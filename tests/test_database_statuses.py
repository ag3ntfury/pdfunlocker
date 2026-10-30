import sqlite3

import pytest

from pdfunlocker.database import manager


@pytest.mark.parametrize("status", ["locked", "corrupted"])
def test_new_statuses_are_accepted_in_isolated_database(
    tmp_path, monkeypatch, status
):
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    manager.initialize_database()

    pdf_id = manager.add_pdf(
        filename="sample.pdf",
        source_path=str(tmp_path / "sample.pdf"),
        sha256=("a" if status == "locked" else "b") * 64,
    )

    assert pdf_id is not None
    manager.update_status(pdf_id, status)


def test_initialize_database_adds_rule_id_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    with sqlite3.connect(db_path) as db:
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

    manager.initialize_database()

    with manager.connect() as db:
        pdf_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(pdf_files)")
        }
        attempt_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(attempts)")
        }

    assert "rule_id" in pdf_columns
    assert "rule_id" in attempt_columns


def test_record_attempt_works_without_unlocker_migration(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "fresh.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    pdf_id = manager.add_pdf(
        filename="sample.pdf",
        source_path=str(tmp_path / "sample.pdf"),
        sha256="c" * 64,
    )

    assert pdf_id is not None

    manager.record_attempt(
        pdf_id=pdf_id,
        profile_name="profile1",
        attempt_number=1,
        pattern_identifier="test-rule",
        result="failed",
        rule_id="00123",
    )

    attempts = manager.list_attempts(pdf_id)

    assert len(attempts) == 1
    assert attempts[0]["rule_id"] == "00123"


def test_update_status_supports_rule_id_on_fresh_database(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "fresh.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    pdf_id = manager.add_pdf(
        filename="sample.pdf",
        source_path=str(tmp_path / "sample.pdf"),
        sha256="d" * 64,
    )

    assert pdf_id is not None

    manager.update_status(pdf_id, "failed", rule_id="rule-42")

    record = manager.get_pdf_by_id(pdf_id)

    assert record["rule_id"] == "rule-42"


def test_unlocker_schema_wrapper_uses_centralized_initializer(monkeypatch):
    from pdfunlocker.pdf import unlocker

    calls = []
    monkeypatch.setattr(
        unlocker,
        "initialize_database",
        lambda: calls.append("initialized"),
    )

    unlocker.ensure_schema()

    assert calls == ["initialized"]


def test_schema_migration_runs_only_once(tmp_path, monkeypatch):
    db_path = tmp_path / "versioned.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    original_migration = manager._migrate_schema
    calls = []

    def tracked_migration(connection):
        calls.append(1)
        return original_migration(connection)

    monkeypatch.setattr(manager, "_migrate_schema", tracked_migration)

    manager.initialize_database()

    with manager.connect():
        pass

    with manager.connect():
        pass

    assert len(calls) == 1

    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_future_schema_version_is_rejected(tmp_path, monkeypatch):
    db_path = tmp_path / "future.sqlite3"

    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA user_version = 999")

    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    with pytest.raises(RuntimeError, match="newer than supported"):
        manager.connect()


def test_existing_version_one_database_skips_migration(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "version-one.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)

    manager.initialize_database()

    def unexpected_migration(connection):
        raise AssertionError("Migration should not run for schema version 1")

    monkeypatch.setattr(manager, "_migrate_schema", unexpected_migration)

    with manager.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
