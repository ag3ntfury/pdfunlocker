#!/usr/bin/env python3
"""Back up the active Personal installation, then encrypt any stored full cards.

This tool never opens the PDF-processing database and never replaces/deletes a
profile. It is safe to run after the permanent field registry migration.
"""
from __future__ import annotations

import json
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
from pdfunlocker.cli.personal_cli import _load_config, _personal_profile_context
from pdfunlocker.paths import APP_DIR
from pdfunlocker.profiles.card_crypto import (
    KEY_PATH, _load_or_create_key, is_card_field_key, is_encrypted_card,
)
from pdfunlocker.profiles.validation import validate_profile_values


def _backup_database(source: Path, destination: Path) -> dict:
    if not source.is_file():
        raise RuntimeError(f"Active profile database not found: {source}")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Backup integrity check failed: {integrity}")
        tables = [row[0] for row in dst.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        counts = {
            table: dst.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
        return {"integrity": integrity, "tables": counts}
    finally:
        dst.close()
        src.close()


def main() -> int:
    config_path = installer.find_installation_config()
    if config_path is None:
        raise RuntimeError("Personal installation config was not found.")
    config = _load_config(config_path)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    download = Path("/storage/emulated/0/Download")
    backup_root = download if download.is_dir() else Path.home() / "PDFUnlocker-Backups"
    backup = backup_root / f"PDFUnlocker-Registry-Fix-Backup-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    try:
        backup.chmod(0o700)
    except OSError:
        pass

    database_dir = Path(config["database_directory"]).expanduser()
    profile_db = database_dir / "profiles.sqlite3"
    report = _backup_database(profile_db, backup / "profiles.sqlite3")
    try:
        (backup / "profiles.sqlite3").chmod(0o600)
    except OSError:
        pass

    profiles_dir = Path(config["profiles_directory"]).expanduser()
    if profiles_dir.is_dir():
        shutil.copytree(profiles_dir, backup / "profiles", dirs_exist_ok=True)
    rules_dir = Path(config["rules_directory"]).expanduser()
    if rules_dir.is_dir():
        shutil.copytree(rules_dir, backup / "rules", dirs_exist_ok=True)
    shutil.copy2(config_path, backup / "config.json")
    try:
        (backup / "config.json").chmod(0o600)
    except OSError:
        pass

    # Create the key before backup and include it so the encrypted card values
    # remain recoverable. A second private copy is also maintained under APP_DIR.
    _load_or_create_key()
    key_backup = backup / "keys" / "card-number.key"
    key_backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(KEY_PATH, key_backup)
    try:
        key_backup.parent.chmod(0o700)
        key_backup.chmod(0o600)
    except OSError:
        pass

    manifest = {
        "created_at": datetime.now().isoformat(),
        "active_profile_id": int(config.get("profile_id", 0)),
        "profile_database": str(profile_db),
        "profile_database_backup": str(backup / "profiles.sqlite3"),
        "database_integrity": report["integrity"],
        "table_counts": report["tables"],
        "card_key_backup": str(key_backup),
        "pdf_processing_database_touched": False,
    }
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    try:
        (backup / "manifest.json").chmod(0o600)
    except OSError:
        pass

    print(f"Safety backup created: {backup}")
    print(f"Profile database backup integrity: {report['integrity']}")

    with _personal_profile_context(config) as (manager, store, active_id, _profile_path):
        store.initialize()
        profile_records = store.list_profiles()
        active_id = int(active_id)
        if active_id not in {int(record["profile_id"]) for record in profile_records}:
            raise RuntimeError(f"Configured active profile {active_id} is missing.")
        for record in profile_records:
            profile_id = int(record["profile_id"])
            result = manager.get_profile(profile_id)
            if result is None:
                raise RuntimeError(f"Unable to reload profile {profile_id} after card migration.")
            _path, values = result
            errors = validate_profile_values(values)
            if errors:
                print(f"PROFILE {profile_id}: {len(errors)} validation issue(s) remain; values were not changed.")
                for error in errors:
                    print(f"  - {error}")
            else:
                print(f"PROFILE {profile_id}: stored values pass validation.")

        fields = store.list_fields(include_archived=True)
        expected = {
            "TITLE": "0100", "FIRST_NAME": "0200", "LAST_NAME": "0300",
            "MIDDLE_NAME": "0400", "MOTHER_NAME": "0500", "DOB": "0600",
            "MOBILE": "0700", "EMAIL": "0800", "PINCODE": "0900",
            "PAN": "1000", "AADHAAR": "1100", "INCORPORATION_DATE": "1700",
            "TAN": "1800", "GSTIN": "1900", "EMPLOYEE_ID": "2000",
            "UAN": "2100", "PPO_NUMBER": "2200", "PRAN": "2300",
            "POLICY_NUMBER": "2400",
        }
        by_key = {item["field_key"]: item for item in fields}
        for key, field_id in expected.items():
            if key not in by_key or by_key[key].get("field_id") != field_id:
                raise RuntimeError(f"Registry verification failed for {key} ({field_id}).")
        for suffix in "ABCDEF":
            expected_id = f"1200{suffix}"
            if not any(item.get("field_id") == expected_id for item in fields):
                raise RuntimeError(f"Bank field registry is missing {expected_id}.")

        with sqlite3.connect(profile_db) as db:
            db.execute("PRAGMA foreign_keys=ON")
            fk_errors = db.execute("PRAGMA foreign_key_check").fetchall()
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            card_rows = db.execute(
                "SELECT field_key,value FROM profile_values"
            ).fetchall()
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"Profile database integrity failure: {integrity}; foreign keys: {fk_errors}")
        unencrypted = [
            key for key, value in card_rows
            if is_card_field_key(key) and value and not is_encrypted_card(value)
            and not (len(value) >= 12 and value.startswith("X") and value[-4:].isdigit())
        ]
        if unencrypted:
            raise RuntimeError(f"Unencrypted full card values remain in fields: {unencrypted}")

    print("Permanent field IDs verified.")
    print("Existing full card values are encrypted in SQLite and profile exports.")
    print(f"Private key: {KEY_PATH}")
    print(f"Key recovery copy: {APP_DIR / 'backups' / 'keys' / 'card-number.key'}")
    print("PDF-processing database was not opened or modified.")
    print("No profile was created, replaced, or deleted.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cancelled. The safety backup remains available.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
