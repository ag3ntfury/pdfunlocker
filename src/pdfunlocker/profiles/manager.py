from __future__ import annotations

import os
import tempfile
import re
from pathlib import Path

from pdfunlocker.paths import APP_DIR, PROFILES_DIR  # noqa: F401
from pdfunlocker.profiles.validation import (
    VALID_COUNTRY_CALLING_CODES, normalize_country_calling_code,
    validate_field_value, validate_profile_values,
)

SEQUENCE_FILE = PROFILES_DIR / "profile_sequence.txt"

PROFILE_FIELDS = (
    ("Personal", (
        "TITLE", "FIRST_NAME", "LAST_NAME", "MIDDLE_NAME", "MOTHER_NAME", "DOB",
    )),
    ("Identity", ("PAN", "AADHAAR")),
    ("Business", ("INCORPORATION_DATE",)),
)


REPEATABLE_FIELDS = (
    ("Personal", "mobile number", "MOBILE"),
    ("Personal", "email address", "EMAIL"),
    ("Personal", "postal code", "PINCODE"),
    ("Business", "TAN", "TAN"),
    ("Business", "GSTIN", "GSTIN"),
    ("Employment", "employee ID", "EMPLOYEE_ID"),
    ("Employment", "UAN", "UAN"),
    ("Employment", "PPO number", "PPO_NUMBER"),
    ("Employment", "PRAN", "PRAN"),
    ("Policy", "policy number", "POLICY_NUMBER"),
)

DISPLAY_LABELS = {
    "TITLE": "Title", "FIRST_NAME": "First Name", "LAST_NAME": "Last Name",
    "MIDDLE_NAME": "Middle Name", "MOTHER_NAME": "Mother Name", "DOB": "DOB",
    "MOBILE": "Mobile Number", "EMAIL": "Email Address", "PINCODE": "PIN Code",
    "PAN": "PAN", "AADHAAR": "Aadhaar", "IFSC": "IFSC", "CIF": "CIF",
    "UAN": "UAN", "PRAN": "PRAN", "PPO_NUMBER": "PPO Number",
    "GSTIN": "GSTIN", "TAN": "TAN", "EMPLOYEE_ID": "Employee ID",
    "POLICY_NUMBER": "Policy Number", "CARD_NO": "Card Number",
    "ACCOUNT_NUMBER": "Account Number", "CUSTOMER_ID": "Customer ID",
    "BANK_NAME": "Bank Name", "INCORPORATION_DATE": "Incorporation Date",
}


def display_label(field: str) -> str:
    key = str(field).upper().replace(" ", "_")
    bank_match = re.fullmatch(r"BANK_1[2-6][0-9]{2}([A-F])", key)
    if bank_match:
        suffix_labels = {
            "A": "Bank Name", "B": "IFSC", "C": "CIF",
            "D": "Customer ID", "E": "Account Number", "F": "Card Number",
        }
        return suffix_labels[bank_match.group(1)]
    return DISPLAY_LABELS.get(key, str(field).replace("_", " ").title())


def _safe_current_value(field: str, value: str) -> str:
    from pdfunlocker.profiles.card_crypto import is_card_field_key, is_encrypted_card, mask_card_value
    if is_card_field_key(field) and (is_encrypted_card(value) or value):
        return mask_card_value(value)
    return value


def ensure_profiles_dir() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def read_sequence() -> int:
    ensure_profiles_dir()

    if not SEQUENCE_FILE.exists():
        return 0

    try:
        return int(
            SEQUENCE_FILE.read_text(encoding="utf-8").strip() or "0"
        )
    except (ValueError, OSError):
        return 0


def next_profile_id() -> int:
    """Reserve the next ID using SQLite, never by scanning .env exports."""
    ensure_profiles_dir()
    sequence_hint = read_sequence()

    from pdfunlocker.profiles import store

    profile_id = store.reserve_profile_id(sequence_hint)
    SEQUENCE_FILE.write_text(f"{profile_id}\n", encoding="utf-8")
    return profile_id

def profile_path(profile_id: int) -> Path:
    return PROFILES_DIR / f"profile{profile_id:02d}.env"


def valid_profile_name(name: str) -> bool:
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,49}",
            name,
        )
    )


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        value = value.replace("\\n", "\n").replace("\\\\", "\\")

        values[key.strip()] = value.strip()

    return values


