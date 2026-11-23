"""PDF discovery, SHA-256 inventory, and duplicate tracking."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


SCANNER_SCHEMA_VERSION = 1
CHUNK_SIZE = 1024 * 1024


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


def initialize_scanner_database(database_path):
    """Create scanner tables without modifying profile tables."""

    with connect(database_path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS scan_runs (
                scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL
                    CHECK (status IN ('running', 'completed', 'partial', 'failed')),
                roots_json TEXT NOT NULL,
                files_seen INTEGER NOT NULL DEFAULT 0,
                files_hashed INTEGER NOT NULL DEFAULT 0,
                errors_count INTEGER NOT NULL DEFAULT 0,
                duplicates_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS documents (
                sha256 TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                encryption_status TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (encryption_status IN (
                        'unknown', 'encrypted', 'not_encrypted'
                    )),
                processing_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (processing_status IN (
                        'pending', 'processing', 'unlocked',
                        'locked', 'corrupted', 'unsupported'
                    )),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_instances (
                instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                modified_at REAL NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                file_status TEXT NOT NULL DEFAULT 'present'
                    CHECK (file_status IN ('present', 'missing', 'changed')),
                FOREIGN KEY (sha256)
                    REFERENCES documents(sha256)
            );

            CREATE INDEX IF NOT EXISTS idx_file_instances_hash
                ON file_instances(sha256);

            CREATE INDEX IF NOT EXISTS idx_file_instances_status
                ON file_instances(file_status);

            CREATE TABLE IF NOT EXISTS document_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT,
                instance_id INTEGER,
                scan_id INTEGER,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sha256) REFERENCES documents(sha256),
                FOREIGN KEY (instance_id) REFERENCES file_instances(instance_id),
                FOREIGN KEY (scan_id) REFERENCES scan_runs(scan_id)
            );

            CREATE TABLE IF NOT EXISTS scan_errors (
                error_id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                path TEXT,
                error_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (scan_id) REFERENCES scan_runs(scan_id)
            );

            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        db.execute("""
            INSERT OR IGNORE INTO app_metadata(key, value)
            VALUES ('scanner_schema_version', ?)
        """, (str(SCANNER_SCHEMA_VERSION),))

        version = db.execute("""
            SELECT value FROM app_metadata
            WHERE key = 'scanner_schema_version'
        """).fetchone()

        if int(version["value"]) != SCANNER_SCHEMA_VERSION:
            raise RuntimeError(
                "Unsupported scanner database schema version: "
                f"{version['value']}"
            )

    try:
        Path(database_path).expanduser().chmod(0o600)
    except OSError:
        pass


def _is_inside(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalise_paths(values):
    result = []

    for value in values or []:
        path = Path(value).expanduser().resolve(strict=False)

        if path not in result:
            result.append(path)

    return result


def _is_excluded(path, exclusions):
    return any(
        path == excluded or _is_inside(path, excluded)
        for excluded in exclusions
    )


def discover_pdfs(settings):
    """Yield PDF paths from configured scan locations."""

    scan = settings.get("scan", {})
    roots = _normalise_paths(scan.get("locations", []))
    exclusions = _normalise_paths(scan.get("exclude_paths", []))

    extensions = {
        str(item).lower()
        for item in scan.get("file_extensions", [".pdf"])
    }

    if not roots:
        raise ValueError("No scan locations are configured.")

    recursive = bool(scan.get("recursive", True))
    follow_symlinks = bool(scan.get("follow_symlinks", False))

    for root in roots:
        if not root.exists():
            continue

        if not root.is_dir():
            continue

        if _is_excluded(root, exclusions):
            continue

        if recursive:
            for current, directories, filenames in os.walk(
                root,
                topdown=True,
                followlinks=follow_symlinks,
            ):
                current_path = Path(current).resolve(strict=False)

                directories[:] = [
                    name for name in directories
                    if not _is_excluded(
                        (current_path / name).resolve(strict=False),
                        exclusions,
                    )
                    and (
                        follow_symlinks
                        or not (current_path / name).is_symlink()
                    )
                ]

                for filename in filenames:
                    candidate = current_path / filename

                    if not follow_symlinks and candidate.is_symlink():
                        continue

                    if candidate.suffix.lower() not in extensions:
                        continue

                    if _is_excluded(candidate.resolve(strict=False), exclusions):
                        continue

                    yield candidate

        else:
            try:
                entries = root.iterdir()
            except OSError:
                continue

            for candidate in entries:
                if not candidate.is_file():
                    continue

                if not follow_symlinks and candidate.is_symlink():
                    continue

                if candidate.suffix.lower() in extensions:
                    if not _is_excluded(
                        candidate.resolve(strict=False), exclusions
                    ):
                        yield candidate


def calculate_sha256(path):
    """Hash a file without loading it entirely into memory."""

    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        while True:
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)

    return digest.hexdigest()


def _record_event(db, sha256, instance_id, scan_id, event_type, details=None):
    db.execute("""
        INSERT INTO document_events (
            sha256, instance_id, scan_id,
            event_type, details, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        sha256,
        instance_id,
        scan_id,
        event_type,
        json.dumps(details, ensure_ascii=False) if details is not None else None,
        utc_now(),
    ))


