"""Global PDF-level success-rate ranking shared across all profiles."""
from pathlib import Path

import yaml

from pdfunlocker.learning.database import connect, initialize_learning_database


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
        if not isinstance(rule_id, str) or not rule_id.isdigit() or len(rule_id) != 5:
            raise ValueError(f"Invalid rule ID: {path}")
        if status not in ("active", "inactive"):
            raise ValueError(f"Invalid rule status: {path}")
        if status == "active":
            rules.append(rule_id)

    if len(rules) != len(set(rules)):
        raise ValueError("Duplicate active rule IDs found.")
    return rules


def get_completed_rule_statistics(database_path):
    """Return completed-batch PDF-level outcomes, deduplicated per rule."""
    initialize_learning_database(database_path)
    with connect(database_path) as db:
        rows = db.execute("""
            SELECT rr.rule_id,
                COUNT(DISTINCT CASE WHEN rr.outcome = 'success' THEN rr.sha256 END) AS successful_files,
                COUNT(DISTINCT CASE WHEN rr.outcome IN ('success', 'exhausted') THEN rr.sha256 END) AS attempted_files
            FROM rule_runs rr
            JOIN learning_batches b
              ON b.profile_id = rr.profile_id
             AND b.batch_number = rr.batch_number
            WHERE b.status = 'completed'
            GROUP BY rr.rule_id
        """).fetchall()

    stats = {}
    for row in rows:
        successful = int(row["successful_files"] or 0)
        attempted = int(row["attempted_files"] or 0)
        if attempted == 0:
            continue
        stats[row["rule_id"]] = {
            "successful_files": successful,
            "attempted_files": attempted,
            "processed_files": attempted,
            "success_rate": successful / attempted if attempted else 0.0,
        }
    return stats


def _rank(active_rules, stats):
    positions = {rule_id: index for index, rule_id in enumerate(active_rules)}
    tested = [r for r in active_rules if stats.get(r, {}).get("attempted_files", 0) > 0]
    untested = [r for r in active_rules if r not in tested]
    tested.sort(key=lambda r: (
        -stats[r]["success_rate"],
        -stats[r]["successful_files"],
        positions[r],
    ))
    return tested + untested


def get_rule_order(database_path, rules_directory, profile_id, batch_number):
    if not isinstance(batch_number, int) or isinstance(batch_number, bool) or batch_number < 1:
        raise ValueError("Batch number must be an integer of at least 1.")
    active = load_active_rules(rules_directory)
    initialize_learning_database(database_path)

    # Every requested batch must exist. Batch 1 still uses global history
    # from previously completed batches belonging to any profile.
    with connect(database_path) as db:
        batch = db.execute("""
            SELECT status FROM learning_batches
            WHERE profile_id = ? AND batch_number = ?
        """, (str(profile_id), batch_number)).fetchone()
        if batch is None:
            raise ValueError("Requested batch does not exist.")

        previous = db.execute("""
            SELECT batch_number, status
            FROM learning_batches
            WHERE profile_id = ? AND batch_number < ?
            ORDER BY batch_number
        """, (str(profile_id), batch_number)).fetchall()

        expected_numbers = list(range(1, batch_number))
        actual_numbers = [row["batch_number"] for row in previous]
        if actual_numbers != expected_numbers:
            raise ValueError("Earlier batches for this profile are missing.")

        if any(row["status"] != "completed" for row in previous):
            raise ValueError("Earlier batches for this profile are not all completed.")

    # Batch 1 also benefits from prior results learned in other profiles.
    return _rank(active, get_completed_rule_statistics(database_path))


def get_rule_ranking(database_path, rules_directory):
    active = load_active_rules(rules_directory)
    stats = get_completed_rule_statistics(database_path)
    ranked = _rank(active, stats)
    result = []
    for index, rule_id in enumerate(ranked, 1):
        item = stats.get(rule_id, {})
        attempted = item.get("attempted_files", 0)
        result.append({
            "rank": index,
            "rule_id": rule_id,
            "successful_files": item.get("successful_files", 0),
            "processed_files": attempted,
            "attempted_files": attempted,
            "success_rate": item.get("success_rate", 0.0),
            "tested": attempted > 0,
            "ranking_method": "success_rate",
        })
    return result