def _save_env_file(path: Path, values: dict[str, str]) -> None:
    """Atomically write a private legacy profile export."""
    lines = [
        "# PDF Unlocker private profile",
        "# DO NOT COMMIT THIS FILE TO PUBLIC SOURCE CONTROL.",
        "",
    ]

    for key, value in values.items():
        escaped = value.replace("\\", "\\\\").replace("\n", "\\n")
        lines.append(f"{key}={escaped}")

    content = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None

    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
        temp_path = None

        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_env(path: Path) -> dict[str, str]:
    """Load from SQLite and repair its export; never import data from .env."""
    from pdfunlocker.profiles import store

    store.initialize()
    requested_path = Path(path)
    records = store.list_profiles()

    record = next(
        (
            item for item in records
            if item["legacy_path"]
            and Path(item["legacy_path"]) == requested_path
        ),
        None,
    )

    if record is None:
        match = re.fullmatch(
            r"profile(\d+)\.env",
            requested_path.name,
            re.IGNORECASE,
        )
        if match:
            record = next(
                (
                    item for item in records
                    if int(item["profile_id"]) == int(match.group(1))
                ),
                None,
            )

    if record is None:
        return {}

    stored = store.load_profile(int(record["profile_id"]))
    if stored is None:
        return {}

    try:
        if not requested_path.exists() or _load_env_file(requested_path) != stored:
            _save_env_file(requested_path, stored)
    except OSError as exc:
        print(
            "Warning: profile loaded from SQLite, but export repair failed: "
            f"{exc}"
        )

    return stored


def save_env(path: Path, values: dict[str, str]) -> None:
    """Save to SQLite first, then export the canonical database values."""
    from pdfunlocker.profiles import store

    store.save_profile(path, values)

    profile_id_text = str(values.get("PROFILE_ID", "")).strip()
    if not profile_id_text.isdigit():
        raise ValueError("A valid PROFILE_ID is required to save a profile.")

    stored = store.load_profile(int(profile_id_text))
    if stored is None:
        raise RuntimeError(
            "Profile was not available in SQLite after saving; export skipped."
        )

    _save_env_file(path, stored)


def profile_names() -> dict[str, int]:
    """Return profile names from SQLite, independent of .env exports."""
    from pdfunlocker.profiles import store

    return {
        record["name"].strip().casefold(): int(record["profile_id"])
        for record in store.list_profiles()
        if record["name"].strip()
    }


def ask_optional_value(field: str) -> str:
    return input(f"{field}: ").strip()


def ask_profile_name(input_func=input) -> str:
    while True:
        name = input_func("Profile name: ").strip()

        if not name:
            print("Profile name is required.")
            continue

        if not valid_profile_name(name):
            print(
                "Invalid profile name. Use 1-50 characters: "
                "letters, numbers, spaces, _, -, or ."
            )
            continue

        if name.casefold() in profile_names():
            print("A profile with this name already exists.")
            continue

        return name


def normalize_and_validate(field: str, value: str) -> str | None:
    """Personal Mode compatibility wrapper around the reusable validator."""
    normalized, error = validate_field_value(field, value)
    if error:
        print(error)
    return normalized


def _validate_with_correction(field: str, value: str, input_func=input) -> str | None:
    """Validate a value; Enter skips, otherwise the entered correction is revalidated."""
    normalized = normalize_and_validate(field, value)
    while normalized is None:
        correction = input_func(
            "Invalid value. Press Enter to skip or insert a corrected value: "
        ).strip()
        if not correction:
            return None
        normalized = normalize_and_validate(field, correction)
    return normalized

def collect_fixed_fields(
    existing: dict[str, str] | None = None,
    modifying: bool = False,
    input_func=input,
    field_keys: set[str] | None = None,
) -> None:
    from pdfunlocker.profiles import store

    values = existing if existing is not None else {}
    definitions = {
        item["field_key"]: int(item["field_number"])
        for item in store.list_fields(include_archived=True)
    }

    for section, fields in PROFILE_FIELDS:
        selected_fields = [field for field in fields if field_keys is None or field in field_keys]
        if not selected_fields:
            continue
        print(f"--- {section} ---")
        for field in selected_fields:
            number = definitions.get(field)
            definition = next((item for item in store.list_fields(include_archived=True) if item["field_key"] == field), None)
            code = str(definition.get("field_id") or "---") if definition else "---"
            current = values.get(field, "")
            hint = " (Mr/Mrs/Ms/Miss/Dr/Other)" if field == "TITLE" else ""
            label = display_label(field)

            while True:
                if modifying and current:
                    answer = input_func(
                        f"{code} {label}{hint} [{_safe_current_value(field, current)}] (Enter=keep, -=clear): "
                    )
                    if field != "DOB":
                        answer = answer.strip()
                    if not answer:
                        break
                    if answer == "-":
                        values.pop(field, None)
                        break
                else:
                    answer = input_func(f"{code} {label}{hint}: ")
                    if field != "DOB":
                        answer = answer.strip()
                    if not answer:
                        break

                normalized = _validate_with_correction(field, answer, input_func)
                if normalized is not None:
                    values[field] = normalized
                break
        print()

