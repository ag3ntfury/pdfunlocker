from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from pdfunlocker.database.manager import (
    claim_pdf,
    initialize_database,
    list_pdfs,
    record_attempt,
    update_status,
)
from pdfunlocker.pdf.candidates import iter_rule_candidates
from pdfunlocker.pdf.engine import check_pdf, try_password, unlock_pdf
from pdfunlocker.profiles.manager import get_profile
from pdfunlocker.rules.manager import load_executable_rules


MAX_ATTEMPTS_PER_SECOND = 50.0


def ensure_schema() -> None:
    """Compatibility wrapper for centralized database initialization."""
    initialize_database()

def profile_ids() -> list[int]:
    from pdfunlocker.paths import PROFILES_DIR

    profiles_dir = PROFILES_DIR

    ids: list[int] = []

    for path in profiles_dir.glob("profile*.env"):
        stem = path.stem

        if not stem.startswith("profile"):
            continue

        number = stem[7:]

        if number.isdigit():
            ids.append(int(number))

    return sorted(set(ids))


def safe_output_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)

    candidate = directory / filename

    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix

    index = 2

    while True:
        candidate = directory / f"{stem} ({index}){suffix}"

        if not candidate.exists():
            return candidate

        index += 1


def process_one_pdf(
    record,
    profiles: list[int],
    rules,
    original_directory: Path,
    unlocked_directory: Path,
) -> str:
    pdf_id = int(record["id"])
    source_path = Path(record["source_path"])

    # The original may already have been moved after an earlier run.
    if not source_path.is_file():
        original_hint = record["original_path"]
        unlocked_hint = record["unlocked_path"]
        candidates_to_check = [
            Path(original_hint) if original_hint else None,
            Path(unlocked_hint) if unlocked_hint else None,
        ]
        source_path = next(
            (candidate for candidate in candidates_to_check
             if candidate is not None and candidate.is_file()),
            source_path,
        )

    if not source_path.is_file():
        update_status(
            pdf_id,
            "failed",
            error="Source and stored output PDF paths do not exist",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        print(f"[PDF {pdf_id}] SOURCE MISSING")
        return "failed"

    pdf_check = check_pdf(source_path)
    if pdf_check.success and not pdf_check.encrypted:
        update_status(
            pdf_id,
            "skipped",
            error="PDF is already unencrypted; no password attempts made",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        print(f"[PDF {pdf_id}] SKIPPED: already unencrypted")
        return "skipped"

    if not pdf_check.encrypted:
        update_status(
            pdf_id,
            "failed",
            error=pdf_check.error or "PDF validation failed",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        print(f"[PDF {pdf_id}] INVALID OR CORRUPTED: {pdf_check.error}")
        return "failed"

    attempt_number = 0
    attempted_passwords: set[str] = set()

    print(f"[PDF {pdf_id}] {record['filename']}")
    print("  Processing...")

    for profile_id in profiles:
        profile_result = get_profile(profile_id)

        if profile_result is None:
            print(f"  Profile {profile_id}: unavailable, skipped")
            continue

        _profile_path, profile = profile_result
        profile_name = profile.get("PROFILE_NAME", "").strip()

        if not profile_name:
            print(f"  Profile {profile_id}: invalid name, skipped")
            continue

        applicable_rules = 0
        skipped_rules = 0

        for rule in rules:
            found_candidate = False

            for candidate in iter_rule_candidates(rule, profile):
                if not found_candidate:
                    found_candidate = True
                    applicable_rules += 1

                password = candidate.password

                if password in attempted_passwords:
                    continue

                attempted_passwords.add(password)

                attempt_number += 1

                attempt_started = time.monotonic()

                success = try_password(
                    source_path,
                    password,
                )

                elapsed_ms = (
                    time.monotonic() - attempt_started
                ) * 1000.0

                record_attempt(
                    pdf_id=pdf_id,
                    profile_name=profile_name,
                    attempt_number=attempt_number,
                    pattern_identifier=rule.rule_id,
                    result="success" if success else "failed",
                    elapsed_ms=elapsed_ms,
                    rule_id=rule.rule_id,
                )

                if success:
                    # Preserve the source PDF in its current location.
                    original_path = source_path

                    unlocked_path = safe_output_path(
                        unlocked_directory,
                        record["filename"],
                    )

                    unlock_result = unlock_pdf(
                        source_path,
                        password,
                        unlocked_path,
                    )

                    if not unlock_result.success:
                        update_status(
                            pdf_id,
                            "failed",
                            attempt_count=attempt_number,
                            error="Password verified but PDF decryption failed",
                            processed_at=datetime.now(timezone.utc).isoformat(),
                        )

                        print(
                            f"  ERROR: password verification succeeded "
                            f"but decryption failed at attempt {attempt_number}"
                        )
                        return "failed"

                    output_check = check_pdf(unlocked_path)
                    if not output_check.success or output_check.encrypted:
                        try:
                            unlocked_path.unlink(missing_ok=True)
                        except OSError:
                            pass

                        update_status(
                            pdf_id,
                            "failed",
                            attempt_count=attempt_number,
                            error="Decryption output failed the unencrypted PDF check",
                            processed_at=datetime.now(timezone.utc).isoformat(),
                        )
                        print(
                            "  ERROR: output could not be verified as unencrypted"
                        )
                        return "failed"

                    update_status(
                        pdf_id,
                        "unlocked",
                        original_path=str(original_path),
                        unlocked_path=str(unlocked_path),
                        profile_used=profile_name,
                        pattern_identifier=rule.rule_id,
                        rule_id=rule.rule_id,
                        attempt_count=attempt_number,
                        processed_at=datetime.now(timezone.utc).isoformat(),
                        error=None,
                    )

                    print("  RESULT: UNLOCKED")
                    print(f"  Profile: {profile_name}")
                    print(f"  Rule: {rule.number} ({rule.rule_id})")
                    print(f"  Attempts: {attempt_number}")
                    print(f"  Output: {unlocked_path}")
                    print()

                    return "unlocked"

                minimum_interval = 1.0 / MAX_ATTEMPTS_PER_SECOND

                if elapsed_ms / 1000.0 < minimum_interval:
                    time.sleep(
                        minimum_interval - (elapsed_ms / 1000.0)
                    )

            if not found_candidate:
                skipped_rules += 1

        print(
            f"  Profile {profile_id} ({profile_name}): "
            f"applicable_rules={applicable_rules}, "
            f"skipped_rules={skipped_rules}"
        )

    update_status(
        pdf_id,
        "failed",
        attempt_count=attempt_number,
        error="No configured candidate succeeded",
        processed_at=datetime.now(timezone.utc).isoformat(),
    )

    print("  RESULT: NOT UNLOCKED")
    print(f"  Attempts: {attempt_number}")
    print()

    return "failed"


def unlock_all(
    original_directory: Path,
    unlocked_directory: Path,
    *,
    dry_run: bool = False,
    retry_failed: bool = False,
    pdf_id: int | None = None,
) -> None:
    if not dry_run:
        ensure_schema()

    all_records = list_pdfs()

    if pdf_id is not None:
        matching = [
            record for record in all_records
            if int(record["id"]) == pdf_id
        ]
        if not matching:
            print(f"PDF record ID {pdf_id} was not found.")
            return

        selected = matching[0]
        allowed = {"pending"}
        if retry_failed:
            allowed.add("failed")

        if selected["status"] not in allowed:
            print(
                f"PDF record ID {pdf_id} has status {selected['status']!r}. "
                f"Eligible statuses: {', '.join(sorted(allowed))}."
            )
            return
        records = [selected]
    else:
        records = [
            record for record in all_records
            if record["status"] == "pending"
            or (retry_failed and record["status"] == "failed")
        ]

    print("PDF Unlocker")
    print("============")
    print()
    print(f"PDF records : {len(records)}")
    print(f"Retry failed: {'YES' if retry_failed else 'NO'}")
    print(f"Dry run     : {'YES' if dry_run else 'NO'}")
    print(f"PDF ID      : {pdf_id if pdf_id is not None else 'ALL ELIGIBLE'}")
    print()

    if not records:
        print("No eligible PDFs to process.")
        return

    if dry_run:
        print("===== DRY RUN: NO PASSWORD ATTEMPTS =====")
        for record in records:
            source = Path(record["source_path"])
            if not source.is_file():
                hints = [record["original_path"], record["unlocked_path"]]
                source = next(
                    (
                        Path(hint) for hint in hints
                        if hint and Path(hint).is_file()
                    ),
                    source,
                )

            if not source.is_file():
                state = "MISSING"
            else:
                try:
                    check = check_pdf(source)
                    if check.success and not check.encrypted:
                        state = "UNENCRYPTED"
                    elif check.encrypted:
                        state = "ENCRYPTED"
                    else:
                        state = "INVALID/INCONCLUSIVE"
                except Exception as exc:
                    state = f"CHECK ERROR: {exc}"

            print(
                f"ID={record['id']} | {record['filename']} | "
                f"status={record['status']} | {state}"
            )

        print(f"Previewed: {len(records)}")
        print("No passwords attempted; no file or database changes requested.")
        return

    profiles = profile_ids()
    rules = load_executable_rules()

    print(f"Profiles    : {len(profiles)}")
    print(f"Rules       : {len(rules)}")
    print(f"Rate limit  : {MAX_ATTEMPTS_PER_SECOND:.0f} attempts/sec")
    print()

    if not profiles:
        print("No profiles found.")
        print("Add one with: pdfunlocker profile add")
        return

    if not rules:
        print("No rules configured; no password attempts made.")
        print("Add rules when you are ready, then run the unlock command again.")
        return

    totals = {
        "unlocked": 0,
        "skipped": 0,
        "failed": 0,
        "not_claimed": 0,
    }

    for record in records:
        claimed = claim_pdf(
            int(record["id"]),
            retry_failed=retry_failed,
        )
        if not claimed:
            totals["not_claimed"] += 1
            print(
                f"[PDF {record['id']}] NOT CLAIMED: "
                "already processing or no longer eligible"
            )
            continue

        result = process_one_pdf(
            record,
            profiles,
            rules,
            original_directory,
            unlocked_directory,
        )
        totals[result if result in {"unlocked", "skipped", "failed"} else "failed"] += 1

    processed = totals["unlocked"] + totals["skipped"] + totals["failed"]
    print("===== UNLOCK SUMMARY =====")
    print(f"Selected  : {len(records)}")
    print(f"Processed : {processed}")
    print(f"Unlocked  : {totals['unlocked']}")
    print(f"Skipped   : {totals['skipped']}")
    print(f"Failed    : {totals['failed']}")
    print(f"Not claimed: {totals['not_claimed']}")
    print()