def _record_error(db, scan_id, path, error):
    db.execute("""
        INSERT INTO scan_errors (
            scan_id, path, error_type, message, created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        scan_id,
        str(path) if path is not None else None,
        type(error).__name__,
        str(error),
        utc_now(),
    ))


def _mark_old_instances_missing(db, roots):
    rows = db.execute("""
        SELECT instance_id, path
        FROM file_instances
        WHERE file_status = 'present'
    """).fetchall()

    now = utc_now()

    for row in rows:
        old_path = Path(row["path"])

        if any(_is_inside(old_path, root) for root in roots):
            if not old_path.exists():
                db.execute("""
                    UPDATE file_instances
                    SET file_status = 'missing', last_seen_at = ?
                    WHERE instance_id = ?
                """, (now, row["instance_id"]))

                _record_event(
                    db, None, row["instance_id"], None,
                    "file_missing", {"path": row["path"]},
                )



def _try_record_move(db, sha256, new_path, filename, file_size,
                     modified_at, roots, scan_id):
    """Conservatively infer a move from one disappeared matching instance."""
    rows = db.execute("""
        SELECT instance_id, path, file_status
        FROM file_instances
        WHERE sha256 = ?
        ORDER BY instance_id
    """, (sha256,)).fetchall()

    disappeared = []
    existing_copies = []

    for row in rows:
        old_path = Path(row["path"])
        try:
            exists = old_path.exists()
        except OSError:
            exists = True

        if exists:
            existing_copies.append(row)
        elif (
            row["file_status"] in ("present", "missing")
            and any(_is_inside(old_path, root) for root in roots)
        ):
            disappeared.append(row)

    # If another matching copy survives, this is a duplicate, not a move.
    if existing_copies or len(disappeared) != 1:
        return None

    candidate = disappeared[0]
    old_path = candidate["path"]
    now = utc_now()

    db.execute("""
        UPDATE file_instances
        SET path = ?, filename = ?, file_size = ?,
            modified_at = ?, last_seen_at = ?, file_status = 'present'
        WHERE instance_id = ?
    """, (
        new_path, filename, file_size, modified_at,
        now, candidate["instance_id"],
    ))

    _record_event(
        db, sha256, candidate["instance_id"], scan_id,
        "file_moved",
        {
            "old_path": old_path,
            "new_path": new_path,
            "detection": "sha256_single_disappeared_instance",
        },
    )

    return candidate["instance_id"]


def scan(database_path, settings):
    """Scan configured folders and update the PDF inventory.

    Source files are opened read-only and are never modified.
    """

    initialize_scanner_database(database_path)

    scan_settings = settings.get("scan", {})
    roots = _normalise_paths(scan_settings.get("locations", []))

    if not roots:
        raise ValueError("No scan locations are configured.")

    started = utc_now()
    roots_json = json.dumps(
        [str(root) for root in roots],
        ensure_ascii=False,
    )

    with connect(database_path) as db:
        cursor = db.execute("""
            INSERT INTO scan_runs (
                started_at, status, roots_json
            )
            VALUES (?, 'running', ?)
        """, (started, roots_json))

        scan_id = cursor.lastrowid

    files_seen = 0
    files_hashed = 0
    errors_count = 0
    seen_paths = set()

    try:
        for path in discover_pdfs(settings):
            files_seen += 1

            try:
                resolved = path.resolve(strict=True)
                stat_before = resolved.stat()

                if not resolved.is_file():
                    continue

                path_string = str(resolved)
                seen_paths.add(path_string)

                sha256 = calculate_sha256(resolved)
                stat_after = resolved.stat()

                if (
                    stat_before.st_size != stat_after.st_size
                    or stat_before.st_mtime_ns != stat_after.st_mtime_ns
                ):
                    raise RuntimeError(
                        "File changed while it was being scanned."
                    )

                now = utc_now()

                with connect(database_path) as db:
                    existing_document = db.execute("""
                        SELECT sha256 FROM documents WHERE sha256 = ?
                    """, (sha256,)).fetchone()

                    if existing_document is None:
                        db.execute("""
                            INSERT INTO documents (
                                sha256, file_size,
                                first_seen_at, last_seen_at
                            )
                            VALUES (?, ?, ?, ?)
                        """, (
                            sha256, stat_after.st_size, now, now,
                        ))

                        _record_event(
                            db, sha256, None, scan_id,
                            "document_discovered",
                            {"path": path_string},
                        )
                    else:
                        db.execute("""
                            UPDATE documents
                            SET file_size = ?, last_seen_at = ?
                            WHERE sha256 = ?
                        """, (stat_after.st_size, now, sha256))

                    existing_instance = db.execute("""
                        SELECT instance_id, sha256, file_status
                        FROM file_instances
                        WHERE path = ?
                    """, (path_string,)).fetchone()

                    if existing_instance is None:
                        moved_instance_id = _try_record_move(
                            db,
                            sha256,
                            path_string,
                            resolved.name,
                            stat_after.st_size,
                            stat_after.st_mtime,
                            roots,
                            scan_id,
                        )

                        if moved_instance_id is not None:
                            existing_instance = db.execute("""
                                SELECT instance_id, sha256, file_status
                                FROM file_instances
                                WHERE path = ?
                            """, (path_string,)).fetchone()

                    if existing_instance is None:
                        cursor = db.execute("""
                            INSERT INTO file_instances (
                                sha256, path, filename,
                                file_size, modified_at,
                                first_seen_at, last_seen_at,
                                file_status
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'present')
                        """, (
                            sha256,
                            path_string,
                            resolved.name,
                            stat_after.st_size,
                            stat_after.st_mtime,
                            now,
                            now,
                        ))

                        instance_id = cursor.lastrowid

                        _record_event(
                            db, sha256, instance_id, scan_id,
                            "file_instance_discovered",
                            {"path": path_string},
                        )

                    else:
                        instance_id = existing_instance["instance_id"]
                        previous_hash = existing_instance["sha256"]

                        if previous_hash != sha256:
                            db.execute("""
                                UPDATE file_instances
                                SET sha256 = ?, filename = ?,
                                    file_size = ?, modified_at = ?,
                                    last_seen_at = ?, file_status = 'changed'
                                WHERE instance_id = ?
                            """, (
                                sha256,
                                resolved.name,
                                stat_after.st_size,
                                stat_after.st_mtime,
                                now,
                                instance_id,
                            ))

                            _record_event(
                                db, sha256, instance_id, scan_id,
                                "file_content_changed",
                                {
                                    "path": path_string,
                                    "previous_sha256": previous_hash,
                                    "new_sha256": sha256,
                                },
                            )

                        else:
                            db.execute("""
                                UPDATE file_instances
                                SET filename = ?, file_size = ?,
                                    modified_at = ?, last_seen_at = ?,
                                    file_status = 'present'
                                WHERE instance_id = ?
                            """, (
                                resolved.name,
                                stat_after.st_size,
                                stat_after.st_mtime,
                                now,
                                instance_id,
                            ))

                    files_hashed += 1

            except (OSError, RuntimeError, ValueError) as error:
                errors_count += 1

                with connect(database_path) as db:
                    _record_error(db, scan_id, path, error)

        with connect(database_path) as db:
            _mark_old_instances_missing(db, roots)

            duplicate_groups = db.execute("""
                SELECT COUNT(*) AS total
                FROM (
                    SELECT sha256
                    FROM file_instances
                    WHERE file_status = 'present'
                    GROUP BY sha256
                    HAVING COUNT(*) > 1
                )
            """).fetchone()["total"]

            status = "partial" if errors_count else "completed"

            db.execute("""
                UPDATE scan_runs
                SET completed_at = ?,
                    status = ?,
                    files_seen = ?,
                    files_hashed = ?,
                    errors_count = ?,
                    duplicates_count = ?
                WHERE scan_id = ?
            """, (
                utc_now(),
                status,
                files_seen,
                files_hashed,
                errors_count,
                duplicate_groups,
                scan_id,
            ))

    except Exception:
        with connect(database_path) as db:
            db.execute("""
                UPDATE scan_runs
                SET completed_at = ?, status = 'failed'
                WHERE scan_id = ?
            """, (utc_now(), scan_id))
        raise

    return {
        "scan_id": scan_id,
        "status": status,
        "files_seen": files_seen,
        "files_hashed": files_hashed,
        "errors": errors_count,
        "duplicate_groups": duplicate_groups,
    }


def get_scan_status(database_path):
    initialize_scanner_database(database_path)

    with connect(database_path) as db:
        latest = db.execute("""
            SELECT * FROM scan_runs
            ORDER BY scan_id DESC LIMIT 1
        """).fetchone()

        documents = db.execute("""
            SELECT COUNT(*) FROM documents
        """).fetchone()[0]

        instances = db.execute("""
            SELECT COUNT(*) FROM file_instances
            WHERE file_status = 'present'
        """).fetchone()[0]

        duplicate_groups = db.execute("""
            SELECT COUNT(*) FROM (
                SELECT sha256
                FROM file_instances
                WHERE file_status = 'present'
                GROUP BY sha256
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]

        return {
            "latest_scan": dict(latest) if latest else None,
            "unique_documents": documents,
            "present_file_instances": instances,
            "duplicate_groups": duplicate_groups,
        }


def get_duplicates(database_path):
    initialize_scanner_database(database_path)

    with connect(database_path) as db:
        groups = db.execute("""
            SELECT sha256, COUNT(*) AS copies
            FROM file_instances
            WHERE file_status = 'present'
            GROUP BY sha256
            HAVING COUNT(*) > 1
            ORDER BY copies DESC, sha256
        """).fetchall()

        result = []

        for group in groups:
            files = db.execute("""
                SELECT path, filename, file_size
                FROM file_instances
                WHERE sha256 = ? AND file_status = 'present'
                ORDER BY path
            """, (group["sha256"],)).fetchall()

            result.append({
                "sha256": group["sha256"],
                "copies": group["copies"],
                "files": [dict(item) for item in files],
            })

        return result