def collect_repeatable_fields(
    values: dict[str, str],
    modifying: bool = False,
    input_func=input,
    prefixes: set[str] | None = None,
) -> None:
    from pdfunlocker.profiles import store

    definitions = {
        item["field_key"]: item
        for item in store.list_fields(include_archived=True)
    }
    profile_id_text = values.get("PROFILE_ID", "0")
    profile_id = int(profile_id_text) if profile_id_text.isdigit() else 0

    for section, label, prefix in REPEATABLE_FIELDS:
        if prefixes is not None and prefix not in prefixes:
            continue
        definition = definitions.get(prefix)
        if not definition or definition.get("archived"):
            continue

        field_number = int(definition["field_number"])
        shown_label = display_label(prefix)
        print(f"--- {section}: {shown_label} ---")
        existing_fields = ([prefix] if prefix in values else [])
        existing_fields.extend(sorted(
            (
                key for key in values
                if key.startswith(f"{prefix}_")
                and key[len(prefix) + 1:].isdigit()
            ),
            key=lambda key: int(key.rsplit("_", 1)[1]),
        ))

        if modifying and existing_fields:
            print(f"Current {shown_label} values:")
            for field in existing_fields:
                sequence = 1 if field == prefix else int(field.rsplit("_", 1)[1])
                code = store.value_code(field_number, sequence, True)
                while True:
                    answer = input_func(
                        f"{code} {shown_label} [{_safe_current_value(field, values[field])}] (Enter=keep, -=clear): "
                    ).strip()
                    if not answer:
                        break
                    if answer == "-":
                        values.pop(field, None)
                        break
                    normalized = _validate_with_correction(field, answer, input_func)
                    if normalized is not None:
                        values[field] = normalized
                    break
            print("Add new values below. Press Enter on an empty value to stop.")

        sequence = store.next_value_sequence(profile_id, prefix, values)
        while True:
            field = f"{prefix}_{sequence:02d}"
            code = store.value_code(field_number, sequence, True)
            prompt = (
                f"{code} Mobile number (default country +91): "
                if prefix == "MOBILE"
                else f"{code} {shown_label}: "
            )
            answer = input_func(prompt).strip()
            if not answer:
                break
            normalized = _validate_with_correction(field, answer, input_func)
            if normalized is None:
                break
            values[field] = normalized
            sequence += 1
        print()

