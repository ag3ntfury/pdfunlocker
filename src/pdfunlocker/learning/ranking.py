"""Global staged rule ranking across all PDF Unlocker profiles."""
from pathlib import Path

import yaml

from pdfunlocker.learning.database import (
    connect,
    initialize_learning_database,
)

GLOBAL_RATE_THRESHOLD = 100
COMPLETED_FILE_STATES = ("unlocked", "locked", "skipped", "failed")


def load_active_rules(rules_directory):
    directory = Path(rules_directory).expanduser()
    if not directory.is_dir():
        raise FileNotFoundError(f"Rules directory not found: {directory}")

    rules = []

    for path in sorted(directory.glob("rule*.yml")):
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)

        if not isinstance(data, dict):
            raise ValueError(f"Invalid rule file: {path}")

        rule = data.get("rule")
        if not isinstance(rule, dict):
            raise ValueError(f"Missing rule metadata: {path}")

        rule_id = rule.get("id")
        status = data.get("status")

        if not isinstance(rule_id, str) or not rule_id.isdigit():
            raise ValueError(f"Invalid rule ID: {path}")

        if len(rule_id) != 5:
            raise ValueError(f"Rule ID must contain five digits: {path}")

        if status not in ("active", "inactive"):
            raise ValueError(f"Invalid rule status: {path}")

        if status == "active":
            rules.append(rule_id)

    if len(rules) != len(set(rules)):
        raise ValueError("Duplicate active rule IDs found.")

    return rules


def get_global_completed_pdf_count(database_path):
    """Count unique completed PDFs across every profile."""
    initialize_learning_database(database_path)

    marks = ",".join("?" for _ in COMPLETED_FILE_STATES)

    with connect(database_path) as db:
        row = db.execute(f"""
            SELECT COUNT(DISTINCT f.sha256) AS total
            FROM learning_batch_files f
            JOIN learning_batches b
              ON b.profile_id = f.profile_id
             AND b.batch_number = f.batch_number
            WHERE b.status = 'completed'
              AND f.state IN ({marks})
        """, COMPLETED_FILE_STATES).fetchone()

    return int(row["total"] or 0)


def get_completed_rule_statistics(database_path):
    """
    Count unique PDFs per rule using completed batches only.

    Successful PDFs are counted once per rule. The success-rate
    denominator includes PDFs with success or exhausted outcomes.
    Incomplete batches and non-attempt outcomes are excluded.
    """
    initialize_learning_database(database_path)

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT
                rr.rule_id,
                COUNT(DISTINCT CASE
                    WHEN rr.outcome = 'success'
                    THEN rr.sha256
                END) AS successful_files,
                COUNT(DISTINCT CASE
                    WHEN rr.outcome IN ('success', 'exhausted')
                    THEN rr.sha256
                END) AS attempted_files
            FROM rule_runs rr
            JOIN learning_batches b
              ON b.profile_id = rr.profile_id
             AND b.batch_number = rr.batch_number
            WHERE b.status = 'completed'
            GROUP BY rr.rule_id
        """).fetchall()

    return {
        row["rule_id"]: {
            "successful_files": int(row["successful_files"] or 0),
            "attempted_files": int(row["attempted_files"] or 0),
            "processed_files": int(row["attempted_files"] or 0),
            "success_rate": (
                row["successful_files"] / row["attempted_files"]
                if row["attempted_files"]
                else 0.0
            ),
        }
        for row in rows
    }


def _rank(active_rules, stats, use_rate):
    positions = {
        rule_id: index
        for index, rule_id in enumerate(active_rules)
    }

    tested = [
        rule_id
        for rule_id in active_rules
        if stats.get(rule_id, {}).get("attempted_files", 0) > 0
    ]

    untested = [
        rule_id
        for rule_id in active_rules
        if rule_id not in tested
    ]

    if use_rate:
        tested.sort(
            key=lambda rule_id: (
                -stats[rule_id]["success_rate"],
                -stats[rule_id]["successful_files"],
                positions[rule_id],
            )
        )
    else:
        tested.sort(
            key=lambda rule_id: (
                -stats[rule_id]["successful_files"],
                positions[rule_id],
            )
        )

    return tested + untested


def get_rule_order(database_path, rules_directory, profile_id, batch_number):
    if not isinstance(batch_number, int) or isinstance(batch_number, bool):
        raise ValueError("Batch number must be an integer.")

    if batch_number < 1:
        raise ValueError("Batch number must be at least 1.")

    active = load_active_rules(rules_directory)

    if batch_number == 1:
        return active

    initialize_learning_database(database_path)

    with connect(database_path) as db:
        batch = db.execute("""
            SELECT status
            FROM learning_batches
            WHERE profile_id = ? AND batch_number = ?
        """, (str(profile_id), batch_number)).fetchone()

        if batch is None:
            raise ValueError("Requested batch does not exist.")

        previous = db.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE WHEN status = 'completed'
                    THEN 1 ELSE 0 END
                ) AS completed
            FROM learning_batches
            WHERE profile_id = ? AND batch_number < ?
        """, (str(profile_id), batch_number)).fetchone()

        if previous["total"] != previous["completed"]:
            raise ValueError(
                "Earlier batches for this profile are not all completed."
            )

    total = get_global_completed_pdf_count(database_path)
    stats = get_completed_rule_statistics(database_path)

    return _rank(
        active,
        stats,
        total >= GLOBAL_RATE_THRESHOLD,
    )


def get_rule_ranking(database_path, rules_directory):
    active = load_active_rules(rules_directory)

    total = get_global_completed_pdf_count(database_path)
    use_rate = total >= GLOBAL_RATE_THRESHOLD

    stats = get_completed_rule_statistics(database_path)
    ranked = _rank(active, stats, use_rate)

    return [
        {
            "rank": index,
            "rule_id": rule_id,
            "successful_files": stats.get(
                rule_id, {}
            ).get("successful_files", 0),
            "processed_files": stats.get(
                rule_id, {}
            ).get("attempted_files", 0),
            "attempted_files": stats.get(
                rule_id, {}
            ).get("attempted_files", 0),
            "success_rate": stats.get(
                rule_id, {}
            ).get("success_rate", 0.0),
            "tested": stats.get(
                rule_id, {}
            ).get("attempted_files", 0) > 0,
            "ranking_method": (
                "success_rate" if use_rate else "success_count"
            ),
            "global_completed_pdfs": total,
            "threshold": GLOBAL_RATE_THRESHOLD,
        }
        for index, rule_id in enumerate(ranked, 1)
    ]
