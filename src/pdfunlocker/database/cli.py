from __future__ import annotations

import argparse
import sys

from pdfunlocker.database.maintenance import backup_database, restore_database


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pdfunlocker-db",
        description="Secure backup and restore for the PDF Unlocker database.",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    backup_parser = subparsers.add_parser(
        "backup", help="create and verify a database backup"
    )
    backup_parser.add_argument(
        "destination", nargs="?", help="optional backup file path"
    )

    restore_parser = subparsers.add_parser(
        "restore", help="restore a verified backup"
    )
    restore_parser.add_argument("source", help="backup database file to restore")

    args = parser.parse_args()

    try:
        if args.action == "backup":
            path = backup_database(args.destination)
            print("Backup created and verified:")
            print(path)
        elif args.action == "restore":
            current, safety = restore_database(args.source)
            print("Restore completed and verified.")
            print(f"Restored database: {current}")
            print(f"Pre-restore safety backup: {safety}")
    except (OSError, ValueError) as exc:
        print(f"Database operation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
