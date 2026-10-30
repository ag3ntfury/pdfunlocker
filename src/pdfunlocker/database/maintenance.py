from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from pdfunlocker.database.manager import database_path
from pdfunlocker.paths import APP_DIR


REQUIRED_TABLES = {"pdf_files", "attempts"}


def _secure(path: Path, directory: bool = False) -> None:
    try:
        path.chmod(0o700 if directory else 0o600)
    except OSError:
        pass


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


def backup_database(destination: str | Path | None = None) -> Path:
    source = database_path().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Main database does not exist: {source}")

    if destination is None:
        backup_dir = APP_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        _secure(backup_dir, directory=True)
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
