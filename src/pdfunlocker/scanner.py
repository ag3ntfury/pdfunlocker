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


def _discover_pdfs_with_errors(settings, report_error):
    """Yield (PDF path, owning root), reporting every traversal failure."""
    scan = settings.get("scan", {})
    roots = _normalise_paths(scan.get("locations", []))
    exclusions = _normalise_paths(scan.get("exclude_paths", []))
    extensions = {
        str(item).lower() if str(item).startswith(".") else "." + str(item).lower()
        for item in scan.get("file_extensions", [".pdf"])
    }

    if not roots:
        raise ValueError("No scan locations are configured.")

    recursive = bool(scan.get("recursive", True))
    follow_symlinks = bool(scan.get("follow_symlinks", False))

    for root in roots:
        if _is_excluded(root, exclusions):
            continue
        try:
            root_stat = root.stat()
            if not root.is_dir():
                report_error(root, NotADirectoryError(f"Scan location is not a directory: {root}"))
                continue
            if not os.access(root, os.R_OK | os.X_OK):
                report_error(root, PermissionError(f"Scan location is not readable: {root}"))
                continue
        except OSError as error:
            report_error(root, error)
            continue

        if recursive:
            visited_directories = set()
            def walk_error(error):
                report_error(getattr(error, "filename", None) or root, error)

            for current, directories, filenames in os.walk(
                root, topdown=True, onerror=walk_error,
                followlinks=follow_symlinks,
            ):
                current_path = Path(current).resolve(strict=False)
                try:
                    current_stat = current_path.stat()
                    identity = (current_stat.st_dev, current_stat.st_ino)
                    if identity in visited_directories:
                        directories[:] = []
                        continue
                    visited_directories.add(identity)
                except OSError as error:
                    report_error(current_path, error)
                    directories[:] = []
                    continue

                kept_directories = []
                for name in directories:
                    candidate_dir = current_path / name
                    try:
                        if _is_excluded(candidate_dir.resolve(strict=False), exclusions):
                            continue
                        if candidate_dir.is_symlink() and not follow_symlinks:
                            continue
                        if follow_symlinks:
                            target_stat = candidate_dir.stat()
                            target_id = (target_stat.st_dev, target_stat.st_ino)
                            if target_id in visited_directories:
                                continue
                        kept_directories.append(name)
                    except OSError as error:
                        report_error(candidate_dir, error)
                directories[:] = kept_directories

                for filename in filenames:
                    candidate = current_path / filename
                    try:
                        if candidate.is_symlink() and not follow_symlinks:
                            continue
                        if candidate.suffix.lower() not in extensions:
                            continue
                        resolved = candidate.resolve(strict=True)
                        if _is_excluded(resolved, exclusions) or not resolved.is_file():
                            continue
                        yield candidate, root
                    except OSError as error:
                        report_error(candidate, error)
        else:
            try:
                entries = list(root.iterdir())
            except OSError as error:
                report_error(root, error)
                continue
            for candidate in entries:
                try:
                    if candidate.is_symlink() and not follow_symlinks:
                        continue
                    if candidate.suffix.lower() not in extensions:
                        continue
                    resolved = candidate.resolve(strict=True)
                    if _is_excluded(resolved, exclusions) or not resolved.is_file():
                        continue
                    yield candidate, root
                except OSError as error:
                    report_error(candidate, error)


def discover_pdfs(settings):
    """Yield PDF paths from configured scan locations (legacy public API)."""
    yield from (path for path, _root in _discover_pdfs_with_errors(settings, lambda *_: None))

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


def _stat_identity(info):
    return (
        info.st_dev, info.st_ino, info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
        getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000)),
    )


def _hash_stable_file(path):
    """Hash one open file and reject replacement or mutation during hashing."""
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as file:
        before = os.fstat(file.fileno())
        while True:
            chunk = file.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(file.fileno())
    path_after = path.stat()
    if _stat_identity(before) != _stat_identity(after):
        raise RuntimeError("File changed while it was being scanned.")
    if (after.st_dev, after.st_ino) != (path_after.st_dev, path_after.st_ino):
        raise RuntimeError("File was replaced while it was being scanned.")
    return digest.hexdigest(), after

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


