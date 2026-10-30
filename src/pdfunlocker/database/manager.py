from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS pdf_files (
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

CREATE INDEX IF NOT EXISTS idx_pdf_files_status ON pdf_files(status);
CREATE INDEX IF NOT EXISTS idx_pdf_files_profile ON pdf_files(profile_used);
CREATE INDEX IF NOT EXISTS idx_pdf_files_sha256 ON pdf_files(sha256);

CREATE TABLE IF NOT EXISTS attempts (
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

CREATE INDEX IF NOT EXISTS idx_attempts_pdf_id ON attempts(pdf_id);
CREATE INDEX IF NOT EXISTS idx_attempts_profile ON attempts(profile_name);
CREATE INDEX IF NOT EXISTS idx_attempts_result ON attempts(result);
CREATE INDEX IF NOT EXISTS idx_attempts_pdf_profile ON attempts(pdf_id, profile_name);
"""

VALID_STATUSES = {
    "pending", "processing", "unlocked", "failed",
    "skipped", "locked", "corrupted",
}


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _secure_database_file(path: Path) -> None:
    try:
        if path.exists():
            path.chmod(0o600)
    except OSError:
        pass


def database_path() -> Path:
    from pdfunlocker.paths import DATABASE_DIR

    _secure_directory(DATABASE_DIR)
    return DATABASE_DIR / "pdfunlocker.sqlite3"


def connect() -> sqlite3.Connection:
    path = database_path()
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA synchronous = FULL")
    _secure_database_file(path)
    return connection


def initialize_database() -> None:
    path = database_path()
    with connect() as connection:
        connection.executescript(SCHEMA)
        connection.commit()
    _secure_database_file(path)


def record_attempt(
    pdf_id: int,
    profile_name: str,
    attempt_number: int,
    pattern_identifier: str,
    result: str,
    elapsed_ms: float | None = None,
    rule_id: str | None = None,
) -> None:
    from datetime import datetime, timezone

    if result not in {"failed", "success"}:
        raise ValueError(f"Invalid attempt result: {result}")

    created_at = datetime.now(timezone.utc).isoformat()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO attempts (
                pdf_id, profile_name, attempt_number, pattern_identifier,
                result, elapsed_ms, created_at, rule_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pdf_id, profile_name, attempt_number, pattern_identifier,
                result, elapsed_ms, created_at, rule_id,
            ),
        )
        connection.commit()


def clear_attempts_for_profile(pdf_id: int, profile_name: str) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM attempts WHERE pdf_id = ? AND profile_name = ?",
            (pdf_id, profile_name),
        )
        connection.commit()


def list_attempts(
    pdf_id: int,
    profile_name: str | None = None,
) -> list[sqlite3.Row]:
    with connect() as connection:
        if profile_name is not None:
            return connection.execute(
                """
                SELECT * FROM attempts
                WHERE pdf_id = ? AND profile_name = ?
                ORDER BY attempt_number
                """,
                (pdf_id, profile_name),
            ).fetchall()

        return connection.execute(
            "SELECT * FROM attempts WHERE pdf_id = ? ORDER BY id",
            (pdf_id,),
        ).fetchall()


def add_pdf(
    filename: str,
    source_path: str,
    sha256: str,
    profile_used: str | None = None,
) -> int | None:
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO pdf_files
                (filename, source_path, sha256, profile_used)
            VALUES (?, ?, ?, ?)
            """,
            (filename, source_path, sha256, profile_used),
        )
        connection.commit()
        return None if cursor.rowcount == 0 else int(cursor.lastrowid)


def get_pdf_by_id(pdf_id: int) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM pdf_files WHERE id = ?", (pdf_id,)
        ).fetchone()


def get_pdf_by_hash(sha256: str) -> sqlite3.Row | None:
    with connect() as connection:
        return connection.execute(
            "SELECT * FROM pdf_files WHERE sha256 = ?", (sha256,)
        ).fetchone()


def update_status(
    pdf_id: int,
    status: str,
    *,
    original_path: str | None = None,
    unlocked_path: str | None = None,
    profile_used: str | None = None,
    bank_used: str | None = None,
    pattern_identifier: str | None = None,
    attempt_count: int | None = None,
    processed_at: str | None = None,
    error: str | None = None,
    rule_id: str | None = None,
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid PDF status: {status}")

    fields = ["status = ?"]
    values: list[object] = [status]
    optional_values = {
        "original_path": original_path,
        "unlocked_path": unlocked_path,
        "profile_used": profile_used,
        "bank_used": bank_used,
        "pattern_identifier": pattern_identifier,
        "attempt_count": attempt_count,
        "processed_at": processed_at,
        "error": error,
        "rule_id": rule_id,
    }

    for field, value in optional_values.items():
        if value is not None:
            fields.append(f"{field} = ?")
            values.append(value)

    values.append(pdf_id)

    with connect() as connection:
        connection.execute(
            f"UPDATE pdf_files SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        connection.commit()


def list_pdfs(status: str | None = None) -> list[sqlite3.Row]:
    with connect() as connection:
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"Invalid PDF status: {status}")

            return connection.execute(
                "SELECT * FROM pdf_files WHERE status = ? ORDER BY id",
                (status,),
            ).fetchall()

        return connection.execute(
            "SELECT * FROM pdf_files ORDER BY id"
        ).fetchall()
