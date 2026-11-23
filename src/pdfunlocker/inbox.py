"""Safe working-copy preparation and result routing for PDF Unlocker."""

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

from pdfunlocker.archive import initialize_archive_database


CHUNK_SIZE = 1024 * 1024
INBOX_SCHEMA_VERSION = 1


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


def initialize_inbox_database(database_path):
    """Create Inbox workflow tables without altering existing schemas."""
    initialize_archive_database(database_path)

    with connect(database_path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_documents (
                sha256 TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN (
                        'pending', 'inbox', 'processing', 'unlocked',
                        'locked', 'corrupted', 'unsupported',
                        'review', 'failed'
                    )),
                current_path TEXT,
                output_sha256 TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_processed_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (sha256) REFERENCES documents(sha256)
            );

            CREATE TABLE IF NOT EXISTS inbox_jobs (
                job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                operation TEXT NOT NULL
                    CHECK (operation IN ('normal', 'force', 'retry')),
                source_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN (
                        'preparing', 'ready', 'completed',
                        'failed', 'conflict'
                    )),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT,
                FOREIGN KEY (sha256) REFERENCES documents(sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_workflow_state
                ON workflow_documents(state);

            CREATE INDEX IF NOT EXISTS idx_inbox_jobs_status
                ON inbox_jobs(status);

            CREATE INDEX IF NOT EXISTS idx_inbox_jobs_hash
                ON inbox_jobs(sha256);
        """)

        db.execute("""
            INSERT OR IGNORE INTO app_metadata(key, value)
            VALUES ('inbox_schema_version', ?)
        """, (str(INBOX_SCHEMA_VERSION),))

        row = db.execute("""
            SELECT value FROM app_metadata
            WHERE key = 'inbox_schema_version'
        """).fetchone()

        if int(row["value"]) != INBOX_SCHEMA_VERSION:
            raise RuntimeError(
                "Unsupported Inbox schema version: " + row["value"]
            )

    try:
        Path(database_path).expanduser().chmod(0o600)
    except OSError:
        pass


def _copy_exclusive(source, destination):
    """Create a destination without ever overwriting an existing file."""
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    with os.fdopen(descriptor, "wb") as target:
        with Path(source).open("rb") as original:
            shutil.copyfileobj(original, target, CHUNK_SIZE)
        target.flush()
        os.fsync(target.fileno())


def _publish_without_overwrite(temporary, destination):
    """Publish without replacing an existing destination."""
    if hasattr(os, "link"):
        try:
            os.link(temporary, destination)
            return
        except FileExistsError:
            raise
        except OSError as error:
            unsupported = {
                errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP,
                errno.EXDEV, errno.ENOSYS,
            }
            if error.errno not in unsupported:
                raise

    _copy_exclusive(temporary, destination)


def copy_verified(source, destination, expected_sha256):
    """Copy and verify a file without overwriting an existing destination."""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not source.is_file():
        raise FileNotFoundError(f"Source file is missing: {source}")

    if calculate_sha256(source) != expected_sha256:
        raise RuntimeError("Source SHA-256 verification failed.")

    if destination.exists():
        if not destination.is_file():
            raise FileExistsError("Destination exists and is not a regular file.")

        if calculate_sha256(destination) != expected_sha256:
            raise FileExistsError(
                "Destination exists with different content; not overwritten."
            )
        return "reused"

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".pdfunlocker-",
        suffix=".partial",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(descriptor, "wb") as target:
            with source.open("rb") as original:
                shutil.copyfileobj(original, target, CHUNK_SIZE)
            target.flush()
            os.fsync(target.fileno())

        if calculate_sha256(temporary) != expected_sha256:
            raise RuntimeError("Temporary copy failed SHA-256 verification.")

        _publish_without_overwrite(temporary, destination)

        if not destination.is_file():
            raise RuntimeError("Published destination is not a regular file.")

        if calculate_sha256(destination) != expected_sha256:
            raise RuntimeError("Published copy failed SHA-256 verification.")

        return "copied"

    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _record_job(db, sha256, operation, source, destination):
    now = utc_now()
    cursor = db.execute("""
        INSERT INTO inbox_jobs (
            sha256, operation, source_path, destination_path,
            status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, 'preparing', ?, ?)
    """, (
        sha256, operation, str(source), str(destination), now, now
    ))
    return cursor.lastrowid


def _set_job_status(database_path, job_id, status, error=None):
    with connect(database_path) as db:
        db.execute("""
            UPDATE inbox_jobs
            SET status = ?, updated_at = ?, last_error = ?
            WHERE job_id = ?
        """, (status, utc_now(), error, job_id))


def _ensure_workflow_document(db, sha256):
    now = utc_now()
    db.execute("""
        INSERT OR IGNORE INTO workflow_documents (
            sha256, state, created_at, updated_at
        )
        VALUES (?, 'pending', ?, ?)
    """, (sha256, now, now))


def prepare_inbox(database_path, pdf_storage, mode="normal"):
    """
    Prepare verified working copies in Inbox.

    normal: only documents not previously processed.
    force: all verified archived documents.
    retry: documents currently recorded as locked, sourced from Locked/.
    """
    if mode not in ("normal", "force", "retry"):
        raise ValueError("Mode must be normal, force or retry.")

    initialize_inbox_database(database_path)

    storage = Path(pdf_storage).expanduser().resolve()
    original_dir = storage / "Original"
    inbox_dir = storage / "Inbox"
    locked_dir = storage / "Locked"

    inbox_dir.mkdir(parents=True, exist_ok=True)

    with connect(database_path) as db:
        if mode == "retry":
            rows = db.execute("""
                SELECT w.sha256, w.current_path, a.file_size
                FROM workflow_documents AS w
                JOIN archive_records AS a ON a.sha256 = w.sha256
                WHERE w.state = 'locked'
                ORDER BY w.updated_at, w.sha256
            """).fetchall()
        elif mode == "force":
            rows = db.execute("""
                SELECT a.sha256, a.archive_path AS current_path, a.file_size
                FROM archive_records AS a
                WHERE a.status = 'archived'
                ORDER BY a.sha256
            """).fetchall()
        else:
            rows = db.execute("""
                SELECT a.sha256, a.archive_path AS current_path, a.file_size
                FROM archive_records AS a
                LEFT JOIN workflow_documents AS w ON w.sha256 = a.sha256
                WHERE a.status = 'archived'
                  AND (w.sha256 IS NULL OR w.state = 'pending')
                ORDER BY a.sha256
            """).fetchall()

    result = {
        "mode": mode,
        "found": len(rows),
        "prepared": 0,
        "reused": 0,
        "skipped": 0,
        "failed": 0,
        "conflicts": 0,
        "errors": [],
    }

    for row in rows:
        sha256 = row["sha256"]

        if mode == "retry":
            source = locked_dir / f"{sha256}.pdf"
        else:
            source = original_dir / f"{sha256}.pdf"

        destination = inbox_dir / f"{sha256}.pdf"

        with connect(database_path) as db:
            _ensure_workflow_document(db, sha256)

            if mode == "normal":
                state = db.execute("""
                    SELECT state FROM workflow_documents WHERE sha256 = ?
                """, (sha256,)).fetchone()["state"]

                if state != "pending":
                    result["skipped"] += 1
                    continue

            if mode == "retry":
                state = db.execute("""
                    SELECT state FROM workflow_documents WHERE sha256 = ?
                """, (sha256,)).fetchone()["state"]

                if state != "locked":
                    result["skipped"] += 1
                    continue

            job_id = _record_job(
                db, sha256, mode, source, destination
            )

        try:
            if not source.is_file():
                raise FileNotFoundError(f"Required source is missing: {source}")

            if source.stat().st_size != row["file_size"]:
                raise RuntimeError("Source size differs from archive inventory.")

            if calculate_sha256(source) != sha256:
                raise RuntimeError("Source does not match expected SHA-256.")

            operation = copy_verified(source, destination, sha256)

            with connect(database_path) as db:
                db.execute("""
                    UPDATE workflow_documents
                    SET state = 'inbox', current_path = ?,
                        last_error = NULL, updated_at = ?
                    WHERE sha256 = ?
                """, (str(destination), utc_now(), sha256))

                db.execute("""
                    UPDATE inbox_jobs
                    SET status = 'ready', updated_at = ?
                    WHERE job_id = ?
                """, (utc_now(), job_id))

            result["prepared"] += 1
            if operation == "reused":
                result["reused"] += 1

        except FileExistsError as error:
            message = str(error)
            _set_job_status(database_path, job_id, "conflict", message)
            result["conflicts"] += 1
            result["errors"].append({"sha256": sha256, "error": message})

        except Exception as error:
            message = str(error)
            _set_job_status(database_path, job_id, "failed", message)

            with connect(database_path) as db:
                db.execute("""
                    UPDATE workflow_documents
                    SET state = 'failed', last_error = ?, updated_at = ?
                    WHERE sha256 = ?
                """, (message, utc_now(), sha256))

            result["failed"] += 1
            result["errors"].append({"sha256": sha256, "error": message})

    return result


def record_unlock_result(database_path, pdf_storage, sha256, result,
                         unlocked_output=None, retry=False):
    """
    Record an Unlocker result and publish its output.

    This function does not run qpdf or attempt passwords.
    The Unlocker supplies the classification and optional output path.
    """
    allowed = {
        "already_unlocked", "unlocked", "locked",
        "corrupted", "unsupported", "needs_review", "error",
    }

    if result not in allowed:
        raise ValueError(f"Invalid Unlocker result: {result}")

    initialize_inbox_database(database_path)

    storage = Path(pdf_storage).expanduser().resolve()
    inbox_file = storage / "Inbox" / f"{sha256}.pdf"

    destinations = {
        "already_unlocked": storage / "Unlocked",
        "unlocked": storage / "Unlocked",
        "locked": storage / "Locked",
        "corrupted": storage / "Corrupted",
        "unsupported": storage / "Unsupported",
        "needs_review": storage / "Review",
    }

    if result == "error":
        with connect(database_path) as db:
            db.execute("""
                UPDATE workflow_documents
                SET state = 'failed', last_error = ?,
                    attempts = attempts + 1, updated_at = ?
                WHERE sha256 = ?
            """, ("Unlocker reported an error.", utc_now(), sha256))
        return {"status": "failed", "inbox_preserved": True}

    source = Path(unlocked_output) if result == "unlocked" else inbox_file
    destination_dir = destinations[result]
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{sha256}.pdf"

    expected_hash = sha256

    if result == "unlocked":
        if unlocked_output is None:
            raise ValueError("Unlocked output path is required.")

        if not source.is_file():
            raise FileNotFoundError("Unlocked output file is missing.")

        expected_hash = calculate_sha256(source)

    if not source.is_file():
        raise FileNotFoundError(f"Result source is missing: {source}")

    operation = copy_verified(source, destination, expected_hash)

    with connect(database_path) as db:
        db.execute("""
            UPDATE workflow_documents
            SET state = ?, current_path = ?, output_sha256 = ?,
                attempts = attempts + 1,
                last_processed_at = ?, last_error = NULL,
                updated_at = ?
            WHERE sha256 = ?
        """, (
            result if result != "already_unlocked" else "unlocked",
            str(destination),
            expected_hash,
            utc_now(),
            utc_now(),
            sha256,
        ))

    # Do not remove the Inbox copy here. Cleanup is a separate operation
    # and will be added after the Workflow Manager is implemented.
    return {
        "status": result,
        "destination": str(destination),
        "operation": operation,
        "inbox_preserved": True,
        "retry": bool(retry),
    }



def cleanup_inbox_item(database_path, pdf_storage, sha256):
    """
    Safely clean one completed Inbox operation.

    Requires a verified destination and matching workflow database record.
    For successful retries, removes the old Locked copy only after verifying
    the Unlocked destination. Original is never modified.
    """
    initialize_inbox_database(database_path)

    storage = Path(pdf_storage).expanduser().resolve()
    inbox_file = storage / "Inbox" / f"{sha256}.pdf"
    locked_file = storage / "Locked" / f"{sha256}.pdf"

    with connect(database_path) as db:
        workflow = db.execute("""
            SELECT state, current_path, output_sha256
            FROM workflow_documents
            WHERE sha256 = ?
        """, (sha256,)).fetchone()

        job = db.execute("""
            SELECT job_id, operation, source_path, destination_path, status
            FROM inbox_jobs
            WHERE sha256 = ?
            ORDER BY job_id DESC
            LIMIT 1
        """, (sha256,)).fetchone()

    if workflow is None or job is None:
        raise RuntimeError("Workflow record or Inbox job is missing.")

    if job["status"] == "completed":
        return {
            "status": "already_completed",
            "inbox_removed": not inbox_file.exists(),
            "locked_removed": not locked_file.exists(),
        }

    if job["status"] != "ready":
        raise RuntimeError(
            f"Inbox job is not ready for cleanup: {job['status']}"
        )

    state = workflow["state"]

    allowed_states = {
        "unlocked", "locked", "corrupted", "unsupported", "review"
    }

    if state not in allowed_states:
        raise RuntimeError(
            f"Document is not in a completed state: {state}"
        )

    expected_inbox = storage / "Inbox" / f"{sha256}.pdf"

    if Path(job["destination_path"]).resolve() != expected_inbox.resolve():
        raise RuntimeError("Inbox job destination does not match expected path.")

    if not workflow["current_path"]:
        raise RuntimeError("Workflow destination path is missing.")

    destination = Path(workflow["current_path"]).resolve()
    expected_destination_dir = storage / {
        "unlocked": "Unlocked",
        "locked": "Locked",
        "corrupted": "Corrupted",
        "unsupported": "Unsupported",
        "review": "Review",
    }[state]

    expected_destination = (
        expected_destination_dir / f"{sha256}.pdf"
    ).resolve()

    if destination != expected_destination.resolve():
        raise RuntimeError("Workflow destination path is unexpected.")

    if not destination.is_file():
        raise FileNotFoundError(
            f"Verified result destination is missing: {destination}"
        )

    expected_output_hash = workflow["output_sha256"]

    if not expected_output_hash:
        raise RuntimeError("Output SHA-256 is missing from workflow record.")

    if calculate_sha256(destination) != expected_output_hash:
        raise RuntimeError("Result destination SHA-256 verification failed.")

    if state != "unlocked" and expected_output_hash != sha256:
        raise RuntimeError("Non-unlocked result has an unexpected output hash.")

    if inbox_file.exists():
        if not inbox_file.is_file():
            raise RuntimeError("Inbox path is not a regular file.")

        if calculate_sha256(inbox_file) != sha256:
            raise RuntimeError("Inbox copy SHA-256 verification failed.")

    # A successful retry may remove its old Locked copy.
    # Verify its exact path and original content before deletion.
    locked_removed = False

    if job["operation"] == "retry" and state == "unlocked":
        recorded_source = Path(job["source_path"]).resolve()

        if recorded_source != locked_file.resolve():
            raise RuntimeError("Retry source is not the expected Locked file.")

        if locked_file.exists():
            if not locked_file.is_file():
                raise RuntimeError("Locked path is not a regular file.")

            if calculate_sha256(locked_file) != sha256:
                raise RuntimeError("Locked copy SHA-256 verification failed.")

            locked_file.unlink()
            locked_removed = True

    # Delete only the verified temporary Inbox copy.
    inbox_removed = False

    if inbox_file.exists():
        inbox_file.unlink()
        inbox_removed = True

    with connect(database_path) as db:
        db.execute("""
            UPDATE inbox_jobs
            SET status = 'completed',
                updated_at = ?,
                last_error = NULL
            WHERE job_id = ? AND status = 'ready'
        """, (utc_now(), job["job_id"]))

    return {
        "status": "completed",
        "state": state,
        "inbox_removed": inbox_removed,
        "locked_removed": locked_removed,
        "destination": str(destination),
    }


def get_workflow_status(database_path):
    initialize_inbox_database(database_path)

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT state, COUNT(*) AS total
            FROM workflow_documents
            GROUP BY state
            ORDER BY state
        """).fetchall()

        return {row["state"]: row["total"] for row in rows}
