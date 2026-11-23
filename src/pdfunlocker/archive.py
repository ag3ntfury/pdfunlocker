"""Verified, SHA-256-addressed PDF archival with incremental processing."""

import errno
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pdfunlocker.scanner import initialize_scanner_database


CHUNK_SIZE = 1024 * 1024


def archive_filename(sha256, extension=".pdf"):
    value = str(sha256).lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid SHA-256 digest.")

    extension = str(extension).lower()
    if (
        not extension.startswith(".")
        or "/" in extension
        or "\\" in extension
        or extension in (".", "..")
    ):
        raise ValueError("Invalid archive file extension.")

    return f"{value}{extension}"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def calculate_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        while True:
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def initialize_archive_database(database_path):
    initialize_scanner_database(database_path)

    with connect(database_path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS archive_records (
                sha256 TEXT PRIMARY KEY,
                archive_path TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('pending', 'archived', 'failed')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                verified_at TEXT,
                last_error TEXT,
                FOREIGN KEY (sha256) REFERENCES documents(sha256)
            );

            CREATE TABLE IF NOT EXISTS archive_sources (
                sha256 TEXT NOT NULL,
                source_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                first_recorded_at TEXT NOT NULL,
                last_recorded_at TEXT NOT NULL,
                PRIMARY KEY (sha256, source_path),
                FOREIGN KEY (sha256) REFERENCES documents(sha256)
            );

            CREATE TABLE IF NOT EXISTS archive_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sha256) REFERENCES documents(sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_archive_records_status
                ON archive_records(status);

            CREATE INDEX IF NOT EXISTS idx_archive_sources_hash
                ON archive_sources(sha256);
        """)


def _record_event(db, sha256, event_type, details=None):
    db.execute("""
        INSERT INTO archive_events (
            sha256, event_type, details, created_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        sha256,
        event_type,
        json.dumps(details, ensure_ascii=False) if details is not None else None,
        utc_now(),
    ))


def _record_sources(db, sha256):
    """Record current paths and historical paths from move events."""
    sources = {}

    rows = db.execute("""
        SELECT path, filename
        FROM file_instances
        WHERE sha256 = ?
        ORDER BY path
    """, (sha256,)).fetchall()

    for row in rows:
        sources[row["path"]] = row["filename"]

    events = db.execute("""
        SELECT details
        FROM document_events
        WHERE sha256 = ?
          AND event_type = 'file_moved'
          AND details IS NOT NULL
        ORDER BY event_id
    """, (sha256,)).fetchall()

    for event in events:
        try:
            details = json.loads(event["details"])
        except (TypeError, ValueError):
            continue

        old_path = details.get("old_path")
        new_path = details.get("new_path")

        if old_path:
            sources.setdefault(old_path, Path(old_path).name)
        if new_path:
            sources.setdefault(new_path, Path(new_path).name)

    now = utc_now()

    for source_path, filename in sources.items():
        db.execute("""
            INSERT INTO archive_sources (
                sha256, source_path, filename,
                first_recorded_at, last_recorded_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sha256, source_path)
            DO UPDATE SET
                filename = excluded.filename,
                last_recorded_at = excluded.last_recorded_at
        """, (sha256, source_path, filename, now, now))


def _copy_exclusive(temporary, destination):
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    with os.fdopen(descriptor, "wb") as target:
        with Path(temporary).open("rb") as source:
            shutil.copyfileobj(source, target, CHUNK_SIZE)
        target.flush()
        os.fsync(target.fileno())


def _publish_without_overwrite(temporary, destination):
    if not hasattr(os, "link"):
        _copy_exclusive(temporary, destination)
        return

    try:
        os.link(temporary, destination)
        return
    except FileExistsError:
        raise
    except OSError as error:
        unsupported = {
            errno.EPERM,
            errno.EOPNOTSUPP,
            errno.ENOTSUP,
            errno.EXDEV,
            errno.ENOSYS,
        }
        if error.errno not in unsupported:
            raise

    _copy_exclusive(temporary, destination)


