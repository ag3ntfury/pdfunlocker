"""Global rule ranking based on completed learning batches."""

from pathlib import Path

import yaml

from pdfunlocker.learning.database import (
    connect,
    initialize_learning_database,
)


def load_active_rules(rules_directory):
    """Load active rule IDs in their original filename order."""

    directory = Path(rules_directory).expanduser()

    if not directory.is_dir():
        raise FileNotFoundError(
            f"Rules directory not found: {directory}"
        )

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


def get_completed_rule_statistics(database_path):
    """
    Aggregate successful distinct PDFs by rule ID.

    Only runs belonging to completed batches are included.
    Profile IDs are deliberately not used as ranking dimensions.
    """

    initialize_learning_database(database_path)

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT
                rr.rule_id,
                COUNT(DISTINCT CASE
                    WHEN rr.outcome = 'success' THEN rr.sha256
                END) AS successful_files,
                COUNT(DISTINCT rr.sha256) AS processed_files
            FROM rule_runs rr
            JOIN learning_batches lb
              ON lb.profile_id = rr.profile_id
             AND lb.batch_number = rr.batch_number
             AND lb.status = 'completed'
            GROUP BY rr.rule_id
        """).fetchall()

    return {
        row["rule_id"]: {
            "successful_files": row["successful_files"],
            "processed_files": row["processed_files"],
        }
        for row in rows
    }


def get_rule_order(
    database_path,
    rules_directory,
    profile_id,
    batch_number,
):
    """
    Return the rule order for a profile batch.

    Batch 1 always uses original active-rule order.
    Later batches use cumulative successes from all completed
    batches across all profiles, followed by unscored active rules
    in original order.
    """

    if not isinstance(batch_number, int) or isinstance(batch_number, bool):
        raise ValueError("Batch number must be an integer.")

    if batch_number < 1:
        raise ValueError("Batch number must be at least 1.")

    active_rules = load_active_rules(rules_directory)

    if batch_number == 1:
        return active_rules

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
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'completed'
                       THEN 1 ELSE 0 END) AS completed
            FROM learning_batches
            WHERE profile_id = ?
              AND batch_number < ?
        """, (str(profile_id), batch_number)).fetchone()

        if previous["total"] != previous["completed"]:
            raise ValueError(
                "Earlier batches for this profile are not all completed."
            )

    statistics = get_completed_rule_statistics(database_path)

    original_positions = {
        rule_id: index
        for index, rule_id in enumerate(active_rules)
    }

    ranked = sorted(
        active_rules,
        key=lambda rule_id: (
            -statistics.get(rule_id, {}).get("successful_files", 0),
            int(rule_id),
            original_positions[rule_id],
        ),
    )

    return ranked


def get_rule_ranking(database_path, rules_directory):
    """Return global ranking details for active rules."""

    active_rules = load_active_rules(rules_directory)
    statistics = get_completed_rule_statistics(database_path)

    ranked = sorted(
        active_rules,
        key=lambda rule_id: (
            -statistics.get(rule_id, {}).get("successful_files", 0),
            int(rule_id),
        ),
    )

    result = []

    for position, rule_id in enumerate(ranked, start=1):
        stats = statistics.get(rule_id, {})

        result.append({
            "rank": position,
            "rule_id": rule_id,
            "successful_files": stats.get("successful_files", 0),
            "processed_files": stats.get("processed_files", 0),
        })

    return result
