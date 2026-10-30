from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from pdfunlocker.database.manager import SCHEMA
from pdfunlocker.database import maintenance


def create_database(path: Path, filename: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("ALTER TABLE pdf_files ADD COLUMN rule_id TEXT")
        db.execute("ALTER TABLE attempts ADD COLUMN rule_id TEXT")
        db.execute(
            """
            INSERT INTO pdf_files (filename, source_path, sha256)
            VALUES (?, ?, ?)
            """,
            (
                filename,
                f"/tmp/{filename}",
                filename.encode().hex().ljust(64, "0")[:64],
            ),
        )
        db.commit()

    return path


def filenames(path: Path) -> list[str]:
    with sqlite3.connect(path) as db:
        return [
            row[0]
            for row in db.execute(
                "SELECT filename FROM pdf_files ORDER BY id"
            )
        ]


def setup_paths(tmp_path, monkeypatch, database_name="live.sqlite3"):
    app_dir = tmp_path / "app"
    database = app_dir / "database" / database_name

    monkeypatch.setattr(maintenance, "APP_DIR", app_dir)
    monkeypatch.setattr(maintenance, "database_path", lambda: database)

    return app_dir, database


def test_backup_creates_verified_database(tmp_path, monkeypatch):
    app_dir, database = setup_paths(tmp_path, monkeypatch)
    create_database(database, "original.pdf")

    backup = maintenance.backup_database()

    assert backup.is_file()
    assert backup.parent == app_dir / "backups"
    assert filenames(backup) == ["original.pdf"]
    assert maintenance.list_backups() == [backup]
    assert backup.stat().st_mode & 0o777 == 0o600
    assert backup.parent.stat().st_mode & 0o777 == 0o700


def test_backup_rejects_missing_live_database(tmp_path, monkeypatch):
    setup_paths(tmp_path, monkeypatch)

    with pytest.raises(FileNotFoundError):
        maintenance.backup_database()


def test_backup_supports_explicit_destination(tmp_path, monkeypatch):
    _, database = setup_paths(tmp_path, monkeypatch)
    create_database(database, "explicit.pdf")

    destination = tmp_path / "external" / "manual.sqlite3"
    result = maintenance.backup_database(destination)

    assert result == destination
    assert result.is_file()
    assert filenames(result) == ["explicit.pdf"]


def test_restore_creates_safety_backup(tmp_path, monkeypatch):
    app_dir, database = setup_paths(tmp_path, monkeypatch)

    create_database(database, "current.pdf")
    source = create_database(
        tmp_path / "source" / "restore.sqlite3",
        "restored.pdf",
    )

    restored, safety_backup = maintenance.restore_database(source)

    assert restored == database
    assert filenames(database) == ["restored.pdf"]
    assert safety_backup.is_file()
    assert filenames(safety_backup) == ["current.pdf"]
    assert maintenance.list_backups() == [safety_backup]


def test_restore_rejects_corrupted_backup_without_changing_database(
    tmp_path, monkeypatch
):
    _, database = setup_paths(tmp_path, monkeypatch)
    create_database(database, "keep.pdf")

    corrupted = tmp_path / "corrupted.sqlite3"
    corrupted.write_text("not a SQLite database", encoding="utf-8")

    with pytest.raises((ValueError, sqlite3.Error)):
        maintenance.restore_database(corrupted)

    assert filenames(database) == ["keep.pdf"]


def test_restore_rejects_incomplete_database(tmp_path, monkeypatch):
    _, database = setup_paths(tmp_path, monkeypatch)
    create_database(database, "keep.pdf")

    incomplete = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(incomplete) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

    with pytest.raises(ValueError, match="missing required tables"):
        maintenance.restore_database(incomplete)

    assert filenames(database) == ["keep.pdf"]


def test_list_backups_ignores_invalid_files_without_deleting_them(tmp_path):
    valid = create_database(
        tmp_path / "pdfunlocker-valid.sqlite3",
        "valid.pdf",
    )

    corrupted = tmp_path / "pdfunlocker-corrupted.sqlite3"
    corrupted.write_text("invalid", encoding="utf-8")

    incomplete = tmp_path / "pdfunlocker-incomplete.sqlite3"
    with sqlite3.connect(incomplete) as db:
        db.execute("CREATE TABLE unrelated (id INTEGER)")

    result = maintenance.list_backups(tmp_path)

    assert result == [valid]
    assert corrupted.exists()
    assert incomplete.exists()


def test_retention_keeps_newest_verified_backups(tmp_path):
    source = create_database(tmp_path / "source.sqlite3", "sample.pdf")
    folder = tmp_path / "backups"
    folder.mkdir()

    for index in range(32):
        target = folder / f"pdfunlocker-{index:02d}.sqlite3"
        shutil.copy2(source, target)
        os.utime(target, (100000 + index, 100000 + index))

    deleted = maintenance.prune_backups(30, folder)
    remaining = maintenance.list_backups(folder)

    assert len(deleted) == 2
    assert len(remaining) == 30
    assert remaining[0].name == "pdfunlocker-31.sqlite3"
    assert remaining[-1].name == "pdfunlocker-02.sqlite3"


def test_retention_does_not_delete_invalid_backups(tmp_path):
    source = create_database(tmp_path / "source.sqlite3", "sample.pdf")
    folder = tmp_path / "backups"
    folder.mkdir()

    for index in range(3):
        target = folder / f"pdfunlocker-{index:02d}.sqlite3"
        shutil.copy2(source, target)
        os.utime(target, (100000 + index, 100000 + index))

    invalid = folder / "pdfunlocker-invalid.sqlite3"
    invalid.write_text("invalid", encoding="utf-8")

    deleted = maintenance.prune_backups(2, folder)

    assert len(deleted) == 1
    assert invalid.exists()
    assert len(maintenance.list_backups(folder)) == 2


def test_validation_rejects_missing_required_columns(tmp_path):
    incomplete = tmp_path / "pdfunlocker-incomplete.sqlite3"

    with sqlite3.connect(incomplete) as db:
        db.execute("CREATE TABLE pdf_files (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE attempts (id INTEGER PRIMARY KEY)")

    with pytest.raises(ValueError, match="missing required columns"):
        maintenance._validate_database(incomplete)


def test_temporary_database_files_are_created_with_private_permissions(
    tmp_path, monkeypatch
):
    _, database = setup_paths(tmp_path, monkeypatch)
    create_database(database, "private.pdf")

    destination = tmp_path / "external" / "private-backup.sqlite3"
    result = maintenance.backup_database(destination)

    assert result.stat().st_mode & 0o777 == 0o600
    assert not destination.with_name(destination.name + ".tmp").exists()


def test_legacy_database_is_migrated_before_backup(tmp_path, monkeypatch):
    _, database = setup_paths(tmp_path, monkeypatch)
    database.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE pdf_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                source_path TEXT NOT NULL,
                original_path TEXT,
                unlocked_path TEXT,
                sha256 TEXT NOT NULL UNIQUE,
                profile_used TEXT,
                bank_used TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                pattern_identifier TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT,
                error TEXT
            );

            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_id INTEGER NOT NULL,
                profile_name TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                pattern_identifier TEXT NOT NULL,
                result TEXT NOT NULL,
                elapsed_ms REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (pdf_id) REFERENCES pdf_files(id)
            );
            """
        )
        db.execute(
            """
            INSERT INTO pdf_files (filename, source_path, sha256)
            VALUES ('legacy.pdf', '/tmp/legacy.pdf', ?)
            """,
            ("e" * 64,),
        )

    from pdfunlocker.database import manager

    monkeypatch.setattr(manager, "database_path", lambda: database)

    manager.initialize_database()

    backup = maintenance.backup_database()

    assert filenames(backup) == ["legacy.pdf"]
    maintenance._validate_database(backup)


def test_backup_validation_rejects_future_schema_version(tmp_path):
    future = create_database(tmp_path / "future.sqlite3", "future.pdf")

    with sqlite3.connect(future) as db:
        db.execute("PRAGMA user_version = 999")

    with pytest.raises(ValueError, match="newer than supported"):
        maintenance._validate_database(future)