def _copy_verified(source, destination, expected_sha256, expected_size):
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    stat_before = source.stat()
    if not source.is_file():
        raise OSError(f"Source is not a regular file: {source}")

    if stat_before.st_size != expected_size:
        raise RuntimeError("Source file size differs from scanner inventory.")

    if calculate_sha256(source) != expected_sha256:
        raise RuntimeError("Source SHA-256 differs from scanner inventory.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{expected_sha256}.",
        suffix=".partial",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as target:
            with source.open("rb") as source_file:
                shutil.copyfileobj(source_file, target, CHUNK_SIZE)
            target.flush()
            os.fsync(target.fileno())

        stat_after = source.stat()
        if (
            stat_before.st_size != stat_after.st_size
            or stat_before.st_mtime_ns != stat_after.st_mtime_ns
        ):
            raise RuntimeError("Source changed while being archived.")

        if temporary.stat().st_size != expected_size:
            raise RuntimeError("Temporary archive has an unexpected size.")

        if calculate_sha256(temporary) != expected_sha256:
            raise RuntimeError("Temporary archive failed SHA-256 verification.")

        _publish_without_overwrite(temporary, destination)

        if not destination.is_file():
            raise RuntimeError("Published archive is not a regular file.")

        if destination.stat().st_size != expected_size:
            raise RuntimeError("Published archive has an unexpected size.")

        if calculate_sha256(destination) != expected_sha256:
            raise RuntimeError("Published archive failed final verification.")

        return "copied"

    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _find_verified_source(source_rows, sha256):
    errors = []

    for row in source_rows:
        candidate = Path(row["path"])

        try:
            if not candidate.is_file():
                continue

            if calculate_sha256(candidate) == sha256:
                return candidate, errors

            errors.append(
                f"{candidate}: source hash no longer matches inventory"
            )
        except OSError as error:
            errors.append(f"{candidate}: {error}")

    return None, errors


def archive_documents(database_path, original_directory, force=False):
    """Archive new documents; leave verified archives untouched in normal mode.

    force=True rechecks existing archive files but never overwrites them.
    Missing archives may be recreated from a verified source.
    """
    initialize_archive_database(database_path)

    original_directory = Path(original_directory).expanduser()
    original_directory.mkdir(parents=True, exist_ok=True)
    original_directory = original_directory.resolve()

    with connect(database_path) as db:
        documents = db.execute("""
            SELECT DISTINCT d.sha256, d.file_size
            FROM documents AS d
            JOIN file_instances AS fi ON fi.sha256 = d.sha256
            WHERE fi.file_status = 'present'
            ORDER BY d.sha256
        """).fetchall()

    result = {
        "documents_found": len(documents),
        "archived": 0,
        "copied": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    for document in documents:
        sha256 = document["sha256"]
        file_size = document["file_size"]
        destination = original_directory / archive_filename(sha256)

        with connect(database_path) as db:
            _record_sources(db, sha256)

            record = db.execute("""
                SELECT archive_path, file_size, status
                FROM archive_records
                WHERE sha256 = ?
            """, (sha256,)).fetchone()

            source_rows = db.execute("""
                SELECT path
                FROM file_instances
                WHERE sha256 = ? AND file_status = 'present'
                ORDER BY path
            """, (sha256,)).fetchall()

            now = utc_now()

            if record is None:
                db.execute("""
                    INSERT INTO archive_records (
                        sha256, archive_path, file_size, status,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'pending', ?, ?)
                """, (sha256, str(destination), file_size, now, now))
            elif record["archive_path"] != str(destination):
                result["failed"] += 1
                message = (
                    "Archive record points to a different destination; "
                    "no path was changed."
                )
                result["errors"].append({
                    "sha256": sha256,
                    "error": message,
                })
                db.execute("""
                    UPDATE archive_records
                    SET status = 'failed', updated_at = ?, last_error = ?
                    WHERE sha256 = ?
                """, (now, message, sha256))
                _record_event(db, sha256, "archive_failed", {"error": message})
                continue
            else:
                db.execute("""
                    UPDATE archive_records
                    SET file_size = ?, status = 'pending',
                        updated_at = ?, last_error = NULL
                    WHERE sha256 = ?
                      AND status != 'archived'
                """, (file_size, now, sha256))

        # Normal mode trusts the previously verified archive record.
        # It does not rehash, recopy, or reset its status.
        if (
            record is not None
            and record["status"] == "archived"
            and not force
            and destination.is_file()
        ):
            result["archived"] += 1
            result["skipped"] += 1
            continue

        try:
            if destination.exists():
                if not destination.is_file():
                    raise RuntimeError(
                        "Archive destination is not a regular file."
                    )

                if destination.stat().st_size != file_size:
                    raise FileExistsError(
                        "Existing archive has an incorrect size; "
                        "it was not overwritten."
                    )

                if calculate_sha256(destination) != sha256:
                    raise FileExistsError(
                        "Existing archive has an incorrect SHA-256; "
                        "it was not overwritten."
                    )

                operation = "reused"

            else:
                source, source_errors = _find_verified_source(
                    source_rows, sha256
                )

                if source is None:
                    detail = "; ".join(source_errors) or (
                        "No available source path."
                    )
                    raise FileNotFoundError(detail)

                operation = _copy_verified(
                    source, destination, sha256, file_size
                )

            now = utc_now()
            with connect(database_path) as db:
                db.execute("""
                    UPDATE archive_records
                    SET status = 'archived',
                        updated_at = ?,
                        verified_at = ?,
                        last_error = NULL
                    WHERE sha256 = ?
                """, (now, now, sha256))

                _record_event(db, sha256, "archive_verified", {
                    "archive_path": str(destination),
                    "operation": operation,
                    "forced": bool(force),
                })

            result["archived"] += 1
            result[operation] += 1

        except Exception as error:
            message = str(error)
            now = utc_now()

            with connect(database_path) as db:
                db.execute("""
                    UPDATE archive_records
                    SET status = 'failed',
                        updated_at = ?,
                        last_error = ?
                    WHERE sha256 = ?
                """, (now, message, sha256))

                _record_event(
                    db, sha256, "archive_failed", {"error": message}
                )

            result["failed"] += 1
            result["errors"].append({
                "sha256": sha256,
                "error": message,
            })

    return result


def get_archive_status(database_path):
    initialize_archive_database(database_path)

    with connect(database_path) as db:
        counts = db.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) AS archived,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM archive_records
        """).fetchone()

        records = db.execute("""
            SELECT sha256, archive_path, file_size, status,
                   created_at, updated_at, verified_at, last_error
            FROM archive_records
            ORDER BY created_at, sha256
        """).fetchall()

        return {
            "total": counts["total"] or 0,
            "archived": counts["archived"] or 0,
            "pending": counts["pending"] or 0,
            "failed": counts["failed"] or 0,
            "records": [dict(row) for row in records],
        }
