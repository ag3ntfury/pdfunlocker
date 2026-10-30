from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from pdfunlocker.database.manager import database_path
from pdfunlocker.paths import APP_DIR

DEFAULT_RETENTION = 30
REQUIRED_TABLES = {"pdf_files", "attempts"}


def _secure(path: Path, directory: bool = False) -> None:
    try:
        path.chmod(0o700 if directory else 0o600)
    except OSError:
        pass


def _backup_directory() -> Path:
    directory = APP_DIR / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    _secure(directory, directory=True)
    return directory


def _validate_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")

    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(
                f"Database integrity check failed: "
                f"{result[0] if result else 'no result'}"
            )

        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValueError(
                "Database is missing required tables: "
                + ", ".join(sorted(missing))
            )

        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(
                f"Database has {len(violations)} foreign-key violation(s)"
            )


def list_backups(
    directory: str | Path | None = None,
) -> list[Path]:
    folder = (
        Path(directory).expanduser().resolve()
        if directory is not None
        else _backup_directory()
    )

    if not folder.is_dir():
        return []

    verified = []
    for path in folder.glob("pdfunlocker-*.sqlite3"):
        try:
            _validate_database(path)
            verified.append(path)
        except (OSError, sqlite3.Error, ValueError):
            continue

    return sorted(
        verified,
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )


def prune_backups(
    keep: int = DEFAULT_RETENTION,
    directory: str | Path | None = None,
) -> list[Path]:
    if keep < 1:
        raise ValueError("Backup retention must be at least 1")

    folder = (
        Path(directory).expanduser().resolve()
        if directory is not None
        else _backup_directory()
    )

    backups = list_backups(folder)
    deleted = []

    for old_backup in backups[keep:]:
        try:
            old_backup.unlink()
            deleted.append(old_backup)
        except OSError:
            continue

    return deleted


def backup_database(destination: str | Path | None = None) -> Path:
    source = database_path().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Main database does not exist: {source}")

    automatic_retention = destination is None

    if automatic_retention:
        backup_dir = _backup_directory()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = backup_dir / f"pdfunlocker-{stamp}.sqlite3"
    else:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

    if target == source:
        raise ValueError("Backup destination cannot be the live database")
    if target.exists():
        raise FileExistsError(f"Backup destination already exists: {target}")

    temporary = target.with_name(target.name + ".tmp")
    if temporary.exists():
        temporary.unlink()

    try:
        with sqlite3.connect(source, timeout=30) as src:
            with sqlite3.connect(temporary, timeout=30) as dst:
                src.backup(dst)

        _secure(temporary)
        _validate_database(temporary)
        os.replace(temporary, target)
        _secure(target)

        if automatic_retention:
            prune_backups(DEFAULT_RETENTION, target.parent)

        return target
    finally:
        if temporary.exists():
            temporary.unlink()


def restore_database(source: str | Path) -> tuple[Path, Path]:
    current = database_path().resolve()
    backup = Path(source).expanduser().resolve()

    if backup == current:
        raise ValueError("Restore source cannot be the live database")

    _validate_database(backup)

    if not current.exists():
        raise FileNotFoundError(f"Current database does not exist: {current}")

    safety_backup = backup_database()
    temporary = current.with_name(current.name + ".restore.tmp")

    if temporary.exists():
        temporary.unlink()

    try:
        with sqlite3.connect(backup, timeout=30) as src:
            with sqlite3.connect(temporary, timeout=30) as dst:
                src.backup(dst)

        _secure(temporary)
        _validate_database(temporary)
        os.replace(temporary, current)
        _secure(current)
        return current, safety_backup
    finally:
        if temporary.exists():
            temporary.unlink()