def collect_bank_fields(
    values: dict[str, str],
    modifying: bool = False,
    input_func=input,
) -> None:
    """Collect bank groups using permanent IDs 1200A-1200F onward."""
    from pdfunlocker.profiles import store
    from pdfunlocker.profiles.registry import BANK_FIRST, BANK_LAST, BANK_SUFFIXES, bank_field_key

    profile_id_text = values.get("PROFILE_ID", "0")
    profile_id = int(profile_id_text) if profile_id_text.isdigit() else 0
    group = BANK_FIRST
    print("--- Banking details (optional) ---")
    while group <= BANK_LAST:
        definitions = store.ensure_bank_group(group)
        name_key = bank_field_key(group, "A")
        current_name = values.get(name_key, "")
        bank_number = group - BANK_FIRST + 1
        prompt = f"{group}A Bank {bank_number:02d} name"
        if modifying and current_name:
            answer = input_func(f"{prompt} [{current_name}] (Enter=keep, -=clear): ").strip()
            if answer == "-":
                for suffix in "ABCDEF":
                    prefix = bank_field_key(group, suffix)
                    values.pop(prefix, None)
                    for key in list(values):
                        if key.startswith(prefix + "_"):
                            values.pop(key, None)
                group += 1
                continue
            answer = answer or current_name
        else:
            answer = input_func(f"{prompt} (Enter=finish banks): ").strip()
        if not answer:
            break
        normalized = _validate_with_correction(name_key, answer, input_func)
        if normalized is None:
            break
        values[name_key] = normalized

        for suffix in "BCDEF":
            prefix = bank_field_key(group, suffix)
            _base, label, _multiple = BANK_SUFFIXES[suffix]
            existing = [prefix] if prefix in values else []
            existing.extend(sorted(
                (key for key in values if key.startswith(prefix + "_") and key[len(prefix)+1:].isdigit()),
                key=lambda key: int(key.rsplit("_", 1)[1]),
            ))
            if modifying:
                for old_key in existing:
                    current = values[old_key]
                    while True:
                        old_sequence = int(old_key.rsplit("_", 1)[1]) if "_" in old_key else 1
                        old_code = f"{definitions[ord(suffix)-ord('A')]['field_id']}-{old_sequence:02d}"
                        shown_old_label = (
                            "Card Number (full 12-19 digits; encrypted)"
                            if suffix == "F" else display_label(_base)
                        )
                        answer = input_func(f"{old_code} {shown_old_label} [{_safe_current_value(prefix, current)}] (Enter=keep, -=clear): ").strip()
                        if not answer:
                            break
                        if answer == "-":
                            values.pop(old_key, None)
                            break
                        normalized = _validate_with_correction(old_key, answer, input_func)
                        if normalized is not None:
                            values[old_key] = normalized
                        break
            sequence = store.next_value_sequence(profile_id, prefix, values)
            while True:
                field_key = f"{prefix}_{sequence:02d}"
                code = f"{definitions[ord(suffix)-ord('A')]['field_id']}-{sequence:02d}"
                shown_label = (
                    "Card Number (full 12-19 digits; encrypted)"
                    if suffix == "F" else display_label(_base)
                )
                answer = input_func(f"{code} {shown_label} (Enter=skip): ").strip()
                if not answer:
                    break
                normalized = _validate_with_correction(field_key, answer, input_func)
                if normalized is None:
                    break
                values[field_key] = normalized
                sequence += 1
        group += 1
    print()


def collect_custom_fields(
    values: dict[str, str],
    modifying: bool = False,
    input_func=input,
) -> None:
    from pdfunlocker.profiles import store

    known = {field for _section, fields in PROFILE_FIELDS for field in fields}
    known.update(prefix for _section, _label, prefix in REPEATABLE_FIELDS)
    known.update(item["field_key"] for item in store.list_fields(include_archived=True) if str(item.get("field_key", "")).startswith("BANK_"))
    fields = [
        item for item in store.list_fields()
        if item.get("is_custom")
        and not item["archived"]
        and item["field_key"] not in known
    ]
    if not fields:
        return

    profile_id_text = values.get("PROFILE_ID", "0")
    profile_id = int(profile_id_text) if profile_id_text.isdigit() else 0
    print("--- Custom fields ---")

    for item in fields:
        key = item["field_key"]
        number = int(item["field_number"])
        label = item["label"]

        if item["allows_multiple"]:
            existing_keys = sorted(
                (
                    candidate for candidate in values
                    if candidate.startswith(key + "_")
                    and candidate[len(key) + 1:].isdigit()
                ),
                key=lambda candidate: int(candidate.rsplit("_", 1)[1]),
            )

            for old_key in existing_keys:
                if not modifying:
                    continue
                current = values[old_key]
                while True:
                    answer = input_func(
                        f"{store.value_code(number, int(old_key.rsplit('_', 1)[1]), True)} "
                        f"{label} [{current}] (Enter=keep, -=clear): "
                    ).strip()
                    if not answer:
                        break
                    if answer == "-":
                        values.pop(old_key, None)
                        break
                    normalized = _validate_with_correction(old_key, answer, input_func)
                    if normalized is not None:
                        values[old_key] = normalized
                    break

            sequence = store.next_value_sequence(profile_id, key, values)
            while True:
                answer = input_func(
                    f"{store.value_code(number, sequence, True)} {label}: "
                ).strip()
                if not answer:
                    break
                field = f"{key}_{sequence:02d}"
                normalized = _validate_with_correction(field, answer, input_func)
                if normalized is None:
                    break
                values[field] = normalized
                sequence += 1
        else:
            current = values.get(key, "")
            while True:
                prompt = (
                    f"{store.value_code(number)} {label} "
                    f"[{current}] (Enter=keep, -=clear): "
                    if modifying and current
                    else f"{store.value_code(number)} {label}: "
                )
                answer = input_func(prompt).strip()
                if modifying and current and answer == "-":
                    values.pop(key, None)
                    break
                if not answer:
                    break
                normalized = _validate_with_correction(key, answer, input_func)
                if normalized is not None:
                    values[key] = normalized
                break
    print()

