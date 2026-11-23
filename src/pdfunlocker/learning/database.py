"""Database schema and statistics for PDF Unlocker rule learning."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from pdfunlocker.inbox import initialize_inbox_database
from pdfunlocker.profiles.store import initialize_database as initialize_profile_database
from pdfunlocker.scanner import utc_now


LEARNING_SCHEMA_VERSION = 1


@contextmanager
def connect(database_path):
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")

    try:
        with db:
            yield db
    finally:
        db.close()


def initialize_learning_database(database_path):
    """Initialize existing application schemas and add learning tables."""

    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    initialize_profile_database(path)
    initialize_inbox_database(path)

    with connect(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS learning_batches (
                batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT NOT NULL,
                batch_number INTEGER NOT NULL CHECK (batch_number >= 1),
                status TEXT NOT NULL DEFAULT 'planned'
                    CHECK (status IN (
                        'planned', 'ready', 'processing',
                        'completed', 'failed'
                    )),
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                UNIQUE (profile_id, batch_number),
                FOREIGN KEY (profile_id)
                    REFERENCES profiles(profile_id)
            );

            CREATE TABLE IF NOT EXISTS learning_batch_files (
                profile_id TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                batch_number INTEGER NOT NULL,
                file_order INTEGER NOT NULL CHECK (file_order >= 1),
                state TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN (
                        'pending', 'processing', 'unlocked',
                        'locked', 'skipped', 'failed'
                    )),
                assigned_at TEXT NOT NULL,
                completed_at TEXT,
                PRIMARY KEY (profile_id, sha256),
                UNIQUE (profile_id, batch_number, file_order),
                FOREIGN KEY (profile_id, batch_number)
                    REFERENCES learning_batches(profile_id, batch_number),
                FOREIGN KEY (profile_id)
                    REFERENCES profiles(profile_id),
                FOREIGN KEY (sha256)
                    REFERENCES documents(sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_learning_batch_files_queue
                ON learning_batch_files(profile_id, batch_number, state);

            CREATE INDEX IF NOT EXISTS idx_learning_batch_files_hash
                ON learning_batch_files(sha256);

            CREATE TABLE IF NOT EXISTS document_ownership (
                sha256 TEXT PRIMARY KEY,
                owner_profile_id TEXT NOT NULL,
                successful_rule_id TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                unlocked_at TEXT NOT NULL,
                FOREIGN KEY (sha256)
                    REFERENCES documents(sha256),
                FOREIGN KEY (owner_profile_id)
                    REFERENCES profiles(profile_id)
            );

            CREATE INDEX IF NOT EXISTS idx_document_ownership_profile
                ON document_ownership(owner_profile_id);

            CREATE TABLE IF NOT EXISTS rule_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                rule_fingerprint TEXT NOT NULL,
                candidate_set_fingerprint TEXT NOT NULL,
                batch_number INTEGER,
                outcome TEXT NOT NULL DEFAULT 'running'
                    CHECK (outcome IN (
                        'running', 'success', 'exhausted',
                        'no_candidates', 'error', 'skipped'
                    )),
                attempted_count INTEGER NOT NULL DEFAULT 0
                    CHECK (attempted_count >= 0),
                started_at TEXT NOT NULL,
                completed_at TEXT,
                last_error TEXT,
                FOREIGN KEY (sha256)
                    REFERENCES documents(sha256),
                FOREIGN KEY (profile_id)
                    REFERENCES profiles(profile_id)
            );

            CREATE INDEX IF NOT EXISTS idx_rule_runs_rule_outcome
                ON rule_runs(rule_id, outcome);

            CREATE INDEX IF NOT EXISTS idx_rule_runs_document
                ON rule_runs(sha256, profile_id);

            CREATE INDEX IF NOT EXISTS idx_rule_runs_batch
                ON rule_runs(profile_id, batch_number);

            CREATE TABLE IF NOT EXISTS unlock_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                candidate_number INTEGER NOT NULL
                    CHECK (candidate_number >= 1),
                candidate_fingerprint TEXT NOT NULL,
                result TEXT NOT NULL
                    CHECK (result IN ('failed', 'success', 'error')),
                attempted_at TEXT NOT NULL,
                error_code TEXT,
                UNIQUE (run_id, candidate_number),
                FOREIGN KEY (run_id)
                    REFERENCES rule_runs(run_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_unlock_attempts_run
                ON unlock_attempts(run_id);

            CREATE INDEX IF NOT EXISTS idx_unlock_attempts_result
                ON unlock_attempts(result);
        """)

        db.execute("""
            INSERT OR IGNORE INTO app_metadata(key, value)
            VALUES ('learning_schema_version', ?)
        """, (str(LEARNING_SCHEMA_VERSION),))

        row = db.execute("""
            SELECT value
            FROM app_metadata
            WHERE key = 'learning_schema_version'
        """).fetchone()

        if int(row["value"]) != LEARNING_SCHEMA_VERSION:
            raise RuntimeError(
                "Unsupported learning database schema version: "
                + row["value"]
            )

    try:
        path.chmod(0o600)
    except OSError:
        pass

    return path


def get_rule_statistics(database_path):
    """
    Return shared rule statistics across all profiles.

    A successful PDF is counted once per rule, regardless of how many
    profiles or execution records are associated with that PDF.
    """

    initialize_learning_database(database_path)

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT
                rule_id,
                COUNT(DISTINCT CASE
                    WHEN outcome = 'success' THEN sha256
                END) AS successful_files,
                COUNT(DISTINCT CASE
                    WHEN outcome IN ('success', 'exhausted') THEN sha256
                END) AS completed_files,
                COALESCE(SUM(CASE
                    WHEN outcome IN ('success', 'exhausted')
                    THEN attempted_count
                    ELSE 0
                END), 0) AS candidate_attempts
            FROM rule_runs
            GROUP BY rule_id
            ORDER BY
                successful_files DESC,
                CAST(rule_id AS INTEGER) ASC,
                rule_id ASC
        """).fetchall()

    results = []

    for row in rows:
        successful = row["successful_files"]
        completed = row["completed_files"]

        results.append({
            "rule_id": row["rule_id"],
            "successful_files": successful,
            "completed_files": completed,
            "candidate_attempts": row["candidate_attempts"],
            "success_rate": (
                successful / completed if completed else 0.0
            ),
        })

    return results


def get_learning_status(database_path):
    """Return a compact summary of batches, ownership and attempts."""

    initialize_learning_database(database_path)

    with connect(database_path) as db:
        batches = db.execute("""
            SELECT status, COUNT(*) AS total
            FROM learning_batches
            GROUP BY status
            ORDER BY status
        """).fetchall()

        ownership = db.execute("""
            SELECT owner_profile_id, COUNT(*) AS total
            FROM document_ownership
            GROUP BY owner_profile_id
            ORDER BY owner_profile_id
        """).fetchall()

        attempts = db.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN result = 'success' THEN 1 ELSE 0 END)
                    AS successful,
                SUM(CASE WHEN result = 'failed' THEN 1 ELSE 0 END)
                    AS failed,
                SUM(CASE WHEN result = 'error' THEN 1 ELSE 0 END)
                    AS errors
            FROM unlock_attempts
        """).fetchone()

    return {
        "batches": [dict(row) for row in batches],
        "ownership": [dict(row) for row in ownership],
        "attempts": {
            "total": attempts["total"] or 0,
            "successful": attempts["successful"] or 0,
            "failed": attempts["failed"] or 0,
            "errors": attempts["errors"] or 0,
        },
    }
