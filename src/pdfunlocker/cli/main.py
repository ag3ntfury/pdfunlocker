from __future__ import annotations

import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pdfunlocker.paths import (
    APP_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    DATABASE_DIR,
    LOGS_DIR,
    PROFILES_DIR,
    RULES_DIR,
)

try:
    VERSION = version("pdfunlocker")
except PackageNotFoundError:
    VERSION = "0.1.0a1"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}

    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )


def ask_directory(prompt: str, default: Path | None = None) -> Path:
    while True:
        if default is not None:
            value = input(f"{prompt} [{default}]: ").strip()
        else:
            value = input(f"{prompt}: ").strip()

        if not value and default is not None:
            path = default.expanduser().resolve()
        elif value:
            path = Path(value).expanduser().resolve()
        else:
            print("Please enter a directory.")
            continue

        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError as exc:
            print(f"Cannot create/access directory: {exc}")


def command_install(_args: argparse.Namespace) -> None:
    print()
    print("========================================")
    print("          PDF Unlocker Setup")
    print("========================================")
    print()

    existing = load_config()

    if existing:
        print("Existing PDF Unlocker configuration found.")
        print()
        answer = input("Reconfigure directories? [y/N]: ").strip().lower()

        if answer not in {"y", "yes"}:
            print("Installation unchanged.")
            return

        print()

    shared_storage = Path.home() / "storage" / "shared"
    if shared_storage.is_dir():
        pdf_root = shared_storage / "PDF"
    else:
        pdf_root = Path.home() / "PDFUnlocker"

    default_inbox = pdf_root / "inbox"
    default_output = pdf_root / "output"

    inbox_dir = ask_directory(
        "Inbox directory",
        default_inbox,
    )

    output_dir = ask_directory(
        "Output directory",
        default_output,
    )

    original_dir = output_dir / "original"
    unlocked_dir = output_dir / "unlocked"
    locked_dir = output_dir / "locked"
    corrupted_dir = output_dir / "corrupted"

    for directory in (
        original_dir,
        unlocked_dir,
        locked_dir,
        corrupted_dir,
        DATABASE_DIR,
        PROFILES_DIR,
        RULES_DIR,
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    config = {
        "version": VERSION,
        "app_directory": str(APP_DIR),
        "inbox_directory": str(inbox_dir),
        "output_directory": str(output_dir),
        "original_directory": str(original_dir),
        "unlocked_directory": str(unlocked_dir),
        "locked_directory": str(locked_dir),
        "corrupted_directory": str(corrupted_dir),
        "database_directory": str(DATABASE_DIR),
        "profiles_directory": str(PROFILES_DIR),
        "rules_directory": str(RULES_DIR),
        "logs_directory": str(LOGS_DIR),
    }

    save_config(config)

    print()
    print("========================================")
    print("          Setup Complete")
    print("========================================")
    print()
    print(f"App        : {APP_DIR}")
    print(f"Inbox      : {inbox_dir}")
    print(f"Original   : {original_dir}")
    print(f"Unlocked   : {unlocked_dir}")
    print(f"Locked     : {locked_dir}")
    print(f"Corrupted  : {corrupted_dir}")
    print(f"Profiles   : {PROFILES_DIR}")
    print(f"Rules      : {RULES_DIR}")
    print(f"Database   : {DATABASE_DIR}")
    print()
    print(f"Configuration: {CONFIG_FILE}")
    print()


def command_status(_args: argparse.Namespace) -> None:
    config = load_config()

    if not config:
        print("PDF Unlocker is not initialized.")
        print("Run: pdfunlocker install")
        return

    print()
    print("PDF Unlocker Status")
    print("===================")
    print()

    for key, value in config.items():
        print(f"{key}: {value}")

    print()


def command_scan(_args: argparse.Namespace) -> None:
    from pdfunlocker.database.manager import initialize_database, list_pdfs
    from pdfunlocker.pdf.scanner import scan_directory

    config = load_config()

    if not config:
        print("PDF Unlocker is not initialized.")
        print("Run: pdfunlocker install")
        return

    inbox = Path(config["inbox_directory"])

    initialize_database()

    print("PDF scan")
    print("========")
    print()
    print(f"Inbox: {inbox}")
    print()

    try:
        result = scan_directory(inbox)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        print(f"Scan failed: {exc}")
        return

    print("Scan complete.")
    print()
    print(f"PDF files found : {result['total']}")
    print(f"New records     : {result['new']}")
    print(f"Duplicates      : {result['duplicate']}")
    print(f"Invalid/corrupt : {result['invalid']}")
    print()

    records = list_pdfs()

    if records:
        print("Database records")
        print("----------------")
        for record in records:
            print(
                f"ID={record['id']} | "
                f"{record['filename']} | "
                f"status={record['status']}"
            )
        print()


def command_unlock(args: argparse.Namespace) -> None:
    from pdfunlocker.pdf.unlocker import unlock_all

    config = load_config()

    if not config:
        print("PDF Unlocker is not initialized.")
        print("Run: pdfunlocker install")
        return

    unlock_all(
        original_directory=Path(config["original_directory"]),
        unlocked_directory=Path(config["unlocked_directory"]),
        dry_run=args.dry_run,
        retry_failed=args.retry_failed,
        pdf_id=args.pdf_id,
    )


def command_profile_add(_args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import add_profile

    add_profile()


def command_profile_list(_args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import list_profiles

    list_profiles()


def command_profile_show(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import show_profile

    show_profile(args.profile_id)


def command_profile_modify(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import modify_profile

    modify_profile(args.profile_id)


def command_profile_validate(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import validate_profile

    validate_profile(args.profile_id)




def command_profile_check(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import check_profile

    check_profile(args.profile_id)


def command_profile_fields(_args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import list_profile_fields

    list_profile_fields()


def command_profile_field_add(_args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import add_profile_field
    add_profile_field()


def command_profile_field_list(_args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import list_profile_registry
    list_profile_registry()


def command_profile_field_archive(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import archive_profile_field
    archive_profile_field(args.field_key)



def command_profile_rules(args: argparse.Namespace) -> None:
    from pdfunlocker.pdf.candidates import evaluate_rules_for_profile

    try:
        _profile, evaluations, _candidates = evaluate_rules_for_profile(
            args.profile_id,
            max_candidates_per_rule=1,
        )
    except (ValueError, OSError) as exc:
        print(f"Cannot evaluate profile rules: {exc}")
        return

    applicable = sum(item.applicable for item in evaluations)
    skipped = len(evaluations) - applicable

    print(f"Profile rule diagnostic: {args.profile_id}")
    print("Diagnostic only: no passwords attempted.")
    print("Stored profile values are not displayed.")
    print()
    print(f"Total rules: {len(evaluations)}")
    print(f"Applicable: {applicable}")
    print(f"Skipped: {skipped}")
    print()

    for item in evaluations:
        rule = item.rule
        status = "APPLICABLE" if item.applicable else "SKIPPED"
        print(f"[{status}] {rule.number} | {rule.rule_id} | {rule.name}")
        print(f"  Components: {', '.join(rule.components) or '(none)'}")
        print(f"  Result: {item.reason}")


def command_profile_remove(args: argparse.Namespace) -> None:
    from pdfunlocker.profiles.manager import remove_profile

    remove_profile(args.profile_id)


def command_rules_list(args: argparse.Namespace) -> None:
    from pdfunlocker.rules.manager import list_rules
    list_rules(
        category=args.category,
        priority=args.priority,
    )


def command_rules_show(args: argparse.Namespace) -> None:
    from pdfunlocker.rules.manager import show_rule
    show_rule(args.rule)


def command_rules_add(_args: argparse.Namespace) -> None:
    from pdfunlocker.rules.manager import add_rule
    add_rule()


def command_rules_modify(args: argparse.Namespace) -> None:
    from pdfunlocker.rules.manager import modify_rule
    modify_rule(args.rule)


def command_rules_remove(args: argparse.Namespace) -> None:
    from pdfunlocker.rules.manager import remove_rule
    remove_rule(args.rule)


def command_rules_archive(args: argparse.Namespace) -> None:
    from pdfunlocker.rules.manager import archive_rule
    archive_rule(args.rule)




def command_database_backup(args: argparse.Namespace) -> None:
    from pdfunlocker.database.maintenance import backup_database

    try:
        destination = backup_database(args.destination)
    except (OSError, ValueError) as exc:
        print(f"Database backup failed: {exc}")
        raise SystemExit(1) from exc

    print("Database backup created and verified:")
    print(destination)


def command_database_restore(args: argparse.Namespace) -> None:
    from pathlib import Path
    from pdfunlocker.database.maintenance import restore_database

    print("WARNING: This will replace the current PDF Unlocker database.")
    print(f"Backup to restore: {Path(args.source).expanduser().resolve()}")
    answer = input("Continue with restore? [y/N]: ").strip().lower()

    if answer not in {"y", "yes"}:
        print("Restore cancelled. Current database unchanged.")
        return

    try:
        restored, safety_backup = restore_database(args.source)
    except (OSError, ValueError) as exc:
        print(f"Database restore failed: {exc}")
        raise SystemExit(1) from exc

    print("Database restored and verified.")
    print(f"Restored database: {restored}")
    print(f"Pre-restore safety backup: {safety_backup}")


def command_database_status(_args: argparse.Namespace) -> None:
    import sqlite3
    from pdfunlocker.database.manager import database_path

    path = database_path()

    print("PDF Unlocker Database Status")
    print("============================")

    if not path.exists():
        print("Database: Not initialized")
        print("Run: pdfunlocker scan")
        return

    print(f"Database: {path}")
    print(f"File permissions: {oct(path.stat().st_mode & 0o777)}")
    print(f"Directory permissions: {oct(path.parent.stat().st_mode & 0o777)}")

    try:
        with sqlite3.connect(path, timeout=30) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
            journal = db.execute("PRAGMA journal_mode").fetchone()[0]

            print(f"Integrity: {integrity}")
            print(f"Foreign-key violations: {len(violations)}")
            print(f"Journal mode: {journal}")

            for table in ("pdf_files", "attempts"):
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()

                if exists:
                    count = db.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    print(f"{table}: {count}")
                else:
                    print(f"{table}: Missing")

    except sqlite3.Error as exc:
        print(f"Database inspection failed: {exc}")
        raise SystemExit(1) from exc



def command_database_backups(_args: argparse.Namespace) -> None:
    from pdfunlocker.database.maintenance import list_backups

    from datetime import datetime

    backups = list_backups()

    print("Verified PDF Unlocker Backups")
    print("=============================")

    if not backups:
        print("No verified backups found.")
        return

    for index, path in enumerate(backups, 1):
        stat = path.stat()
        modified = datetime.fromtimestamp(stat.st_mtime).astimezone()
        size_mb = stat.st_size / (1024 * 1024)

        print(
            f"{index:02d}. {path.name} | "
            f"{size_mb:.2f} MB | "
            f"{modified:%Y-%m-%d %H:%M:%S}"
        )

    print()
    print(f"Verified backups: {len(backups)}")
    print("Automatic retention: newest 30 verified backups")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfunlocker",
        description="CLI-first PDF password unlocking utility.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
    )

    install_parser = subparsers.add_parser(
        "install",
        help="initialize PDF Unlocker",
    )
    install_parser.set_defaults(func=command_install)

    status_parser = subparsers.add_parser(
        "status",
        help="show PDF Unlocker status",
    )
    status_parser.set_defaults(func=command_status)

    database_parser = subparsers.add_parser(
        "database",
        help="inspect, back up, or restore the database",
    )
    database_subparsers = database_parser.add_subparsers(
        dest="database_command",
        metavar="COMMAND",
    )

    database_backup = database_subparsers.add_parser(
        "backup",
        help="create and verify a database backup",
    )
    database_backup.add_argument(
        "destination",
        nargs="?",
        help="optional destination path for the backup",
    )
    database_backup.set_defaults(func=command_database_backup)

    database_restore = database_subparsers.add_parser(
        "restore",
        help="restore a database backup after confirmation",
    )
    database_restore.add_argument(
        "source",
        help="path to the verified backup database",
    )
    database_restore.set_defaults(func=command_database_restore)

    database_status = database_subparsers.add_parser(
        "status",
        help="show database integrity, permissions, and record counts",
    )
    database_status.set_defaults(func=command_database_status)

    database_backups = database_subparsers.add_parser(
        "backups",
        help="list verified database backups",
    )
    database_backups.set_defaults(func=command_database_backups)



    scan_parser = subparsers.add_parser(
        "scan",
        help="scan the configured inbox for PDFs",
    )
    scan_parser.set_defaults(func=command_scan)

    unlock_parser = subparsers.add_parser(
        "unlock",
        help="process eligible PDFs and try configured password combinations",
    )
    unlock_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview eligible PDFs without modifying files or the database",
    )
    unlock_parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="include PDFs previously marked failed",
    )
    unlock_parser.add_argument(
        "--id",
        dest="pdf_id",
        type=int,
        metavar="ID",
        help="process only the specified PDF database record",
    )
    unlock_parser.set_defaults(func=command_unlock)

    profile_parser = subparsers.add_parser(
        "profile",
        help="manage private password profiles",
    )
    profile_subparsers = profile_parser.add_subparsers(
        dest="profile_command",
        metavar="COMMAND",
    )

    profile_add = profile_subparsers.add_parser(
        "add",
        help="add a profile",
    )
    profile_add.set_defaults(func=command_profile_add)

    profile_list = profile_subparsers.add_parser(
        "list",
        help="list profiles",
    )
    profile_list.set_defaults(func=command_profile_list)

    profile_show = profile_subparsers.add_parser(
        "show",
        help="show a profile",
    )
    profile_show.add_argument("profile_id", type=int, help="profile ID")
    profile_show.set_defaults(func=command_profile_show)

    profile_modify = profile_subparsers.add_parser(
        "modify",
        help="modify a profile",
    )
    profile_modify.add_argument("profile_id", type=int, help="profile ID")
    profile_modify.set_defaults(func=command_profile_modify)

    profile_validate = profile_subparsers.add_parser(
        "validate",
        help="validate a profile",
    )
    profile_validate.add_argument(
        "profile_id",
        type=int,
        help="profile ID",
    )
    profile_validate.set_defaults(func=command_profile_validate)

    profile_check = profile_subparsers.add_parser(
        "check",
        help="report missing and empty fields without showing stored values",
    )
    profile_check.add_argument("profile_id", type=int, help="profile ID")
    profile_check.set_defaults(func=command_profile_check)

    profile_fields = profile_subparsers.add_parser(
        "fields",
        help="list supported profile field names",
    )
    profile_fields.set_defaults(func=command_profile_fields)

    profile_field_parser = profile_subparsers.add_parser(
        "field",
        help="create, list, or archive custom profile fields",
    )
    profile_field_subparsers = profile_field_parser.add_subparsers(
        dest="profile_field_command",
        metavar="COMMAND",
    )
    profile_field_add = profile_field_subparsers.add_parser("add", help="add a custom field")
    profile_field_add.set_defaults(func=command_profile_field_add)
    profile_field_list = profile_field_subparsers.add_parser("list", help="list field IDs")
    profile_field_list.set_defaults(func=command_profile_field_list)
    profile_field_archive = profile_field_subparsers.add_parser("archive", help="archive a custom field without deleting values")
    profile_field_archive.add_argument("field_key", help="field key, for example ACCOUNT_NUMBER")
    profile_field_archive.set_defaults(func=command_profile_field_archive)

    profile_rules = profile_subparsers.add_parser(
        "rules",
        help="diagnose rule applicability without attempting passwords",
    )
    profile_rules.add_argument("profile_id", type=int, help="profile ID")
    profile_rules.set_defaults(func=command_profile_rules)

    profile_remove = profile_subparsers.add_parser(
        "remove",
        help="remove a profile",
    )
    profile_remove.add_argument("profile_id", type=int, help="profile ID")
    profile_remove.set_defaults(func=command_profile_remove)

    rules_parser = subparsers.add_parser(
        "rules",
        help="manage password combination rules",
    )
    rules_subparsers = rules_parser.add_subparsers(
        dest="rules_command",
        metavar="COMMAND",
    )

    rules_list = rules_subparsers.add_parser(
        "list",
        help="list rules",
    )
    rules_list.add_argument(
        "--category",
        help="filter by category",
    )
    rules_list.add_argument(
        "--priority",
        help="filter by priority (A1-Xn or Z)",
    )
    rules_list.set_defaults(func=command_rules_list)

    rules_show = rules_subparsers.add_parser(
        "show",
        help="show a rule",
    )
    rules_show.add_argument("rule", help="rule ID or rule number")
    rules_show.set_defaults(func=command_rules_show)

    rules_add = rules_subparsers.add_parser(
        "add",
        help="add a rule",
    )
    rules_add.set_defaults(func=command_rules_add)

    rules_modify = rules_subparsers.add_parser(
        "modify",
        help="modify a rule",
    )
    rules_modify.add_argument("rule", help="rule ID or rule number")
    rules_modify.set_defaults(func=command_rules_modify)

    rules_remove = rules_subparsers.add_parser(
        "remove",
        help="remove a rule",
    )
    rules_remove.add_argument("rule", help="rule ID or rule number")
    rules_remove.set_defaults(func=command_rules_remove)

    rules_archive = rules_subparsers.add_parser(
        "archive",
        help="archive a rule without deleting it",
    )
    rules_archive.add_argument("rule", help="rule ID or rule number")
    rules_archive.set_defaults(func=command_rules_archive)

    return parser


def main() -> None:
    import re
    import sys

    argv = sys.argv[1:]
    if len(argv) == 2 and re.fullmatch(r"rule\d{1,5}", argv[0], re.IGNORECASE) and argv[1] in {"--help", "-h"}:
        reference = argv[0][4:].zfill(5)
        from pdfunlocker.rules.manager import show_rule
        try:
            show_rule(reference)
        except (ValueError, OSError) as exc:
            print(f"Cannot show rule help: {exc}", file=sys.stderr)
            raise SystemExit(2)
        return

    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