def collect_profile_values(
    existing: dict[str, str] | None = None,
    modifying: bool = False,
    input_func=input,
    include_custom_fields: bool = False,
) -> dict[str, str]:
    values = existing if existing is not None else {}

    print()
    print("Enter profile values.")
    print("Press Enter to skip an optional field.")
    print()

    # Collection order follows permanent public IDs, not implementation groups.
    collect_fixed_fields(values, modifying, input_func, {"TITLE", "FIRST_NAME", "LAST_NAME", "MIDDLE_NAME", "MOTHER_NAME", "DOB"})
    collect_repeatable_fields(values, modifying, input_func, {"MOBILE", "EMAIL", "PINCODE"})
    collect_fixed_fields(values, modifying, input_func, {"PAN", "AADHAAR"})
    collect_bank_fields(values, modifying, input_func)
    collect_fixed_fields(values, modifying, input_func, {"INCORPORATION_DATE"})
    collect_repeatable_fields(values, modifying, input_func, {"TAN", "GSTIN"})
    collect_repeatable_fields(values, modifying, input_func, {"EMPLOYEE_ID", "UAN", "PPO_NUMBER", "PRAN", "POLICY_NUMBER"})
    if include_custom_fields:
        collect_custom_fields(values, modifying, input_func)

    return values



def add_profile() -> int:
    ensure_profiles_dir()

    print()
    print("Add PDF Unlocker Profile")
    print("========================")
    print()

    name = ask_profile_name()
    profile_id = next_profile_id()

    values = {
        "PROFILE_ID": str(profile_id),
        "PROFILE_NAME": name,
    }

    collect_profile_values(values)

    path = profile_path(profile_id)
    save_env(path, values)

    print()
    print("Profile created successfully.")
    print(f"ID   : {profile_id}")
    print(f"Name : {name}")
    print(f"File : {path}")
    print()

    return profile_id


def list_profiles() -> None:
    """Display profiles stored in SQLite, even if exports are missing."""
    from pdfunlocker.profiles import store

    records = store.list_profiles()

    print()
    print("PDF Unlocker Profiles")
    print("=====================")
    print()

    if not records:
        print("No profiles found.")
        print()
        return

    print(f"{'ID':<8}{'NAME':<30}FILE")
    print("-" * 70)

    for record in records:
        profile_id = int(record["profile_id"])
        name = record["name"]
        saved_path = record["legacy_path"]
        path = Path(saved_path) if saved_path else profile_path(profile_id)
        print(f"{profile_id:<8}{name:<30}{path.name}")

    print()


def get_profile(
    profile_id: int,
) -> tuple[Path, dict[str, str]] | None:
    """Retrieve a profile from SQLite, repairing its export when possible."""
    from pdfunlocker.profiles import store

    values = store.load_profile(profile_id)
    if values is None:
        return None

    record = next(
        (
            item for item in store.list_profiles()
            if int(item["profile_id"]) == profile_id
        ),
        None,
    )
    path = (
        Path(record["legacy_path"])
        if record and record["legacy_path"]
        else profile_path(profile_id)
    )

    try:
        if not path.exists() or _load_env_file(path) != values:
            _save_env_file(path, values)
    except OSError as exc:
        print(
            "Warning: profile loaded from SQLite, but export repair failed: "
            f"{exc}"
        )

    return path, values


