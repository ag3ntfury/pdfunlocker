"""Multi-profile CLI for PDF Unlocker.

The SQLite profile store remains authoritative. This module does not migrate
or recreate the database and never allocates profile or field identifiers
outside the existing store/registry implementations.
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


@contextmanager
def profile_storage_context() -> Iterator[None]:
    """Bind profile operations to configured storage, allowing multiple profiles."""
    from pdfunlocker.cli import installer
    from pdfunlocker.profiles import manager, store

    config_path = installer.find_installation_config()

    if config_path is None:
        dev_mode = os.environ.get("PDFUNLOCKER_PROFILE_DEV_MODE", "").strip().lower()
        if dev_mode not in {"1", "true", "yes"}:
            raise RuntimeError(
                "No completed Personal installation was found. Run "
                "'pdfunlocker setup' first. For an intentional source-checkout "
                "workflow only, set PDFUNLOCKER_PROFILE_DEV_MODE=1."
            )
        yield
        return

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"Cannot read installation configuration: {exc}") from exc

    if not isinstance(config, dict) or config.get("setup_complete") is not True:
        raise RuntimeError("The installation configuration is incomplete.")

    if config.get("edition") != "personal":
        raise RuntimeError("Unsupported installation edition for profile management.")

    database_directory = config.get("database_directory")
    profiles_directory = config.get("profiles_directory")

    if not isinstance(database_directory, str) or not database_directory.strip():
        raise RuntimeError("The configured database directory is missing.")

    if not isinstance(profiles_directory, str) or not profiles_directory.strip():
        raise RuntimeError("The configured profiles directory is missing.")

    db_path = Path(database_directory).expanduser().resolve() / "profiles.sqlite3"
    profiles_path = Path(profiles_directory).expanduser().resolve()

    old_db_path = store.DB_PATH
    old_profiles_dir = manager.PROFILES_DIR
    old_sequence_file = manager.SEQUENCE_FILE

    try:
        store.DB_PATH = db_path
        manager.PROFILES_DIR = profiles_path
        manager.SEQUENCE_FILE = profiles_path / "profile_sequence.txt"
        yield
    finally:
        store.DB_PATH = old_db_path
        manager.PROFILES_DIR = old_profiles_dir
        manager.SEQUENCE_FILE = old_sequence_file


def _normalize_name(value: str) -> str:
    return " ".join(str(value).split())


def _ask_profile_name() -> str:
    from pdfunlocker.profiles import manager, store

    while True:
        name = _normalize_name(input("Profile name: "))

        if not name:
            print("Profile name is required.")
            continue

        if not manager.valid_profile_name(name):
            print(
                "Invalid profile name. Use 1-50 characters: "
                "letters, numbers, spaces, _, -, or ."
            )
            continue

        duplicate = any(
            _normalize_name(record["name"]).casefold() == name.casefold()
            for record in store.list_profiles()
        )

        if duplicate:
            print("A profile with this name already exists.")
            continue

        return name


def _profile_record(profile_id: int) -> dict | None:
    from pdfunlocker.profiles import store

    return next(
        (
            record for record in store.list_profiles()
            if int(record["profile_id"]) == profile_id
        ),
        None,
    )


def _safe_export_path(record: dict, profile_id: int) -> Path:
    """Resolve an export path without allowing writes outside the profiles directory."""
    from pdfunlocker.profiles import manager

    root = manager.PROFILES_DIR.expanduser().resolve()
    saved = str(record.get("legacy_path") or "").strip()

    path = (
        Path(saved).expanduser()
        if saved
        else manager.profile_path(profile_id)
    )

    resolved = path.resolve()

    if resolved.parent != root:
        raise RuntimeError(
            f"Profile {profile_id} references an export outside the configured "
            "profiles directory. Refusing to write or delete that file."
        )

    return resolved


def _load_profile(profile_id: int) -> tuple[dict, dict[str, str]] | None:
    from pdfunlocker.profiles import store

    record = _profile_record(profile_id)
    if record is None:
        return None

    values = store.load_profile(profile_id)
    if values is None:
        return None

    return record, values


def command_add(_: argparse.Namespace) -> None:
    from pdfunlocker.profiles import manager

    name = _ask_profile_name()

    # IDs are reserved atomically by the existing SQLite high-water mark.
    profile_id = manager.next_profile_id()

    values = {
        "PROFILE_ID": str(profile_id),
        "PROFILE_NAME": name,
    }

    manager.collect_profile_values(
        values,
        modifying=False,
        input_func=input,
        include_custom_fields=True,
    )

    path = manager.profile_path(profile_id)
    manager.save_env(path, values)

    print()
    print("Profile created successfully.")
    print(f"ID   : {profile_id}")
    print(f"Name : {name}")
    print(f"File : {path}")
    print()


def command_list(_: argparse.Namespace) -> None:
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

    print(f"{'ID':<10}{'NAME':<32}EXPORT")
    print("-" * 78)

    for record in records:
        profile_id = int(record["profile_id"])
        name = record["name"]
        export = Path(record["legacy_path"]).name if record["legacy_path"] else "-"
        print(f"{profile_id:<10}{name:<32}{export}")

    print()
    print(f"Total profiles: {len(records)}")
    print()


def _display_value(field_key: str, value: str) -> str:
    """Mask stored values by default; never reveal secrets in CLI output."""
    value = str(value)
    if not value:
        return "[empty]"
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _public_field_id(item: dict) -> str:
    from pdfunlocker.profiles.registry import field_id_for_key

    field_key = str(item["field_key"])
    existing = item.get("field_id")

    if existing:
        return str(existing)

    return field_id_for_key(
        field_key,
        int(item["field_number"]),
        is_custom=bool(item.get("is_custom")),
    )


def command_show(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles import store
    from pdfunlocker.profiles.manager import display_label

    result = _load_profile(args.profile_id)

    if result is None:
        print(f"Profile not found: {args.profile_id}")
        return

    record, values = result

    print()
    print("PDF Unlocker Profile")
    print("====================")
    print(f"ID   : {values.get('PROFILE_ID', record['profile_id'])}")
    print(f"Name : {values.get('PROFILE_NAME', record['name'])}")
    print()
    print("Stored values are masked by default.")
    print()

    fields = store.list_fields(include_archived=True)
    known_keys: set[str] = set()
    displayed_keys: set[str] = set()
    current_category = None

    for item in fields:
        key = str(item["field_key"])
        known_keys.add(key)
        category = str(item.get("category") or "Other")
        field_id = _public_field_id(item)
        entries: list[tuple[str, str]] = []

        if key in values:
            entries.append((key, values[key]))

        if item.get("allows_multiple"):
            prefix = key + "_"
            for value_key, value in values.items():
                suffix = value_key[len(prefix):] if value_key.startswith(prefix) else ""
                if suffix.isdigit():
                    entries.append((value_key, value))

        if not entries:
            continue

        if category != current_category:
            print(f"--- {category} ---")
            current_category = category

        entries.sort(key=lambda pair: (
            0 if pair[0] == key else 1,
            int(pair[0].rsplit("_", 1)[1]) if pair[0] != key else 0,
        ))

        for value_key, value in entries:
            displayed_keys.add(value_key)
            display_id = field_id
            if value_key != key:
                sequence = int(value_key.rsplit("_", 1)[1])
                display_id = store.value_code(int(item["field_number"]), sequence, True)
            label = display_label(key)
            shown = _display_value(value_key, value)
            print(f"{display_id} {label}: {shown}")

    # Retain visibility of any legacy/orphaned values rather than silently hiding them.
    remaining = [
        (key, value)
        for key, value in values.items()
        if key not in {"PROFILE_ID", "PROFILE_NAME"}
        and key not in displayed_keys
        and not any(
            key.startswith(field_key + "_")
            and key[len(field_key) + 1:].isdigit()
            and field_key in known_keys
            for field_key in known_keys
        )
    ]

    if remaining:
        print("--- Legacy or unregistered values ---")
        for key, value in remaining:
            print(f"{key}: {_display_value(key, value)}")

    print()


def command_modify(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles import manager

    result = _load_profile(args.profile_id)

    if result is None:
        print(f"Profile not found: {args.profile_id}")
        return

    record, values = result
    try:
        path = _safe_export_path(record, args.profile_id)
    except RuntimeError as exc:
        print(exc)
        return

    current_name = values.get("PROFILE_NAME", record["name"])
    print()
    print(f"Modify Profile {args.profile_id}")
    print("==============================")
    print(f"Current name: {current_name}")

    new_name = _normalize_name(input("New profile name [Enter=keep]: "))

    if new_name:
        if not manager.valid_profile_name(new_name):
            print("Invalid profile name.")
            return

        duplicate = any(
            _normalize_name(item["name"]).casefold() == new_name.casefold()
            and int(item["profile_id"]) != args.profile_id
            for item in manager_profile_records()
        )

        if duplicate:
            print(f"Profile name already exists: {new_name}")
            return

        values["PROFILE_NAME"] = new_name

    manager.collect_profile_values(
        values,
        modifying=True,
        input_func=input,
        include_custom_fields=True,
    )

    manager.save_env(path, values)

    print()
    print("Profile updated successfully.")
    print()


def manager_profile_records() -> list[dict]:
    from pdfunlocker.profiles import store
    return store.list_profiles()


def command_remove(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles import store

    result = _load_profile(args.profile_id)

    if result is None:
        print(f"Profile not found: {args.profile_id}")
        return

    record, values = result

    print()
    print(f"Profile ID   : {args.profile_id}")
    print(f"Profile name : {values.get('PROFILE_NAME', record['name'])}")
    print()
    print("This permanently removes this profile and its stored values.")
    answer = input("Type REMOVE to confirm: ").strip()

    if answer != "REMOVE":
        print("Profile removal cancelled. No data was changed.")
        return

    try:
        path = _safe_export_path(record, args.profile_id)
    except RuntimeError as exc:
        print(exc)
        print("Database removal was not performed.")
        return

    store.delete_profile(args.profile_id)

    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"Profile removed from SQLite, but export cleanup failed: {exc}")
        print(f"Retained export: {path}")
        return

    print("Profile removed.")
    print("Its ID will not be reused.")
    print()


def command_validate(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles import store
    from pdfunlocker.profiles.manager import valid_profile_name
    from pdfunlocker.profiles.validation import validate_profile_values

    result = _load_profile(args.profile_id)

    if result is None:
        print(f"Profile not found: {args.profile_id}")
        return

    record, values = result
    errors: list[str] = []

    profile_id = values.get("PROFILE_ID", "")
    if not profile_id.isdigit() or int(profile_id) != args.profile_id:
        errors.append("PROFILE_ID is invalid.")

    name = values.get("PROFILE_NAME", "")
    if not name:
        errors.append("PROFILE_NAME is missing.")
    elif not valid_profile_name(name):
        errors.append("PROFILE_NAME is invalid.")

    errors.extend(validate_profile_values(values))

    print()
    print(f"Validate Profile {args.profile_id}")
    print(f"Name: {name or record['name']}")
    print()

    if errors:
        print("INVALID")
        for error in errors:
            print(f"- {error}")
        print(f"\nTotal errors: {len(errors)}")
        raise ValueError("Profile validation failed.")
    else:
        print("VALID")
        print("All stored profile values pass the current validation rules.")

    print()




def command_audit(args: argparse.Namespace) -> None:
    """Report completeness and validation issues without displaying values."""
    from pdfunlocker.profiles import store
    from pdfunlocker.profiles.manager import valid_profile_name
    from pdfunlocker.profiles.validation import validate_profile_values

    result = _load_profile(args.profile_id)
    if result is None:
        raise ValueError(f"Profile not found: {args.profile_id}")

    record, values = result
    missing = []
    empty = []

    profile_bank_groups = {int(bank["group_code"]) for bank in store.list_profile_banks(args.profile_id)}
    import re
    audit_fields = []
    for item in store.list_fields():
        bank_match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})[A-F]", str(item["field_key"]))
        if bank_match and int(bank_match.group(1)) not in profile_bank_groups:
            continue
        audit_fields.append(item)
    seen_audit_ids: set[str] = set()
    for item in audit_fields:
        key = str(item["field_key"])
        label = str(item.get("label") or key)
        field_id = _public_field_id(item)
        if field_id in seen_audit_ids and not key.startswith("BANK_"):
            continue
        seen_audit_ids.add(field_id)
        present = []

        if key in values:
            present.append(key)

        if item.get("allows_multiple"):
            prefix = key + "_"
            present.extend(
                value_key for value_key in values
                if value_key.startswith(prefix)
                and value_key[len(prefix):].isdigit()
            )

        if not present:
            missing.append(f"{field_id} {label}")
        elif all(not str(values[value_key]).strip() for value_key in present):
            empty.append(f"{field_id} {label}")

    invalid = []
    profile_id = values.get("PROFILE_ID", "")
    if not profile_id.isdigit() or int(profile_id) != args.profile_id:
        invalid.append("PROFILE_ID is invalid.")

    name = values.get("PROFILE_NAME", "")
    if not name:
        invalid.append("PROFILE_NAME is missing.")
    elif not valid_profile_name(name):
        invalid.append("PROFILE_NAME is invalid.")

    invalid.extend(validate_profile_values(values))

    print()
    print(f"Profile audit: {args.profile_id}")
    print(f"Name: {name or record['name']}")
    print("Stored values are not displayed.")
    print(f"Missing fields: {len(missing)}")
    for item in missing:
        print(f"- {item}")
    print(f"Empty fields: {len(empty)}")
    for item in empty:
        print(f"- {item}")
    print(f"Validation errors: {len(invalid)}")
    for item in invalid:
        print(f"- {item}")

    if missing or empty or invalid:
        raise ValueError("Profile audit found issues.")

    print("AUDIT PASSED")
    print()


def command_check(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles import store

    result = _load_profile(args.profile_id)

    if result is None:
        print(f"Profile not found: {args.profile_id}")
        return

    record, values = result
    missing: list[str] = []
    empty: list[str] = []

    for item in store.list_fields():
        key = str(item["field_key"])
        label = str(item.get("label") or key)
        field_id = _public_field_id(item)

        present = []
        if key in values:
            present.append(key)

        if item.get("allows_multiple"):
            prefix = key + "_"
            present.extend(
                value_key for value_key in values
                if value_key.startswith(prefix)
                and value_key[len(prefix):].isdigit()
            )

        if not present:
            missing.append(f"{field_id} {label}")
        elif all(not values[value_key].strip() for value_key in present):
            empty.append(f"{field_id} {label}")

    print()
    print(f"Profile check: {args.profile_id}")
    print(f"Name: {values.get('PROFILE_NAME', record['name'])}")
    print("Stored values are not displayed.")
    print()

    print(f"Missing fields: {len(missing)}")
    for field in missing:
        print(f"- {field}")

    print(f"\nEmpty fields: {len(empty)}")
    for field in empty:
        print(f"- {field}")

    print()


def _public_field_key(item: dict) -> str:
    from pdfunlocker.profiles.registry import BANK_SUFFIXES
    import re
    match = re.fullmatch(r"BANK_1[2-6][0-9]{2}([A-F])", str(item.get("field_key", "")))
    return BANK_SUFFIXES[match.group(1)][0] if match else str(item["field_key"])


def _print_registry(include_archived: bool = True) -> None:
    from pdfunlocker.profiles import store

    fields = store.list_fields(include_archived=include_archived)
    fields.sort(key=lambda item: (bool(item.get("archived")), str(item.get("field_id") or ""), int(item.get("field_number", 0))))

    print()
    print("Profile Field Registry")
    print("======================")

    if not fields:
        print("No registered fields.")
        print()
        return

    categories = (
        "Personal", "Private", "Banking", "Business",
        "Employment", "Insurance", "Education",
    )

    for category in categories:
        grouped = [
            item for item in fields
            if str(item.get("category") or "Custom") == category
        ]

        if not grouped:
            continue

        print(f"\n--- {category} ---")
        seen: set[str] = set()
        for item in grouped:
            field_id = _public_field_id(item)
            if field_id in seen:
                continue
            seen.add(field_id)
            mode = "multiple" if item.get("allows_multiple") else "single"
            state = "archived" if item.get("archived") else "active"
            print(
                f"{field_id:<8} {_public_field_key(item):<30} "
                f"{item['label']} [{mode}; {state}]"
            )

    legacy = [item for item in fields if str(item.get("category") or "Custom") == "Custom"]
    if legacy:
        print("\n--- Legacy uncategorized fields (compatibility only) ---")
        seen: set[str] = set()
        for item in legacy:
            field_id = _public_field_id(item)
            if field_id in seen:
                continue
            seen.add(field_id)
            print(f"{field_id:<8} {_public_field_key(item):<30} {item['label']} [legacy; category required]")

    print()


def command_fields(_: argparse.Namespace) -> None:
    _print_registry(include_archived=True)


def command_field_add(_: argparse.Namespace) -> None:
    from pdfunlocker.profiles import manager

    manager.add_profile_field(raise_errors=True)
    print()
    print("Current field registry:")
    _print_registry(include_archived=True)


def command_field_list(_: argparse.Namespace) -> None:
    _print_registry(include_archived=True)




def _find_field(field_id: str) -> dict:
    from pdfunlocker.profiles import store

    fields = store.list_fields(include_archived=True)
    fields.sort(key=lambda item: (bool(item.get("archived")), int(item.get("field_number", 0))))
    for item in fields:
        if _public_field_id(item).casefold() == field_id.casefold():
            return item

    raise ValueError(f"Field ID not found: {field_id}")


def command_field_show(args: argparse.Namespace) -> None:
    item = _find_field(args.field_id)
    print()
    print(f"Field ID : {_public_field_id(item)}")
    print(f"Key      : {_public_field_key(item)}")
    print(f"Label    : {item['label']}")
    print(f"Category : {item.get('category') or 'Legacy (uncategorized)'}")
    print(f"Multiple : {'yes' if item.get('allows_multiple') else 'no'}")
    print(f"Status   : {'archived' if item.get('archived') else 'active'}")
    print(f"Built-in : {'yes' if item.get('is_builtin') else 'no'}")
    print()


def command_field_modify(args: argparse.Namespace) -> None:
    """Modify a custom field label without changing its permanent category/ID."""
    from pdfunlocker.profiles import store

    item = _find_field(args.field_id)
    if item.get("is_builtin") or item.get("archived"):
        raise ValueError("Built-in or archived field definitions cannot be modified.")

    label = input(f"New label [{item['label']}]: ").strip()
    if not label:
        print("No changes requested.")
        return

    store.update_field_label(str(item["field_key"]), label)
    print("Field label updated. Its category and permanent ID remain unchanged.")


def command_field_archive(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles import manager

    item = _find_field(args.field_id)
    manager.archive_profile_field(str(item["field_key"]))


def command_profile_backup(args: argparse.Namespace) -> None:
    from getpass import getpass
    from pdfunlocker.profiles.backup import create_backup

    first = getpass("New profile-backup passphrase (minimum 12 characters): ")
    second = getpass("Confirm passphrase: ")
    if first != second:
        raise ValueError("Passphrases do not match. No backup was created.")
    path = create_backup(first, args.output)
    print(f"Encrypted profile backup created: {path}")
    print("Keep the passphrase separately; it cannot be recovered from the backup.")


def command_profile_backups(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.backup import list_backups

    items = list_backups(args.directory)
    print("Profile backups")
    print("===============")
    if not items:
        print("No .pupb backups found.")
        return
    for item in items:
        size = item["size"]
        if size >= 1024 * 1024:
            shown = f"{size / (1024 * 1024):.2f} MiB"
        elif size >= 1024:
            shown = f"{size / 1024:.1f} KiB"
        else:
            shown = f"{size} B"
        print(f"{item['modified']}  {shown:>10}  {item['path']}")
    print(f"Total: {len(items)}")


def command_profile_restore(args: argparse.Namespace) -> None:
    from getpass import getpass
    from pdfunlocker.profiles.backup import restore_backup

    print("WARNING: close every other PDF Unlocker process before restoring.")
    print("Restore replaces the profile database and card-encryption key.")
    if input("Type RESTORE to continue: ").strip() != "RESTORE":
        print("Restore cancelled. No data was changed.")
        return
    passphrase = getpass("Backup passphrase: ")
    safety_path, manifest = restore_backup(args.backup_file, passphrase)
    print("Profile restore completed and validated.")
    print(f"Profiles restored: {manifest['profile_count']}")
    print(f"Safety backup: {safety_path}")
    print("Profile exports are non-authoritative and can be regenerated from SQLite when profiles are loaded.")


def command_profile_verify(args: argparse.Namespace) -> None:
    from getpass import getpass
    from pdfunlocker.profiles.backup import verify_backup

    passphrase = getpass("Profile-backup passphrase: ")
    result = verify_backup(args.backup_file, passphrase)
    print("Profile backup verified successfully.")
    print(f"Backup: {result['backup_path']}")
    print(f"Created: {result['created_at']}")
    print(f"Schema version: {result['schema_version']}")
    print(f"Profiles: {result['profile_count']}")
    print(f"Stored values: {result['value_count']}")
    print(f"Encrypted card values: {result['encrypted_card_count']}")
    print(f"Includes card-encryption key: {'yes' if result['includes_card_key'] else 'no'}")
    print("Active profile database and encryption keys were not modified.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfunlocker profile",
        description="Manage multiple PDF Unlocker profiles.",
    )

    commands = parser.add_subparsers(dest="profile_command", required=True)

    add = commands.add_parser("add", help="create a profile")
    add.set_defaults(func=command_add)

    listing = commands.add_parser("list", help="list all profiles")
    listing.set_defaults(func=command_list)

    show = commands.add_parser("show", help="show all stored profile values")
    show.add_argument("profile_id", type=int, metavar="ID")
    show.set_defaults(func=command_show)

    modify = commands.add_parser("modify", help="modify a profile")
    modify.add_argument("profile_id", type=int, metavar="ID")
    modify.set_defaults(func=command_modify)

    remove = commands.add_parser("remove", help="remove a profile")
    remove.add_argument("profile_id", type=int, metavar="ID")
    remove.set_defaults(func=command_remove)

    validate = commands.add_parser("validate", help="validate a profile")
    validate.add_argument("profile_id", type=int, metavar="ID")
    validate.set_defaults(func=command_validate)

    audit = commands.add_parser("audit", help="audit completeness and validation")
    audit.add_argument("profile_id", type=int, metavar="ID")
    audit.set_defaults(func=command_audit)

    check = commands.add_parser("check", help="check missing and empty fields")
    check.add_argument("profile_id", type=int, metavar="ID")
    check.set_defaults(func=command_check)

    fields = commands.add_parser("fields", help="list registered profile fields")
    fields.set_defaults(func=command_fields)

    field = commands.add_parser("field", help="manage custom profile fields")
    field_commands = field.add_subparsers(
        dest="field_command",
        required=True,
    )

    field_add = field_commands.add_parser("add", help="add a custom field")
    field_add.set_defaults(func=command_field_add)

    field_list = field_commands.add_parser("list", help="list field IDs")
    field_list.set_defaults(func=command_field_list)

    field_show = field_commands.add_parser("show", help="show field metadata")
    field_show.add_argument("field_id", metavar="FIELD_ID")
    field_show.set_defaults(func=command_field_show)

    field_modify = field_commands.add_parser("modify", help="modify field metadata")
    field_modify.add_argument("field_id", metavar="FIELD_ID")
    field_modify.set_defaults(func=command_field_modify)

    field_archive = field_commands.add_parser(
        "archive",
        help="archive a custom field without deleting stored values",
    )
    field_archive.add_argument("field_id", metavar="FIELD_ID")
    field_archive.set_defaults(func=command_field_archive)

    profile_backup = commands.add_parser("backup", help="create an encrypted profile backup")
    profile_backup.add_argument("--output", type=Path, help="destination .pupb file (default: private application backup directory)")
    profile_backup.set_defaults(func=command_profile_backup)

    profile_backups = commands.add_parser("backups", help="list encrypted profile backups")
    profile_backups.add_argument("--directory", type=Path, help="directory to list (default: private application backup directory)")
    profile_backups.set_defaults(func=command_profile_backups)

    profile_restore = commands.add_parser("restore", help="restore an encrypted profile backup")
    profile_restore.add_argument("backup_file", type=Path, metavar="BACKUP_FILE")
    profile_restore.set_defaults(func=command_profile_restore)

    profile_verify = commands.add_parser("verify", help="verify an encrypted profile backup without restoring it")
    profile_verify.add_argument("backup_file", type=Path, metavar="BACKUP_FILE")
    profile_verify.set_defaults(func=command_profile_verify)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        with profile_storage_context():
            args.func(args)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Profile operation failed: {exc}\n")
