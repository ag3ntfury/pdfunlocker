"""Tests for global shared rule ranking."""

import tempfile
import unittest
from pathlib import Path

import yaml

from pdfunlocker.learning.database import (
    connect,
    initialize_learning_database,
)
from pdfunlocker.learning.ranking import (
    get_completed_rule_statistics,
    get_rule_order,
    get_rule_ranking,
    load_active_rules,
)
from pdfunlocker.profiles.store import create_profile
from pdfunlocker.scanner import utc_now


class LearningRankingTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = self.root / "learning.db"
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()

        initialize_learning_database(self.database)

        self.profile_one = create_profile(self.database, "Rupesh")
        self.profile_two = create_profile(self.database, "Priya")
        self.now = utc_now()

        self.write_rule("00010", "active")
        self.write_rule("00017", "active")
        self.write_rule("00018", "active")
        self.write_rule("00030", "active")
        self.write_rule("00025", "inactive")

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_rule(self, rule_id, status):
        path = self.rules_dir / f"rule{rule_id}.yml"
        data = {
            "rule": {
                "id": rule_id,
                "name": f"Test rule {rule_id}",
                "category": "test",
            },
            "pattern": {"fields": []},
            "transform": {"cases": ["lower", "upper", "raw"]},
            "status": status,
        }
        path.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

    def add_batch(self, profile_id, batch_number, hashes, status="completed"):
        with connect(self.database) as db:
            db.execute("""
                INSERT INTO learning_batches (
                    profile_id, batch_number, status, created_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                profile_id,
                batch_number,
                status,
                self.now,
                self.now if status == "completed" else None,
            ))

            for order, sha in enumerate(hashes, start=1):
                db.execute("""
                    INSERT OR IGNORE INTO documents (
                        sha256, file_size, encryption_status,
                        processing_status, first_seen_at, last_seen_at
                    )
                    VALUES (?, 100, 'encrypted', 'pending', ?, ?)
                """, (sha, self.now, self.now))

                db.execute("""
                    INSERT INTO learning_batch_files (
                        profile_id, sha256, batch_number,
                        file_order, state, assigned_at, completed_at
                    )
                    VALUES (?, ?, ?, ?, 'locked', ?, ?)
                """, (
                    profile_id,
                    sha,
                    batch_number,
                    order,
                    self.now,
                    self.now,
                ))

    def add_run(self, profile_id, batch_number, sha, rule_id, outcome):
        completed_at = (
            self.now if outcome != "running" else None
        )

        with connect(self.database) as db:
            db.execute("""
                INSERT INTO rule_runs (
                    sha256, profile_id, rule_id,
                    rule_fingerprint, candidate_set_fingerprint,
                    batch_number, outcome, attempted_count,
                    started_at, completed_at
                )
                VALUES (?, ?, ?, 'rule-fp', 'candidate-fp',
                        ?, ?, 1, ?, ?)
            """, (
                sha,
                profile_id,
                rule_id,
                batch_number,
                outcome,
                self.now,
                completed_at,
            ))

    def test_active_rules_keep_original_order(self):
        self.assertEqual(
            load_active_rules(self.rules_dir),
            ["00010", "00017", "00018", "00030"],
        )

    def test_first_batch_uses_yaml_order_when_no_global_history(self):
        self.add_batch(self.profile_one, 1, ["a" * 64])

        self.assertEqual(
            get_rule_order(
                self.database, self.rules_dir,
                self.profile_one, 1,
            ),
            ["00010", "00017", "00018", "00030"],
        )

    def test_global_successes_merge_across_profiles(self):
        hashes_one = [f"{n:064x}" for n in range(1, 11)]
        hashes_two = [f"{n:064x}" for n in range(11, 21)]

        self.add_batch(self.profile_one, 1, hashes_one)
        self.add_batch(self.profile_two, 1, hashes_two)

        for sha in hashes_one[:3]:
            self.add_run(self.profile_one, 1, sha, "00010", "success")

        for sha in hashes_one[3:8]:
            self.add_run(self.profile_one, 1, sha, "00017", "success")

        for sha in hashes_one[8:]:
            self.add_run(self.profile_one, 1, sha, "00030", "success")

        for sha in hashes_two[:4]:
            self.add_run(self.profile_two, 1, sha, "00010", "success")

        for sha in hashes_two[4:9]:
            self.add_run(self.profile_two, 1, sha, "00018", "success")

        ranking = get_rule_ranking(self.database, self.rules_dir)

        self.assertEqual(
            [item["rule_id"] for item in ranking],
            ["00010", "00017", "00018", "00030"],
        )

        self.assertEqual(
            [item["successful_files"] for item in ranking],
            [7, 5, 5, 2],
        )

    def test_incomplete_batches_do_not_influence_ranking(self):
        hashes = [f"{n:064x}" for n in range(1, 3)]
        self.add_batch(
            self.profile_one, 1, hashes, status="processing"
        )

        for sha in hashes:
            self.add_run(
                self.profile_one, 1, sha, "00030", "success"
            )

        stats = get_completed_rule_statistics(self.database)

        self.assertNotIn("00030", stats)

    def test_completed_batch_successes_influence_later_batch(self):
        hashes_one = [f"{n:064x}" for n in range(1, 3)]
        hashes_two = [f"{n:064x}" for n in range(3, 5)]

        self.add_batch(self.profile_one, 1, hashes_one)
        self.add_batch(self.profile_one, 2, hashes_two)

        for sha in hashes_one:
            self.add_run(
                self.profile_one, 1, sha, "00018", "success"
            )

        order = get_rule_order(
            self.database, self.rules_dir,
            self.profile_one, 2,
        )

        self.assertEqual(order[0], "00018")

    def test_incomplete_previous_batch_blocks_later_ranking(self):
        self.add_batch(
            self.profile_one, 1, ["a" * 64], status="processing"
        )
        self.add_batch(self.profile_one, 2, ["b" * 64])

        with self.assertRaisesRegex(ValueError, "Earlier batches"):
            get_rule_order(
                self.database, self.rules_dir,
                self.profile_one, 2,
            )

    def test_duplicate_pdf_success_counts_once(self):
        sha = "a" * 64
        self.add_batch(self.profile_one, 1, [sha])
        self.add_batch(self.profile_two, 1, [sha])

        self.add_run(self.profile_one, 1, sha, "00010", "success")
        self.add_run(self.profile_two, 1, sha, "00010", "success")

        stats = get_completed_rule_statistics(self.database)

        self.assertEqual(stats["00010"]["successful_files"], 1)

    def test_inactive_rules_are_excluded(self):
        self.add_batch(self.profile_one, 1, ["e" * 64])
        self.assertNotIn(
            "00025",
            get_rule_order(
                self.database, self.rules_dir,
                self.profile_one, 1,
            ),
        )

    def test_unscored_rules_keep_original_order(self):
        self.add_batch(self.profile_one, 1, ["a" * 64])
        self.add_batch(self.profile_one, 2, ["b" * 64])

        self.add_run(
            self.profile_one, 1, "a" * 64, "00018", "success"
        )

        order = get_rule_order(
            self.database, self.rules_dir,
            self.profile_one, 2,
        )

        self.assertEqual(
            order,
            ["00018", "00010", "00017", "00030"],
        )


    def test_first_batch_uses_global_history_from_another_profile(self):
        sha_previous = "c" * 64
        sha_new = "d" * 64
        self.add_batch(self.profile_one, 1, [sha_previous])
        self.add_run(
            self.profile_one, 1, sha_previous, "00018", "success"
        )
        self.add_batch(self.profile_two, 1, [sha_new])

        self.assertEqual(
            get_rule_order(
                self.database, self.rules_dir,
                self.profile_two, 1,
            )[0],
            "00018",
        )

    def test_error_no_candidates_and_skipped_are_not_attempts(self):
        hashes = [f"{n:064x}" for n in range(1, 4)]
        self.add_batch(self.profile_one, 1, hashes)
        self.add_run(self.profile_one, 1, hashes[0], "00010", "error")
        self.add_run(self.profile_one, 1, hashes[1], "00010", "no_candidates")
        self.add_run(self.profile_one, 1, hashes[2], "00010", "skipped")

        stats = get_completed_rule_statistics(self.database)
        self.assertNotIn("00010", stats)

    def test_success_and_exhausted_are_distinct_pdf_denominator(self):
        hashes = [f"{n:064x}" for n in range(1, 4)]
        self.add_batch(self.profile_one, 1, hashes)
        self.add_run(self.profile_one, 1, hashes[0], "00010", "success")
        self.add_run(self.profile_one, 1, hashes[0], "00010", "exhausted")
        self.add_run(self.profile_one, 1, hashes[1], "00010", "exhausted")
        self.add_run(self.profile_one, 1, hashes[2], "00010", "error")

        stats = get_completed_rule_statistics(self.database)
        self.assertEqual(stats["00010"]["successful_files"], 1)
        self.assertEqual(stats["00010"]["attempted_files"], 2)
        self.assertEqual(stats["00010"]["success_rate"], 0.5)

    def test_batch_one_must_exist(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            get_rule_order(
                self.database, self.rules_dir,
                self.profile_one, 1,
            )

    def test_missing_intermediate_batch_is_rejected(self):
        self.add_batch(self.profile_one, 1, ["a" * 64])
        self.add_batch(self.profile_one, 3, ["b" * 64])
        with self.assertRaisesRegex(ValueError, "missing"):
            get_rule_order(
                self.database, self.rules_dir,
                self.profile_one, 3,
            )

    def test_invalid_batch_number_rejected(self):
        for number in (0, -1, 1.5, True):
            with self.subTest(number=number):
                with self.assertRaises(ValueError):
                    get_rule_order(
                        self.database, self.rules_dir,
                        self.profile_one, number,
                    )


if __name__ == "__main__":
    unittest.main()