def show_profile(profile_id: int) -> None:
    result = get_profile(profile_id)

    if result is None:
        print(f"Profile not found: {profile_id}")
        return

    path, values = result
    from pdfunlocker.profiles import store

    print()
    print("PDF Unlocker Profile")
    print("====================")
    print(f"ID   : {values.get('PROFILE_ID', '')}")
    print(f"Name : {values.get('PROFILE_NAME', '')}")
    print(f"File : {path}")
    print()

    current_category = None
    for item in store.list_fields(include_archived=False):
        key = str(item["field_key"])
        field_id = str(item.get("field_id") or item["field_number"])
        category = str(item.get("category") or "Other")
        if category != current_category:
            print(f"--- {category} ---")
            current_category = category

        entries: list[tuple[int, str]] = []
        if key in values:
            entries.append((0, values[key]))
        if item.get("allows_multiple"):
            prefix = key + "_"
            for value_key, value in values.items():
                if value_key.startswith(prefix) and value_key[len(prefix):].isdigit():
                    entries.append((int(value_key[len(prefix):]), value))
        entries.sort(key=lambda pair: pair[0])

        if not entries:
            continue
        label = display_label(key)
        for sequence, value in entries:
            code = (
                store.value_code(int(item["field_number"]), sequence or 1, True)
                if item.get("allows_multiple")
                else field_id
            )
            print(f"{code} {label}: {_safe_current_value(key, value)}")
    print()


def validate_profile(profile_id: int) -> bool:
    result = get_profile(profile_id)

    if result is None:
        print(f"Profile not found: {profile_id}")
        return False

    path, values = result

    print()
    print(f"Validate Profile {profile_id}")
    print("======================")
    print(f"Name : {values.get('PROFILE_NAME', '')}")
    print(f"File : {path}")
    print()

    errors: list[str] = []

    profile_id_value = values.get("PROFILE_ID", "")
    if not profile_id_value.isdigit() or int(profile_id_value) != profile_id:
        errors.append("PROFILE_ID is invalid.")

    profile_name = values.get("PROFILE_NAME", "")
    if not profile_name:
        errors.append("PROFILE_NAME is missing.")
    elif not valid_profile_name(profile_name):
        errors.append("PROFILE_NAME is invalid.")

    errors.extend(validate_profile_values(values))

    if errors:
        print("INVALID")
        print()
        for error in errors:
            print(f"- {error}")
        print()
        print(f"Total errors: {len(errors)}")
        return False

    print("VALID")
    print()
    print("All stored profile values pass the current validation rules.")
    return True

def modify_profile(profile_id: int) -> None:
    result = get_profile(profile_id)

    if result is None:
        print(f"Profile not found: {profile_id}")
        return

    path, values = result

    current_name = values.get("PROFILE_NAME", "")

    print()
    print(f"Modify Profile {profile_id}")
    print("======================")
    print()
    print(f"Current name: {current_name}")

    new_name = input(
        "New profile name [Enter=keep]: "
    ).strip()

    if new_name:
        if not valid_profile_name(new_name):
            print("Invalid profile name.")
            return

        existing = profile_names()
        owner = existing.get(new_name.casefold())

        if owner is not None and owner != profile_id:
            print(f"Profile name already exists: {new_name}")
            return

        values["PROFILE_NAME"] = new_name

    collect_profile_values(
        values,
        modifying=True,
    )

    save_env(path, values)

    print()
    print("Profile updated successfully.")
    print()


def remove_profile(profile_id: int) -> None:
    result = get_profile(profile_id)

    if result is None:
        print(f"Profile not found: {profile_id}")
        return

    path, values = result
    name = values.get("PROFILE_NAME", "")

    print()
    print(f"Profile ID   : {profile_id}")
    print(f"Profile name : {name}")
    print()

    if input("Remove this profile? Enter=No: ").strip() not in {"y", "Y"}:
        print("Profile removal cancelled.")
        return

    from pdfunlocker.profiles import store

    try:
        # Delete from SQLite first. If this fails, preserve the legacy file.
        store.delete_profile(profile_id)
    except Exception as exc:
        print(f"Unable to remove profile from database: {exc}")
        return

    try:
        path.unlink()
    except OSError as exc:
        # The database record is gone, but the legacy file remains as a
        # recoverable export if filesystem deletion fails.
        print(f"Profile removed from database, but unable to remove legacy file: {exc}")
        print(f"Legacy profile file retained at: {path}")
        return

    print("Profile removed.")
    print("The profile ID will not be reused.")
    print()


def list_profile_fields() -> None:
    """List supported field names without exposing stored profile values."""
    print("Supported profile fields")
    print("=========================")
    for section, fields in PROFILE_FIELDS:
        print(f"\n{section}:")
        for field in fields:
            print(f"  {field}")

    print("\nRepeatable fields (numbered suffixes such as _01):")
    for section, label, prefix in REPEATABLE_FIELDS:
        print(f"  {section}: {prefix}_NN — {label}")
    from pdfunlocker.profiles import store
    print("\nSQLite field registry (IDs are assigned automatically):")
    for item in store.list_fields():
        suffix = "A/B/C... per value" if item["allows_multiple"] else "single value"
        state = "archived" if item["archived"] else "active"
        print(f"  {item['field_number']:03d} {item['field_key']:<24} {suffix} [{state}]")
    print("\nAll profile fields are optional unless a particular rule needs them.")


