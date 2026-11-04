#!/usr/bin/env python3
"""Apply the permanent field registry and optionally replace the Personal profile.

The PDF-processing database is deliberately never opened by this script.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT / "src"))
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from pdfunlocker.cli import installer
from pdfunlocker.cli.personal_cli import (
    _load_config,
    _personal_profile_context,
    _personal_rules_context,
)
from pdfunlocker.profiles.registry import FIELD_ID_BY_KEY, BANK_FIRST
from pdfunlocker.profiles.card_crypto import (
    decrypt_card_number, is_card_field_key, is_encrypted_card,
)
from pdfunlocker.profiles.validation import validate_profile_values


def backup_active_data(config: dict, config_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = Path("/storage/emulated/0/Download")
    if not root.is_dir():
        root = Path.home() / "PDFUnlocker-Backups"
    backup = root / f"PDFUnlocker-PreFieldRegistry-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)

    database_dir = Path(config["database_directory"]).expanduser()
    profile_db = database_dir / "profiles.sqlite3"
    if not profile_db.is_file():
        raise RuntimeError(f"Active profile database not found: {profile_db}")

    src = sqlite3.connect(f"file:{profile_db}?mode=ro", uri=True)
    dst = sqlite3.connect(backup / "profiles.sqlite3")
    try:
        src.backup(dst)
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Profile database backup failed integrity check: {integrity}")
    finally:
        dst.close()
        src.close()

    profiles_dir = Path(config["profiles_directory"]).expanduser()
    if profiles_dir.is_dir():
        shutil.copytree(profiles_dir, backup / "profiles", dirs_exist_ok=True)
    shutil.copy2(config_path, backup / "config.json")

    from pdfunlocker.profiles.card_crypto import KEY_PATH, _load_or_create_key
    _load_or_create_key()
    if KEY_PATH.is_file():
        (backup / "keys").mkdir(parents=True, exist_ok=True)
        shutil.copy2(KEY_PATH, backup / "keys" / "card-number.key")
        try:
            (backup / "keys").chmod(0o700)
            (backup / "keys" / "card-number.key").chmod(0o600)
        except OSError:
            pass

    rules_dir = Path(config["rules_directory"]).expanduser()
    if rules_dir.is_dir():
        shutil.copytree(rules_dir, backup / "rules", dirs_exist_ok=True)

    return backup


def migrate_rules(rules_dir: Path) -> int:
    from tools.migrate_field_ids import migrate_rules as migrate
    changed = migrate(rules_dir)
    return len(changed)


def verify_registry(store) -> None:
    fields = store.list_fields(include_archived=True)
    by_key = {item["field_key"]: item for item in fields}
    for key, expected in FIELD_ID_BY_KEY.items():
        if key not in by_key or by_key[key].get("field_id") != expected:
            raise RuntimeError(
                f"Registry verification failed for {key}: expected {expected}, "
                f"found {by_key.get(key, {}).get('field_id')}"
            )
    for suffix in "ABCDEF":
        expected = f"{BANK_FIRST}{suffix}"
        if not any(item.get("field_id") == expected for item in fields):
            raise RuntimeError(f"Missing bank field ID {expected}")


def replace_profile(config_path: Path, config: dict, manager, store, old_profile_id: int) -> int:
    answer = input(
        f"\nCreate a new profile and then delete old profile {old_profile_id}? "
        "Type REPLACE to continue: "
    ).strip()
    if answer != "REPLACE":
        print("Profile replacement skipped. Existing profile was preserved.")
        return old_profile_id

    default_name = "Rupesh"
    name = input(f"New profile name [{default_name}]: ").strip() or default_name
    if not manager.valid_profile_name(name):
        raise RuntimeError("Invalid profile name. Use 1-50 letters, digits, spaces, _, -, or .")

    new_profile_id = manager.next_profile_id()
    values = {
        "PROFILE_ID": str(new_profile_id),
        "PROFILE_NAME": name,
    }
    print("\nCollecting the new profile. Press Enter to skip optional fields.")
    manager.collect_profile_values(values, modifying=False, input_func=input)

    new_path = manager.profile_path(new_profile_id)
    manager.save_env(new_path, values)
    saved = store.load_profile(new_profile_id)
    if not saved or saved.get("PROFILE_NAME") != name:
        raise RuntimeError("New profile could not be verified; old profile was kept.")

    # Verify exact key coverage and every persisted value before deleting anything.
    expected_keys = set(values)
    saved_keys = set(saved)
    if expected_keys != saved_keys:
        missing = sorted(expected_keys - saved_keys)
        unexpected = sorted(saved_keys - expected_keys)
        raise RuntimeError(
            f"Profile verification failed (missing={missing}, unexpected={unexpected}); "
            "old profile was kept."
        )
    for key, expected_value in values.items():
        actual_value = saved[key]
        if is_card_field_key(key):
            if not is_encrypted_card(actual_value):
                raise RuntimeError(f"Card field {key} is not encrypted; old profile was kept.")
            if decrypt_card_number(actual_value) != expected_value:
                raise RuntimeError(f"Card field {key} failed decrypt/compare verification; old profile was kept.")
        elif actual_value != expected_value:
            raise RuntimeError(f"Field {key} failed exact save verification; old profile was kept.")

    validation_errors = validate_profile_values(saved)
    if validation_errors:
        raise RuntimeError(
            "New profile failed stored-value validation; old profile was kept: "
            + "; ".join(validation_errors)
        )

    export_path = manager.profile_path(new_profile_id)
    exported = manager._load_env_file(export_path)
    if exported != saved:
        raise RuntimeError("Profile export does not match the database; old profile was kept.")
    for key, exported_value in exported.items():
        if is_card_field_key(key) and exported_value and not is_encrypted_card(exported_value):
            raise RuntimeError(f"Profile export exposes unencrypted card data in {key}; old profile was kept.")

    # Verify SQLite referential integrity and every repeatable value counter.
    with store._connect() as db:
        foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError("Profile database foreign-key check failed; old profile was kept.")
        for field_key in saved:
            match = re.fullmatch(r"(.+)_([0-9]+)", field_key)
            if not match:
                continue
            base, sequence_text = match.groups()
            sequence = int(sequence_text)
            field_row = db.execute(
                "SELECT field_number,allows_multiple FROM field_definitions WHERE field_key=?",
                (base,),
            ).fetchone()
            if not field_row or not field_row["allows_multiple"]:
                continue
            counter = db.execute(
                "SELECT next_sequence FROM value_counters WHERE profile_id=? AND field_number=?",
                (new_profile_id, int(field_row["field_number"])),
            ).fetchone()
            if not counter or int(counter["next_sequence"]) <= sequence:
                raise RuntimeError(
                    f"Repeatable sequence counter is invalid for {field_key}; old profile was kept."
                )

    # Delete old data only after the new profile has been saved and verified.
    store.delete_profile(old_profile_id)
    remaining_ids = {int(item["profile_id"]) for item in store.list_profiles()}
    if old_profile_id in remaining_ids:
        raise RuntimeError(
            "New profile was saved, but the old profile could not be deleted. "
            "The configured profile was not changed."
        )
    old_path = manager.profile_path(old_profile_id)
    try:
        old_path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"Warning: old profile export could not be removed: {exc}")

    config["profile_id"] = new_profile_id
    installer._atomic_json_write(config_path, config)
    print(f"\nNew profile saved: ID {new_profile_id} | {name}")
    print(f"Old profile {old_profile_id} deleted after new profile verification.")
    return new_profile_id


def main() -> int:
    config_path = installer.find_installation_config()
    if config_path is None:
        raise RuntimeError("Personal installation config was not found.")
    config = _load_config(config_path)
    old_profile_id = int(config.get("profile_id", 0))
    if old_profile_id < 1:
        raise RuntimeError("Configured profile ID is invalid.")

    backup = backup_active_data(config, config_path)
    print(f"Safety backup created: {backup}")

    with _personal_profile_context(config) as (manager, store, active_id, _profile_path):
        store.initialize()
        store.ensure_bank_group(BANK_FIRST)
        verify_registry(store)
        print("Permanent field registry verified.")

        with _personal_rules_context(config) as rules_manager:
            rules_dir = Path(config["rules_directory"]).expanduser().resolve()
            changed = migrate_rules(rules_dir)
            loaded = rules_manager.load_rules()
            if not loaded:
                raise RuntimeError("No password rules were loaded after migration.")
            print(f"Password rules migrated: {changed}; validated: {len(loaded)}")

        replace_profile(config_path, config, manager, store, active_id)

    print("\nFIELD REGISTRY IMPLEMENTATION COMPLETE")
    print("The PDF-processing database was not opened or modified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled. Any old profile not yet deleted remains intact.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
