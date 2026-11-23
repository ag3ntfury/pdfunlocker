"""Deterministic, resumable PDF learning batches."""

from pdfunlocker.learning.database import connect, initialize_learning_database
from pdfunlocker.scanner import utc_now


DEFAULT_BATCH_SIZE = 10
TERMINAL_FILE_STATES = ("unlocked", "locked", "skipped")


def _validate_batch_size(batch_size):
    if not isinstance(batch_size, int) or isinstance(batch_size, bool):
        raise ValueError("Batch size must be an integer.")
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1.")
    return batch_size


def _get_enabled_profile(db, profile_id):
    row = db.execute("""
        SELECT profile_id, enabled
        FROM profiles
        WHERE profile_id = ?
    """, (str(profile_id),)).fetchone()

    if row is None:
        raise ValueError(f"Profile not found: {profile_id}")

    if not row["enabled"]:
        raise ValueError(f"Profile is disabled: {profile_id}")

    return row


def _validate_previous_profile(db, previous_profile_id):
    previous_profile_id = str(previous_profile_id)

    _get_enabled_profile(db, previous_profile_id)

    batches = db.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)
                   AS completed
        FROM learning_batches
        WHERE profile_id = ?
    """, (previous_profile_id,)).fetchone()

    if not batches["total"]:
        raise ValueError(
            "Previous profile has no learning batches."
        )

    if batches["total"] != batches["completed"]:
        raise ValueError(
            "Previous profile has unfinished batches."
        )

    unfinished = db.execute("""
        SELECT COUNT(*) AS total
        FROM learning_batch_files
        WHERE profile_id = ?
          AND state NOT IN ('unlocked', 'locked', 'skipped')
    """, (previous_profile_id,)).fetchone()["total"]

    if unfinished:
        raise ValueError(
            "Previous profile still has unfinished PDF files."
        )

    return previous_profile_id


def assign_batches(
    database_path,
    profile_id,
    batch_size=DEFAULT_BATCH_SIZE,
    previous_profile_id=None,
):
    """
    Assign eligible archived PDFs to sequential batches.

    First profile:
        Receives all archived, unowned PDFs not previously assigned
        to that profile.

    Subsequent profile:
        Receives only PDFs marked locked by the completed previous
        profile, excluding PDFs already owned by any profile.

    Existing assignments are never changed.
    """

    batch_size = _validate_batch_size(batch_size)
    initialize_learning_database(database_path)

    profile_id = str(profile_id)
    now = utc_now()

    with connect(database_path) as db:
        _get_enabled_profile(db, profile_id)

        if previous_profile_id is not None:
            previous_profile_id = _validate_previous_profile(
                db, previous_profile_id
            )

            if previous_profile_id == profile_id:
                raise ValueError(
                    "A profile cannot be its own previous profile."
                )

            source_condition = """
                AND EXISTS (
                    SELECT 1
                    FROM learning_batch_files previous_file
                    WHERE previous_file.profile_id = ?
                      AND previous_file.sha256 = d.sha256
                      AND previous_file.state = 'locked'
                )
            """
            parameters = [profile_id, previous_profile_id]
        else:
            source_condition = ""
            parameters = [profile_id]

        candidates = db.execute(f"""
            SELECT d.sha256
            FROM documents d
            JOIN archive_records ar
              ON ar.sha256 = d.sha256
             AND ar.status = 'archived'
            WHERE NOT EXISTS (
                SELECT 1
                FROM document_ownership ownership
                WHERE ownership.sha256 = d.sha256
            )
            AND NOT EXISTS (
                SELECT 1
                FROM learning_batch_files assigned
                WHERE assigned.profile_id = ?
                  AND assigned.sha256 = d.sha256
            )
            {source_condition}
            ORDER BY d.first_seen_at ASC, d.sha256 ASC
        """, parameters).fetchall()

        hashes = [row["sha256"] for row in candidates]

        if not hashes:
            return {
                "profile_id": profile_id,
                "assigned": 0,
                "batches_created": 0,
                "batch_size": batch_size,
                "first_batch": None,
                "last_batch": None,
                "files": [],
            }

        existing = db.execute("""
            SELECT COALESCE(MAX(batch_number), 0)
            FROM learning_batches
            WHERE profile_id = ?
        """, (profile_id,)).fetchone()[0]

        next_batch = existing + 1
        created_batches = 0
        assigned_files = []

        for offset in range(0, len(hashes), batch_size):
            chunk = hashes[offset:offset + batch_size]
            batch_number = next_batch
            next_batch += 1

            db.execute("""
                INSERT INTO learning_batches (
                    profile_id, batch_number, status, created_at
                )
                VALUES (?, ?, 'ready', ?)
            """, (profile_id, batch_number, now))

            created_batches += 1

            for file_order, sha256 in enumerate(chunk, start=1):
                db.execute("""
                    INSERT INTO learning_batch_files (
                        profile_id, sha256, batch_number,
                        file_order, state, assigned_at
                    )
                    VALUES (?, ?, ?, ?, 'pending', ?)
                """, (
                    profile_id,
                    sha256,
                    batch_number,
                    file_order,
                    now,
                ))

                assigned_files.append({
                    "sha256": sha256,
                    "batch_number": batch_number,
                    "file_order": file_order,
                })

        return {
            "profile_id": profile_id,
            "assigned": len(assigned_files),
            "batches_created": created_batches,
            "batch_size": batch_size,
            "first_batch": assigned_files[0]["batch_number"],
            "last_batch": assigned_files[-1]["batch_number"],
            "files": assigned_files,
        }


def update_batch_file_state(
    database_path,
    profile_id,
    sha256,
    state,
):
    """Update one PDF's state and complete its batch when appropriate."""

    allowed = {
        "pending", "processing", "unlocked",
        "locked", "skipped", "failed",
    }

    if state not in allowed:
        raise ValueError(f"Invalid batch file state: {state}")

    initialize_learning_database(database_path)

    now = utc_now()
    profile_id = str(profile_id)

    with connect(database_path) as db:
        row = db.execute("""
            SELECT batch_number, state
            FROM learning_batch_files
            WHERE profile_id = ? AND sha256 = ?
        """, (profile_id, sha256)).fetchone()

        if row is None:
            raise ValueError(
                "PDF is not assigned to this profile."
            )

        db.execute("""
            UPDATE learning_batch_files
            SET state = ?,
                completed_at = ?
            WHERE profile_id = ? AND sha256 = ?
        """, (
            state,
            now if state in TERMINAL_FILE_STATES else None,
            profile_id,
            sha256,
        ))

        batch_number = row["batch_number"]

        states = db.execute("""
            SELECT state
            FROM learning_batch_files
            WHERE profile_id = ? AND batch_number = ?
        """, (profile_id, batch_number)).fetchall()

        all_terminal = all(
            item["state"] in TERMINAL_FILE_STATES
            for item in states
        )

        if all_terminal:
            db.execute("""
                UPDATE learning_batches
                SET status = 'completed',
                    completed_at = COALESCE(completed_at, ?)
                WHERE profile_id = ? AND batch_number = ?
            """, (now, profile_id, batch_number))
        elif state == "processing":
            db.execute("""
                UPDATE learning_batches
                SET status = 'processing',
                    started_at = COALESCE(started_at, ?)
                WHERE profile_id = ? AND batch_number = ?
                  AND status != 'completed'
            """, (now, profile_id, batch_number))
        else:
            db.execute("""
                UPDATE learning_batches
                SET status = 'ready',
                    completed_at = NULL
                WHERE profile_id = ? AND batch_number = ?
                  AND status != 'completed'
            """, (profile_id, batch_number))

    return {
        "profile_id": profile_id,
        "sha256": sha256,
        "batch_number": batch_number,
        "state": state,
        "batch_completed": all_terminal,
    }