def add_profile_field() -> None:
    from pdfunlocker.profiles import store
    label = input("Field label: ").strip()
    if not label:
        print("Field label is required.")
        return
    default_key = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    key = input(f"Field key [{default_key}]: ").strip() or default_key
    print("Categories: Personal, Identity, Financial, Benefits & Retirement, Tax & Business, Custom")
    category = input("Category [Custom]: ").strip() or "Custom"
    valid_categories = {"Personal", "Identity", "Financial", "Benefits & Retirement", "Tax & Business", "Custom"}
    if category not in valid_categories:
        print("Unknown category. Use one of the listed categories.")
        return
    multiple_answer = input("Allow multiple values? [y/N]: ").strip().lower()
    try:
        number, key = store.add_field(label, key, multiple_answer in {"y", "yes"}, category)
    except (ValueError, OSError) as exc:
        print(f"Cannot add field: {exc}")
        return
    suffix = "A, B, C..." if multiple_answer in {"y", "yes"} else "single value"
    print(f"Field added: {number:03d} {key} ({suffix})")
    print("This field is now available to all profiles.")


def archive_profile_field(field_key: str) -> None:
    from pdfunlocker.profiles import store
    try:
        store.archive_field(field_key)
    except (ValueError, OSError) as exc:
        print(f"Cannot archive field: {exc}")
        return
    print(f"Field archived: {field_key.upper()}. Existing values are retained.")


def list_profile_registry() -> None:
    from pdfunlocker.profiles import store
    print("Profile field registry")
    print("======================")
    fields = store.list_fields()
    order = ("Personal", "Identity", "Financial", "Benefits & Retirement", "Tax & Business", "Custom", "Business")
    for category in order:
        grouped = [item for item in fields if item.get("category", "Custom") == category]
        if not grouped:
            continue
        print(f"\n--- {category} ---")
        for item in grouped:
            mode = "multiple (A/B/C...)" if item["allows_multiple"] else "single"
            print(f"{item['field_number']:03d}  {item['field_key']:<24} {item['label']} [{mode}]")
    archived = store.list_fields(include_archived=True)
    archived = [item for item in archived if item["archived"]]
    if archived:
        print("\n--- Archived (IDs retained) ---")
        for item in archived:
            print(f"{item['field_number']:03d}  {item['field_key']:<24} {item['label']} [archived]")


def check_profile(profile_id: int) -> bool:
    """Report absent and empty supported fields without displaying their values."""
    result = get_profile(profile_id)
    if result is None:
        print(f"Profile not found: {profile_id}")
        return False

    path, values = result
    print(f"Profile check: {profile_id}")
    print(f"Name: {values.get('PROFILE_NAME', '(unnamed)')}")
    print(f"File: {path}")
    print("Stored field values are not displayed.")
    print()

    missing = []
    empty = []

    for section, fields in PROFILE_FIELDS:
        for field in fields:
            if field not in values:
                missing.append((section, field))
            elif not values[field].strip():
                empty.append((section, field))

    for section, label, prefix in REPEATABLE_FIELDS:
        present = sorted(
            ([prefix] if prefix in values else []) + [
                key for key in values
                if key.startswith(prefix + "_") and key[len(prefix) + 1:].isdigit()
            ],
            key=lambda key: 0 if key == prefix else int(key.rsplit("_", 1)[1]),
        )
        if not present:
            missing.append((section, f"{prefix}_NN ({label}; none configured)"))
        else:
            for field in present:
                if not values[field].strip():
                    empty.append((section, field))

    print(f"Missing/unconfigured fields: {len(missing)}")
    for section, field in missing:
        print(f"  MISSING [{section}]: {field}")

    print(f"Empty stored fields: {len(empty)}")
    for section, field in empty:
        print(f"  EMPTY [{section}]: {field}")

    print("\nThese are diagnostic hints, not mandatory requirements.")
    print("Only add information that genuinely applies to your PDFs.")
    return not missing and not empty