def _mark_old_instances_missing(db, complete_roots, exclusions=None):
    """Mark missing paths only inside roots whose traversal completed safely."""
    exclusions = exclusions or []
    rows = db.execute("""
        SELECT instance_id, path
        FROM file_instances
        WHERE file_status = 'present'
    """).fetchall()
    now = utc_now()
    for row in rows:
        old_path = Path(row["path"])
        if _is_excluded(old_path, exclusions):
            continue
        if any(_is_inside(old_path, root) for root in complete_roots):
            try:
                exists = old_path.exists()
            except OSError:
                exists = True
            if not exists:
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
    """Scan configured folders; reconcile missing paths only for complete roots."""
    initialize_scanner_database(database_path)
    scan_settings = settings.get("scan", {})
    roots = _normalise_paths(scan_settings.get("locations", []))
    exclusions = _normalise_paths(scan_settings.get("exclude_paths", []))
    if not roots:
        raise ValueError("No scan locations are configured.")

    started = utc_now()
    roots_json = json.dumps([str(root) for root in roots], ensure_ascii=False)
    with connect(database_path) as db:
        cursor = db.execute("""
            INSERT INTO scan_runs (started_at, status, roots_json)
            VALUES (?, 'running', ?)
        """, (started, roots_json))
        scan_id = cursor.lastrowid

    files_seen = files_hashed = errors_count = 0
    active_roots = [root for root in roots if not _is_excluded(root, exclusions)]
    complete_roots = set(active_roots)
    seen_paths = set()

    def record_scan_error(path, error):
        nonlocal errors_count
        errors_count += 1
        try:
            resolved_path = Path(path).resolve(strict=False) if path is not None else None
        except (OSError, TypeError, ValueError):
            resolved_path = path
        for root in roots:
            try:
                if resolved_path is not None and _is_inside(Path(resolved_path), root):
                    complete_roots.discard(root)
            except (TypeError, ValueError):
                pass
        with connect(database_path) as db:
            _record_error(db, scan_id, resolved_path, error)

    try:
        for path, root in _discover_pdfs_with_errors(settings, record_scan_error):
            files_seen += 1
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_file():
                    continue
                path_string = str(resolved)
                seen_paths.add(path_string)
                sha256, stat_after = _hash_stable_file(resolved)
                now = utc_now()

                with connect(database_path) as db:
                    existing_document = db.execute(
                        "SELECT sha256 FROM documents WHERE sha256 = ?", (sha256,)
                    ).fetchone()
                    if existing_document is None:
                        db.execute("""
                            INSERT INTO documents (
                                sha256, file_size, first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?)
                        """, (sha256, stat_after.st_size, now, now))
                        _record_event(db, sha256, None, scan_id,
                                      "document_discovered", {"path": path_string})
                    else:
                        db.execute("""
                            UPDATE documents SET file_size = ?, last_seen_at = ?
                            WHERE sha256 = ?
                        """, (stat_after.st_size, now, sha256))

                    existing_instance = db.execute("""
                        SELECT instance_id, sha256, file_status
                        FROM file_instances WHERE path = ?
                    """, (path_string,)).fetchone()

                    if existing_instance is None:
                        moved_instance_id = _try_record_move(
                            db, sha256, path_string, resolved.name,
                            stat_after.st_size, stat_after.st_mtime, active_roots, scan_id,
                        )
                        if moved_instance_id is not None:
                            existing_instance = db.execute("""
                                SELECT instance_id, sha256, file_status
                                FROM file_instances WHERE path = ?
                            """, (path_string,)).fetchone()

                    if existing_instance is None:
                        cursor = db.execute("""
                            INSERT INTO file_instances (
                                sha256, path, filename, file_size, modified_at,
                                first_seen_at, last_seen_at, file_status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'present')
                        """, (sha256, path_string, resolved.name,
                              stat_after.st_size, stat_after.st_mtime, now, now))
                        _record_event(db, sha256, cursor.lastrowid, scan_id,
                                      "file_instance_discovered", {"path": path_string})
                    else:
                        instance_id = existing_instance["instance_id"]
                        previous_hash = existing_instance["sha256"]
                        if previous_hash != sha256:
                            db.execute("""
                                UPDATE file_instances
                                SET sha256 = ?, filename = ?, file_size = ?,
                                    modified_at = ?, last_seen_at = ?, file_status = 'changed'
                                WHERE instance_id = ?
                            """, (sha256, resolved.name, stat_after.st_size,
                                  stat_after.st_mtime, now, instance_id))
                            _record_event(db, sha256, instance_id, scan_id,
                                          "file_content_changed", {
                                              "path": path_string,
                                              "previous_sha256": previous_hash,
                                              "new_sha256": sha256,
                                          })
                        else:
                            db.execute("""
                                UPDATE file_instances
                                SET filename = ?, file_size = ?, modified_at = ?,
                                    last_seen_at = ?, file_status = 'present'
                                WHERE instance_id = ?
                            """, (resolved.name, stat_after.st_size,
                                  stat_after.st_mtime, now, instance_id))
                files_hashed += 1
            except (OSError, RuntimeError, ValueError) as error:
                complete_roots.discard(root)
                record_scan_error(path, error)

        with connect(database_path) as db:
            _mark_old_instances_missing(db, complete_roots, exclusions)
            duplicate_groups = db.execute("""
                SELECT COUNT(*) AS total FROM (
                    SELECT sha256 FROM file_instances
                    WHERE file_status = 'present'
                    GROUP BY sha256 HAVING COUNT(*) > 1
                )
            """).fetchone()["total"]
            status = "partial" if errors_count else "completed"
            db.execute("""
                UPDATE scan_runs
                SET completed_at = ?, status = ?, files_seen = ?,
                    files_hashed = ?, errors_count = ?, duplicates_count = ?
                WHERE scan_id = ?
            """, (utc_now(), status, files_seen, files_hashed,
                  errors_count, duplicate_groups, scan_id))
    except Exception:
        with connect(database_path) as db:
            db.execute("""
                UPDATE scan_runs SET completed_at = ?, status = 'failed'
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
