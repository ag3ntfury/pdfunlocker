"""Consistent SQLite snapshots for private recovery and user-accessible exports."""

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _integrity_check(path):
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        rows = db.execute("PRAGMA integrity_check").fetchall()
    return len(rows) == 1 and rows[0][0] == "ok"


def create_database_snapshot(database_path, destination_directory, label="manual"):
    source = Path(database_path).expanduser().resolve()
    destination_directory = Path(destination_directory).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Active database not found: {source}")
    destination_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_directory / f"pdfunlocker-{label}-{stamp}.sqlite3"
    fd, temporary_name = tempfile.mkstemp(prefix=".pdfunlocker-export-", suffix=".tmp", dir=destination_directory)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_db:
            with sqlite3.connect(temporary) as target_db:
                source_db.backup(target_db)
                result = target_db.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError("Database export failed SQLite integrity_check.")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        if not _integrity_check(destination):
            destination.unlink(missing_ok=True)
            raise RuntimeError("Exported database did not pass integrity_check.")
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def export_database(database_path, pdf_storage, kind="manual", recovery_directory=None, export_root=None):
    if kind not in {"manual", "automatic"}:
        raise ValueError("Export kind must be 'manual' or 'automatic'.")
    # A private recovery snapshot is created first, independently of public export storage.
    recovery = None
    if recovery_directory is not None:
        recovery = create_database_snapshot(database_path, recovery_directory, "recovery")
    export_root = Path(export_root) if export_root is not None else Path(pdf_storage) / "Export"
    folder = export_root / "Database" / ("Manual" if kind == "manual" else "Automatic")
    exported = create_database_snapshot(database_path, folder, kind)
    return {"recovery": recovery, "export": exported}


def migrate_database(source_path, destination_path):
    """Safely copy a legacy live database without altering its source."""
    source = Path(source_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source database not found: {source}")
    if destination.exists():
        raise FileExistsError(f"Destination database already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".pdfunlocker-migration-", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_db:
            with sqlite3.connect(temporary) as target_db:
                source_db.backup(target_db)
                result = target_db.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError("Migrated database failed SQLite integrity_check.")
        os.replace(temporary, destination)
        if not _integrity_check(destination):
            destination.unlink(missing_ok=True)
            raise RuntimeError("Migrated database failed post-copy integrity_check.")
        return destination
    finally:
        temporary.unlink(missing_ok=True)
