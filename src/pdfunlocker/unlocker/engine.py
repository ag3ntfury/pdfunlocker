"""Single-PDF, single-profile, single-rule execution engine.

This module coordinates existing PDF Unlocker components. It does not
select profiles/rules, assign batches, publish final archives, or schedule
jobs. Plaintext candidates are used only in memory.
"""

import hashlib
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from pdfunlocker.learning.candidates import generate_candidates
from pdfunlocker.learning.ranking import load_active_rules
from pdfunlocker.learning.tracker import (
    fail_rule_run,
    finish_rule_run,
    get_rule_run,
    record_candidate_attempt,
    start_rule_run,
)
from pdfunlocker.unlocker import qpdf


MAX_ATTEMPTS_PER_SECOND = 50


@dataclass
class UnlockResult:
    status: str
    sha256: str | None = None
    profile_id: str | None = None
    rule_id: str | None = None
    run_id: int | None = None
    attempted_count: int = 0
    output_path: str | None = None
    output_sha256: str | None = None
    error_code: str | None = None
    message: str | None = None

    def to_dict(self):
        return asdict(self)


def _result(status, **kwargs):
    return UnlockResult(status=status, **kwargs).to_dict()


def _safe_error_code(value, fallback="engine_error"):
    """Return a short non-sensitive machine-readable error code."""
    if not isinstance(value, str):
        return fallback

    value = value.strip().lower()
    if not value or len(value) > 100:
        return fallback

    if not all(char.isalnum() or char in "_-" for char in value):
        return fallback

    return value


