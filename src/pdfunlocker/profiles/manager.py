from __future__ import annotations

import os
import tempfile
import re
from pathlib import Path

from pdfunlocker.paths import APP_DIR, PROFILES_DIR  # noqa: F401

SEQUENCE_FILE = PROFILES_DIR / "profile_sequence.txt"

PROFILE_FIELDS = (
    ("Personal", (
        "FIRST_NAME", "MIDDLE_NAME", "LAST_NAME", "MOTHER_NAME",
        "BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR", "PINCODE",
    )),
    ("Identity", (
        "PAN", "AADHAAR_FIRST4", "AADHAAR_LAST4",
    )),
    ("Financial", ("ACCOUNT_TITLE",)),
    ("Benefits & Retirement", ()),
    ("Tax & Business", ()) ,
)

REPEATABLE_FIELDS = (
    ("Personal", "mobile number", "MOBILE"),
    ("Personal", "email address", "EMAIL"),
    ("Financial", "account number", "ACCOUNT_NUMBER"),
    ("Financial", "credit card number", "CREDIT_CARD_NUMBER"),
    ("Identity", "customer ID", "CUSTOMER_ID"),
    ("Identity", "employee ID", "EMPLOYEE_ID"),
    ("Identity", "roll number", "ROLL_NUMBER"),
    ("Financial", "IFSC", "IFSC"),
    ("Financial", "CIF", "CIF"),
    ("Benefits & Retirement", "UAN", "UAN"),
    ("Benefits & Retirement", "PRAN", "PRAN"),
    ("Benefits & Retirement", "policy number", "POLICY_NUMBER"),
    ("Benefits & Retirement", "PPO number", "PPO_NUMBER"),
    ("Tax & Business", "TAN", "TAN"),
    ("Tax & Business", "GSTIN", "GSTIN"),
)


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


# ITU-assigned international country calling codes.
VALID_COUNTRY_CALLING_CODES = frozenset("""
1 7 20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49
51 52 53 54 55 56 57 58 60 61 62 63 64 65 66 81 82 84 86
90 91 92 93 94 95 98
211 212 213 216 218
220 221 222 223 224 225 226 227 228 229
230 231 232 233 234 235 236 237 238 239
240 241 242 243 244 245 246 247 248 249
250 251 252 253 254 255 256 257 258 260
261 262 263 264 265 266 267 268 269
290 291 297 298 299
350 351 352 353 354 355 356 357 358 359
370 371 372 373 374 375 376 377 378 380
381 382 383 385 386 387 389
420 421 423
500 501 502 503 504 505 506 507 508 509
590 591 592 593 594 595 596 597 598 599
670 672 673 674 675 676 677 678 679
680 681 682 683 685 686 687 688 689 690
691 692
850 852 853 855 856 880 886
960 961 962 963 964 965 966 967 968 970
971 972 973 974 975 976 977
992 993 994 995 996 998
""".split())


def normalize_country_calling_code(value: str) -> str | None:
    """Normalize and validate an international country calling code."""
    value = value.strip()

    if not value:
        return "+91"

    if not re.fullmatch(r"\+?[0-9]{1,3}", value):
        print("Invalid country calling code. Enter a valid code, such as 91 or 92.")
        return None

    digits = value.removeprefix("+")

    if digits not in VALID_COUNTRY_CALLING_CODES:
        print("Invalid country calling code. Enter a valid code, such as 91 or 92.")
        return None

    return f"+{digits}"


def normalize_and_validate(field: str, value: str) -> str | None:
    value = value.strip()

    if not value:
        return ""

    if field in {
        "FIRST_NAME", "MIDDLE_NAME", "LAST_NAME", "PAN",
        "IFSC", "CIF", "UAN", "PRAN", "TAN", "GSTIN",
        "POLICY_NUMBER", "PPO_NUMBER", "EMPLOYEE_ID", "ROLL_NUMBER",
        "ACCOUNT_TITLE", "MOTHER_NAME",
    } or field.startswith(("EMAIL_", "IFSC_", "CIF_", "UAN_", "PRAN_", "TAN_", "GSTIN_", "POLICY_NUMBER_", "PPO_NUMBER_", "EMPLOYEE_ID_", "ROLL_NUMBER_")):
        return value.upper()

    if field in {"BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR", "PINCODE",
                 "AADHAAR_FIRST4", "AADHAAR_LAST4"}:
        if not value.isdigit():
            print(f"{field} must contain digits only.")
            return None

        if field == "BIRTH_DAY" and not 1 <= int(value) <= 31:
            print("BIRTH_DAY must be between 1 and 31.")
            return None

        if field == "BIRTH_MONTH" and not 1 <= int(value) <= 12:
            print("BIRTH_MONTH must be between 1 and 12.")
            return None

        if field == "BIRTH_YEAR" and len(value) != 4:
            print("BIRTH_YEAR must contain exactly 4 digits.")
            return None

        if field == "PINCODE" and len(value) != 6:
            print("PINCODE must contain exactly 6 digits.")
            return None

        if field in {"AADHAAR_FIRST4", "AADHAAR_LAST4"} and len(value) != 4:
            print(f"{field} must contain exactly 4 digits.")
            return None

        return value

    if field.startswith("MOBILE_"):
        if not value.startswith("+"):
            print("Mobile number must include country code, for example +91.")
            return None

        digits = value[1:].replace(" ", "").replace("-", "")

        if not digits.isdigit():
            print("Mobile number must contain + followed by digits.")
            return None

        if not 7 <= len(digits) <= 15:
            print("Mobile number must contain 7 to 15 digits after the country code.")
            return None

        return f"+{digits}"

    if field.startswith("ACCOUNT_NUMBER_"):
        value = value.replace(" ", "").replace("-", "")

        if not value.isdigit():
            print("Account number must contain digits only.")
            return None

        return value

    if field.startswith("CREDIT_CARD_NUMBER_"):
        value = value.replace(" ", "").replace("-", "")

        if not value.isdigit():
            print("Credit card number must contain digits only.")
            return None

        if len(value) != 16:
            print("Credit card number must contain exactly 16 digits.")
            return None

        return value

    if field.startswith("CUSTOMER_ID_"):
        return value.upper()

    return value