def get_batches(database_path, profile_id):
    """Return batch summaries for one profile."""

    initialize_learning_database(database_path)

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT
                b.batch_number,
                b.status,
                b.created_at,
                b.started_at,
                b.completed_at,
                COUNT(f.sha256) AS total_files,
                SUM(CASE WHEN f.state = 'unlocked' THEN 1 ELSE 0 END)
                    AS unlocked,
                SUM(CASE WHEN f.state = 'locked' THEN 1 ELSE 0 END)
                    AS locked,
                SUM(CASE WHEN f.state = 'pending' THEN 1 ELSE 0 END)
                    AS pending,
                SUM(CASE WHEN f.state = 'processing' THEN 1 ELSE 0 END)
                    AS processing,
                SUM(CASE WHEN f.state = 'failed' THEN 1 ELSE 0 END)
                    AS failed
            FROM learning_batches b
            LEFT JOIN learning_batch_files f
              ON f.profile_id = b.profile_id
             AND f.batch_number = b.batch_number
            WHERE b.profile_id = ?
            GROUP BY b.batch_id
            ORDER BY b.batch_number
        """, (str(profile_id),)).fetchall()

    result = []

    for row in rows:
        item = dict(row)
        for key in (
            "unlocked", "locked", "pending",
            "processing", "failed",
        ):
            item[key] = item[key] or 0
        result.append(item)

    return result


def get_batch_files(database_path, profile_id, batch_number):
    """Return files in their stable processing order."""

    initialize_learning_database(database_path)

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT sha256, file_order, state, assigned_at, completed_at
            FROM learning_batch_files
            WHERE profile_id = ? AND batch_number = ?
            ORDER BY file_order
        """, (str(profile_id), batch_number)).fetchall()

    return [dict(row) for row in rows]