def _rule_fingerprint(rules_directory, rule_id):
    path = Path(rules_directory).expanduser() / f"rule{rule_id}.yml"
    if not path.is_file():
        raise FileNotFoundError("Requested rule file does not exist.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _output_path(output_directory, sha256, run_id, candidate_number):
    # All filename components are generated or validated numeric/hash data.
    return (
        Path(output_directory).expanduser()
        / f"{sha256}_run{run_id}_candidate{candidate_number}.pdf"
    )


def _rate_limit(previous_attempt, attempts_per_second):
    if previous_attempt is None:
        return time.monotonic()

    interval = 1.0 / attempts_per_second
    elapsed = time.monotonic() - previous_attempt

    if elapsed < interval:
        time.sleep(interval - elapsed)

    return time.monotonic()


def _finish_error(database_path, run_id, code):
    """Finish an active run-level error without inventing a candidate."""
    details = get_rule_run(database_path, run_id)

    if details is None:
        raise ValueError("Rule run disappeared during execution.")

    if details["run"]["outcome"] != "running":
        return False

    fail_rule_run(database_path, run_id, code)
    return True


def _completed_result(database_path, output_directory, details, base, timeout=120):
    run = details["run"]
    outcome = run["outcome"]

    if outcome == "exhausted":
        return _result("locked", attempted_count=run["attempted_count"], **base)

    if outcome == "no_candidates":
        return _result(
            "no_candidates",
            attempted_count=run["attempted_count"],
            **base,
        )

    if outcome == "skipped":
        return _result("skipped", attempted_count=run["attempted_count"], **base)

    if outcome == "success":
        successful = next(
            (
                item for item in details["attempts"]
                if item["result"] == "success"
            ),
            None,
        )

        if successful is None:
            return _result(
                "error",
                attempted_count=run["attempted_count"],
                error_code="success_record_missing",
                message="The completed run has no successful attempt record.",
                **base,
            )

        destination = _output_path(
            output_directory,
            run["sha256"],
            run["run_id"],
            successful["candidate_number"],
        )

        if destination.is_file():
            verification = qpdf.verify_unlocked(destination, timeout=timeout)
            if verification.status == "verified":
                return _result(
                    "unlocked",
                    attempted_count=run["attempted_count"],
                    output_path=str(destination),
                    output_sha256=verification.output_sha256,
                    **base,
                )

        return _result(
            "error",
            attempted_count=run["attempted_count"],
            error_code="completed_output_missing_or_invalid",
            message="The prior successful output is unavailable or failed verification.",
            **base,
        )

    return _result(
        "error",
        attempted_count=run["attempted_count"],
        error_code="previous_run_error",
        message="The previous run ended with an engine error.",
        **base,
    )


def unlock_one_rule(
    input_path,
    output_directory,
    database_path,
    profile_id,
    rule_id,
    template_path,
    rules_directory,
    batch_number=None,
    expected_sha256=None,
    timeout=120,
    attempts_per_second=MAX_ATTEMPTS_PER_SECOND,
    allow_test_rule=False,
):
    """Execute one active rule for one PDF and one profile.

    The returned successful output is verified but not moved into the
    application's final Unlocked archive. The caller owns publication.
    """

    source = Path(input_path).expanduser()
    output_dir = Path(output_directory).expanduser()

    base = {
        "profile_id": str(profile_id),
        "rule_id": str(rule_id),
    }

    if not source.is_file():
        return _result(
            "corrupted",
            error_code="input_missing",
            message="Input PDF does not exist or is not a regular file.",
            **base,
        )

    if not isinstance(attempts_per_second, int) or isinstance(
        attempts_per_second, bool
    ):
        return _result(
            "error",
            error_code="invalid_attempt_rate",
            message="Attempt rate must be an integer.",
            **base,
        )

    if not 1 <= attempts_per_second <= MAX_ATTEMPTS_PER_SECOND:
        return _result(
            "error",
            error_code="invalid_attempt_rate",
            message="Attempt rate must be between 1 and 50 per second.",
            **base,
        )

    if str(rule_id) == "00000" and not allow_test_rule:
        return _result(
            "error",
            error_code="test_rule_disabled",
            message="Reserved test rule 00000 requires explicit test-mode permission.",
            **base,
        )

    run_id = None

    try:
        sha256 = qpdf.calculate_sha256(source)

        if expected_sha256 is not None and sha256.lower() != str(
            expected_sha256
        ).lower():
            return _result(
                "error",
                sha256=sha256,
                error_code="input_hash_mismatch",
                message="Input PDF does not match the expected SHA-256.",
                **base,
            )

        encryption = qpdf.detect_encryption(source, timeout=timeout)

        if encryption.status == "corrupted":
            return _result(
                "corrupted",
                sha256=sha256,
                error_code=encryption.error_code,
                message="QPDF could not read the input PDF.",
                **base,
            )

        if encryption.status == "not_encrypted":
            return _result(
                "not_encrypted",
                sha256=sha256,
                message="The input PDF is not encrypted.",
                **base,
            )

        if encryption.status != "encrypted":
            return _result(
                "review",
                sha256=sha256,
                error_code=_safe_error_code(
                    encryption.error_code, "encryption_detection_uncertain"
                ),
                message="Encryption detection was inconclusive.",
                **base,
            )

        active_rules = load_active_rules(
            rules_directory,
            allow_test_rule=allow_test_rule,
        )
        if str(rule_id) not in active_rules:
            return _result(
                "error",
                sha256=sha256,
                error_code="rule_not_active",
                message="The requested rule is missing or inactive.",
                **base,
            )

        rule_fingerprint = _rule_fingerprint(rules_directory, str(rule_id))

        candidates = generate_candidates(
            database_path,
            template_path,
            rules_directory,
            str(profile_id),
            str(rule_id),
        )

        candidate_records = candidates["candidates"]
        candidate_set_fingerprint = candidates["candidate_set_fingerprint"]

        output_dir.mkdir(parents=True, exist_ok=True)

        started = start_rule_run(
            database_path,
            sha256,
            str(profile_id),
            str(rule_id),
            rule_fingerprint,
            candidate_set_fingerprint,
            batch_number=batch_number,
        )

        run_id = started["run_id"]
        base.update({"sha256": sha256, "run_id": run_id})

        details = get_rule_run(database_path, run_id)
        if details is None:
            return _result(
                "error",
                error_code="run_record_missing",
                message="Unable to load the learning run record.",
                **base,
            )

        if started["status"] == "already_completed":
            completed_result = _completed_result(
                database_path, output_dir, details, base, timeout=timeout
            )

            # A historical success remains immutable. If its output has
            # disappeared or failed verification, start a separate run.
            if completed_result.get("error_code") != (
                "completed_output_missing_or_invalid"
            ):
                return completed_result

            started = start_rule_run(
                database_path,
                sha256,
                str(profile_id),
                str(rule_id),
                rule_fingerprint,
                candidate_set_fingerprint,
                batch_number=batch_number,
                retry_completed_success=True,
            )

            run_id = started["run_id"]
            base.update({"run_id": run_id})

            details = get_rule_run(database_path, run_id)
            if details is None:
                return _result(
                    "error",
                    error_code="run_record_missing",
                    message="Unable to load the recovery run record.",
                    **base,
                )

            if started["status"] == "already_completed":
                return _completed_result(
                    database_path, output_dir, details, base, timeout=timeout
                )

        attempted_numbers = set(started["attempted_candidates"])
        attempted_count = details["run"]["attempted_count"]
        previous_attempt_time = None

        if not candidate_records:
            finish_rule_run(database_path, run_id, "no_candidates")
            return _result(
                "no_candidates",
                attempted_count=attempted_count,
                **base,
            )

        for candidate in candidate_records:
            number = candidate["number"]

            if number in attempted_numbers:
                continue

            previous_attempt_time = _rate_limit(
                previous_attempt_time, attempts_per_second
            )

            destination = _output_path(
                output_dir, sha256, run_id, number
            )

            # Recover the narrow crash window where QPDF created a verified
            # output but the process stopped before recording the success.
            if destination.exists():
                verification = qpdf.verify_unlocked(
                    destination, timeout=timeout
                )

                if verification.status == "verified":
                    record_candidate_attempt(
                        database_path,
                        run_id,
                        number,
                        candidate["fingerprint"],
                        "success",
                    )
                    return _result(
                        "unlocked",
                        attempted_count=attempted_count + 1,
                        output_path=str(destination),
                        output_sha256=verification.output_sha256,
                        **base,
                    )

                _finish_error(
                    database_path, run_id, "output_path_conflict"
                )
                return _result(
                    "error",
                    attempted_count=attempted_count,
                    error_code="output_path_conflict",
                    message="An existing output path failed verification; it was not overwritten.",
                    **base,
                )

            try:
                attempt = qpdf.decrypt_pdf(
                    source,
                    destination,
                    candidate["value"],
                    timeout=timeout,
                )
            except qpdf.QPDFError as error:
                code = _safe_error_code(error.code, "qpdf_execution_error")
                _finish_error(database_path, run_id, code)
                return _result(
                    "error",
                    attempted_count=attempted_count,
                    error_code=code,
                    message="QPDF reported an execution error.",
                    **base,
                )
            except (OSError, RuntimeError, ValueError):
                _finish_error(
                    database_path, run_id, "qpdf_adapter_exception"
                )
                return _result(
                    "error",
                    attempted_count=attempted_count,
                    error_code="qpdf_adapter_exception",
                    message="The QPDF adapter could not complete the attempt.",
                    **base,
                )

            if attempt.status == "unlocked":
                record_candidate_attempt(
                    database_path,
                    run_id,
                    number,
                    candidate["fingerprint"],
                    "success",
                )
                return _result(
                    "unlocked",
                    attempted_count=attempted_count + 1,
                    output_path=attempt.output_path,
                    output_sha256=attempt.output_sha256,
                    **base,
                )

            if attempt.status == "wrong_password":
                record_candidate_attempt(
                    database_path,
                    run_id,
                    number,
                    candidate["fingerprint"],
                    "failed",
                )
                attempted_count += 1
                continue

            code = _safe_error_code(
                attempt.error_code,
                f"qpdf_{attempt.status}",
            )

            _finish_error(database_path, run_id, code)

            status = (
                "review"
                if attempt.status in {
                    "review", "uncertain", "still_encrypted",
                    "invalid_output",
                }
                else "error"
            )

            return _result(
                status,
                attempted_count=attempted_count,
                error_code=code,
                message="QPDF did not confirm a successful decryption.",
                **base,
            )

        finish_rule_run(database_path, run_id, "exhausted")

        return _result(
            "locked",
            attempted_count=attempted_count,
            **base,
        )

    except Exception:
        # Do not expose exception text: it could contain sensitive input data.
        # Close an active run without changing an already completed run.
        if run_id is not None:
            try:
                _finish_error(
                    database_path,
                    run_id,
                    "engine_unexpected_error",
                )
            except Exception:
                pass

        return _result(
            "error",
            error_code="engine_unexpected_error",
            message="The Unlock Engine could not initialize or complete this run.",
            **base,
        )