def collect_fixed_fields(
    existing: dict[str, str] | None = None,
    modifying: bool = False,
    input_func=input,
) -> None:
    values = existing if existing is not None else {}

    for section, fields in PROFILE_FIELDS:
        print(f"--- {section} ---")

        for field in fields:
            current = values.get(field, "")

            if modifying and current:
                while True:
                    value = input_func(
                        f"{field} [{current}] "
                        "(Enter=keep, -=clear): "
                    ).strip()

                    if not value:
                        break

                    if value == "-":
                        values.pop(field, None)
                        break

                    normalized = normalize_and_validate(field, value)

                    if normalized is not None:
                        values[field] = normalized
                        break

            else:
                while True:
                    value = input_func(f"{field}: ").strip()

                    if not value:
                        break

                    normalized = normalize_and_validate(field, value)

                    if normalized is not None:
                        values[field] = normalized
                        break

        print()


def collect_repeatable_fields(
    values: dict[str, str],
    modifying: bool = False,
    input_func=input,
) -> None:
    from pdfunlocker.profiles import store

    definitions = {
        item["field_key"]: item
        for item in store.list_fields(include_archived=True)
    }
    profile_id_text = values.get("PROFILE_ID", "0")
    profile_id = int(profile_id_text) if profile_id_text.isdigit() else 0

    for section, label, prefix in REPEATABLE_FIELDS:
        definition = definitions.get(prefix)
        if not definition or definition.get("archived"):
            continue

        field_number = int(definition["field_number"])
        print(f"--- {section}: {label.title()} ---")
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
            print(f"Current {label} values:")
            for field in existing_fields:
                sequence = 1 if field == prefix else int(field.rsplit("_", 1)[1])
                code = store.value_code(field_number, sequence, True)
                while True:
                    value = input_func(
                        f"{code} {label.title()} [{values[field]}] "
                        "(Enter=keep, -=clear): "
                    ).strip()
                    if not value:
                        break
                    if value == "-":
                        values.pop(field, None)
                        break
                    normalized = normalize_and_validate(field, value)
                    if normalized is None:
                        continue
                    values[field] = normalized
                    break
            print("Add new values below. Press Enter on an empty value to stop.")

        sequence = store.next_value_sequence(profile_id, prefix, values)
        while True:
            field = f"{prefix}_{sequence:02d}"
            code = store.value_code(field_number, sequence, True)

            if prefix == "MOBILE":
                while True:
                    country_code_input = input_func(
                        f"{code} Mobile country code [default +91]: "
                    ).strip()
                    country_code = normalize_country_calling_code(
                        country_code_input
                    )
                    if country_code is not None:
                        break

                number_text = input_func(
                    f"{code} Mobile number: "
                ).strip()
                if not number_text:
                    break
                normalized = normalize_and_validate(
                    field, f"{country_code}{number_text}"
                )
            else:
                value = input_func(f"{code} {label.title()}: ").strip()
                if not value:
                    break
                normalized = normalize_and_validate(field, value)

            if normalized is None:
                continue
            values[field] = normalized
            sequence += 1
        print()


