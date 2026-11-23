"""Secure, resumable tracking of PDF rule and candidate attempts.

This module never accepts or stores plaintext passwords.
Candidate fingerprints must be opaque, non-reversible identifiers
created by the candidate-generation layer.
"""

from pdfunlocker.learning.database import (
    connect,
    initialize_learning_database,
)
from pdfunlocker.scanner import utc_now


VALID_RESULTS = {"failed", "success", "error"}
TERMINAL_OUTCOMES = {
    "success", "exhausted", "no_candidates", "error", "skipped",
}


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _positive_integer(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def start_rule_run(
    database_path,
    sha256,
    profile_id,
    rule_id,
    rule_fingerprint,
    candidate_set_fingerprint,
    batch_number=None,
):
    """
    Start or resume a rule run.

    A matching running run resumes.
    A matching successful, exhausted, no-candidate, or skipped run
    is returned as already completed.
    An engine-error run does not block a fresh retry.
    """

    sha256 = _required_text(sha256, "sha256")
    profile_id = _required_text(str(profile_id), "profile_id")
    rule_id = _required_text(rule_id, "rule_id")
    rule_fingerprint = _required_text(
        rule_fingerprint, "rule_fingerprint"
    )
    candidate_set_fingerprint = _required_text(
        candidate_set_fingerprint, "candidate_set_fingerprint"
    )

    if batch_number is not None:
        _positive_integer(batch_number, "batch_number")

    initialize_learning_database(database_path)
    now = utc_now()

    with connect(database_path) as db:
        if batch_number is not None:
            assignment = db.execute("""
                SELECT state
                FROM learning_batch_files
                WHERE profile_id = ?
                  AND sha256 = ?
                  AND batch_number = ?
            """, (profile_id, sha256, batch_number)).fetchone()

            if assignment is None:
                raise ValueError(
                    "PDF is not assigned to this profile and batch."
                )

        existing = db.execute("""
            SELECT *
            FROM rule_runs
            WHERE sha256 = ?
              AND profile_id = ?
              AND rule_id = ?
              AND rule_fingerprint = ?
              AND candidate_set_fingerprint = ?
              AND batch_number IS ?
            ORDER BY run_id DESC
            LIMIT 1
        """, (
            sha256,
            profile_id,
            rule_id,
            rule_fingerprint,
            candidate_set_fingerprint,
            batch_number,
        )).fetchone()

        if existing is not None:
            run_id = existing["run_id"]
            outcome = existing["outcome"]

            attempted = db.execute("""
                SELECT candidate_number
                FROM unlock_attempts
                WHERE run_id = ?
                ORDER BY candidate_number
            """, (run_id,)).fetchall()

            attempted_numbers = [
                row["candidate_number"] for row in attempted
            ]

            if outcome == "running":
                return {
                    "run_id": run_id,
                    "status": "resumed",
                    "outcome": outcome,
                    "attempted_candidates": attempted_numbers,
                }

            if outcome in TERMINAL_OUTCOMES - {"error"}:
                return {
                    "run_id": run_id,
                    "status": "already_completed",
                    "outcome": outcome,
                    "attempted_candidates": attempted_numbers,
                }

        cursor = db.execute("""
            INSERT INTO rule_runs (
                sha256,
                profile_id,
                rule_id,
                rule_fingerprint,
                candidate_set_fingerprint,
                batch_number,
                outcome,
                attempted_count,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'running', 0, ?)
        """, (
            sha256,
            profile_id,
            rule_id,
            rule_fingerprint,
            candidate_set_fingerprint,
            batch_number,
            now,
        ))

        return {
            "run_id": cursor.lastrowid,
            "status": "created",
            "outcome": "running",
            "attempted_candidates": [],
        }


def record_candidate_attempt(
    database_path,
    run_id,
    candidate_number,
    candidate_fingerprint,
    result,
    error_code=None,
):
    """
    Record one candidate attempt without storing its password.

    Repeating an identical recorded attempt is idempotent.
    A success completes the rule run.
    An engine error completes the run with outcome 'error',
    not 'exhausted'.
    """

    _positive_integer(run_id, "run_id")
    _positive_integer(candidate_number, "candidate_number")
    candidate_fingerprint = _required_text(
        candidate_fingerprint, "candidate_fingerprint"
    )

    if result not in VALID_RESULTS:
        raise ValueError(f"Invalid attempt result: {result}")

    if error_code is not None:
        error_code = _required_text(error_code, "error_code")
        if len(error_code) > 100:
            raise ValueError("error_code must not exceed 100 characters.")

    if result == "error" and error_code is None:
        raise ValueError("An engine error requires an error_code.")

    initialize_learning_database(database_path)
    now = utc_now()

    with connect(database_path) as db:
        run = db.execute("""
            SELECT outcome
            FROM rule_runs
            WHERE run_id = ?
        """, (run_id,)).fetchone()

        if run is None:
            raise ValueError(f"Rule run not found: {run_id}")

        if run["outcome"] != "running":
            raise ValueError(
                f"Rule run is not active: {run['outcome']}"
            )

        previous = db.execute("""
            SELECT candidate_fingerprint, result, error_code
            FROM unlock_attempts
            WHERE run_id = ? AND candidate_number = ?
        """, (run_id, candidate_number)).fetchone()

        if previous is not None:
            if (
                previous["candidate_fingerprint"] == candidate_fingerprint
                and previous["result"] == result
                and previous["error_code"] == error_code
            ):
                return {
                    "run_id": run_id,
                    "candidate_number": candidate_number,
                    "result": result,
                    "duplicate": True,
                }

            raise ValueError(
                "Candidate number already exists with different data."
            )

        db.execute("""
            INSERT INTO unlock_attempts (
                run_id,
                candidate_number,
                candidate_fingerprint,
                result,
                attempted_at,
                error_code
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            candidate_number,
            candidate_fingerprint,
            result,
            now,
            error_code,
        ))

        db.execute("""
            UPDATE rule_runs
            SET attempted_count = attempted_count + 1
            WHERE run_id = ?
        """, (run_id,))

        if result in {"success", "error"}:
            db.execute("""
                UPDATE rule_runs
                SET outcome = ?,
                    completed_at = ?,
                    last_error = ?
                WHERE run_id = ?
            """, (
                result,
                now,
                error_code,
                run_id,
            ))

        return {
            "run_id": run_id,
            "candidate_number": candidate_number,
            "result": result,
            "duplicate": False,
        }


def finish_rule_run(database_path, run_id, outcome):
    """Finish a run as exhausted, no_candidates, or skipped."""

    _positive_integer(run_id, "run_id")

    if outcome not in {"exhausted", "no_candidates", "skipped"}:
        raise ValueError(f"Invalid final outcome: {outcome}")

    initialize_learning_database(database_path)
    now = utc_now()

    with connect(database_path) as db:
        run = db.execute("""
            SELECT outcome, attempted_count
            FROM rule_runs
            WHERE run_id = ?
        """, (run_id,)).fetchone()

        if run is None:
            raise ValueError(f"Rule run not found: {run_id}")

        if run["outcome"] != "running":
            raise ValueError(
                f"Rule run is not active: {run['outcome']}"
            )

        if outcome == "exhausted" and run["attempted_count"] < 1:
            raise ValueError(
                "Cannot mark a run exhausted without attempts."
            )

        if outcome == "no_candidates" and run["attempted_count"] != 0:
            raise ValueError(
                "A run with attempts cannot be marked no_candidates."
            )

        if outcome == "exhausted":
            errors = db.execute("""
                SELECT COUNT(*) AS total
                FROM unlock_attempts
                WHERE run_id = ? AND result != 'failed'
            """, (run_id,)).fetchone()["total"]

            if errors:
                raise ValueError(
                    "Exhausted runs may contain only failed attempts."
                )

        db.execute("""
            UPDATE rule_runs
            SET outcome = ?,
                completed_at = ?
            WHERE run_id = ?
        """, (outcome, now, run_id))

    return {
        "run_id": run_id,
        "outcome": outcome,
    }


def get_rule_run(database_path, run_id):
    """Return run metadata and candidate attempt history."""

    _positive_integer(run_id, "run_id")
    initialize_learning_database(database_path)

    with connect(database_path) as db:
        run = db.execute("""
            SELECT
                run_id, sha256, profile_id, rule_id,
                rule_fingerprint, candidate_set_fingerprint,
                batch_number, outcome, attempted_count,
                started_at, completed_at, last_error
            FROM rule_runs
            WHERE run_id = ?
        """, (run_id,)).fetchone()

        if run is None:
            return None

        attempts = db.execute("""
            SELECT
                candidate_number,
                candidate_fingerprint,
                result,
                attempted_at,
                error_code
            FROM unlock_attempts
            WHERE run_id = ?
            ORDER BY candidate_number
        """, (run_id,)).fetchall()

    return {
        "run": dict(run),
        "attempts": [dict(row) for row in attempts],
    }