def collect_custom_fields(
    values: dict[str, str],
    modifying: bool = False,
    input_func=input,
) -> None:
    from pdfunlocker.profiles import store

    known = {field for _section, fields in PROFILE_FIELDS for field in fields}
    known.update(prefix for _section, _label, prefix in REPEATABLE_FIELDS)
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
                current = values[old_key]
                if not modifying:
                    continue
                answer = input_func(
                    f"{store.value_code(number, int(old_key.rsplit('_', 1)[1]), True)} "
                    f"{label} [{current}] (Enter=keep, -=clear): "
                ).strip()
                if answer == "-":
                    values.pop(old_key, None)
                elif answer:
                    normalized = normalize_and_validate(old_key, answer)
                    if normalized is not None:
                        values[old_key] = normalized

            sequence = store.next_value_sequence(profile_id, key, values)
            while True:
                answer = input_func(
                    f"{store.value_code(number, sequence, True)} "
                    f"{label}: "
                ).strip()
                if not answer:
                    break
                normalized = normalize_and_validate(
                    f"{key}_{sequence:02d}", answer
                )
                if normalized is None:
                    continue
                values[f"{key}_{sequence:02d}"] = normalized
                sequence += 1
        else:
            current = values.get(key, "")
            prompt = (
                f"{store.value_code(number)} {label} "
                f"[{current}] (Enter=keep, -=clear): "
                if modifying and current
                else f"{store.value_code(number)} {label}: "
            )
            answer = input_func(prompt).strip()
            if modifying and answer == "-":
                values.pop(key, None)
            elif answer:
                normalized = normalize_and_validate(key, answer)
                if normalized is not None:
                    values[key] = normalized
    print()


def collect_profile_values(
    existing: dict[str, str] | None = None,
    modifying: bool = False,
    input_func=input,
) -> dict[str, str]:
    values = existing if existing is not None else {}

    print()
    print("Enter profile values.")
    print("Press Enter to skip an optional field.")
    print()

    collect_fixed_fields(values, modifying, input_func)
    collect_repeatable_fields(values, modifying, input_func)
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

    print()
    print("PDF Unlocker Profile")
    print("====================")
    print(f"ID   : {values.get('PROFILE_ID', '')}")
    print(f"Name : {values.get('PROFILE_NAME', '')}")
    print(f"File : {path}")
    print()

    for section, fields in PROFILE_FIELDS:
        print(f"--- {section} ---")

        for field in fields:
            if field in values:
                print(f"{field}: {values[field]}")

        print()

    for section, label, prefix in REPEATABLE_FIELDS:
        display_section = {
            "MOBILE": "Mobile",
            "EMAIL": "Email",
            "ACCOUNT_NUMBER": "Account Numbers",
            "CREDIT_CARD_NUMBER": "Credit Card Numbers",
            "CUSTOMER_ID": "Customer IDs",
        }.get(prefix, section)

        print(f"--- {display_section} ---")

        from pdfunlocker.profiles import store
        definition = next((item for item in store.list_fields(include_archived=True) if item["field_key"] == prefix), None)
        fields = ([ (prefix, 1) ] if prefix in values else [])
        fields.extend((key, int(key.rsplit("_", 1)[1])) for key in sorted(
            (key for key in values if key.startswith(f"{prefix}_") and key[len(prefix) + 1:].isdigit()),
            key=lambda key: int(key.rsplit("_", 1)[1]),
        ))
        if not fields:
            print("(none)")
        else:
            for field, sequence in fields:
                code = store.value_code(int(definition["field_number"]), sequence, True) if definition else field
                print(f"{code} {label.title()}: {values[field]}")

        print()

    from pdfunlocker.profiles import store
    known = {field for _section, fields in PROFILE_FIELDS for field in fields}
    known.update(prefix for _section, _label, prefix in REPEATABLE_FIELDS)
    for item in store.list_fields():
        key = item["field_key"]
        if not item.get("is_custom") or item["archived"] or key in known:
            continue
        print(f"--- {item['label']} (field {item['field_number']:03d}) ---")
        if item["allows_multiple"]:
            for value_key in sorted((k for k in values if k.startswith(key + "_") and k[len(key)+1:].isdigit()), key=lambda k: int(k.rsplit("_", 1)[1])):
                sequence = int(value_key.rsplit("_", 1)[1])
                print(f"{store.value_code(int(item['field_number']), sequence, True)}: {values[value_key]}")
        elif key in values:
            print(f"{store.value_code(int(item['field_number']))}: {values[key]}")
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

    for section, fields in PROFILE_FIELDS:
        for field in fields:
            if field not in values:
                continue

            value = values[field]
            normalized = normalize_and_validate(field, value)

            if normalized is None:
                errors.append(f"{field}: invalid value.")

    for _section, _label, prefix in REPEATABLE_FIELDS:
        fields = sorted(
            (
                key
                for key in values
                if key.startswith(f"{prefix}_")
                and key[len(prefix) + 1:].isdigit()
            ),
            key=lambda key: int(key.rsplit("_", 1)[1]),
        )

        for field in fields:
            value = values[field]
            normalized = normalize_and_validate(field, value)

            if normalized is None:
                errors.append(f"{field}: invalid value.")
                continue

            if normalized != value:
                errors.append(
                    f"{field}: normalization required."
                )

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
