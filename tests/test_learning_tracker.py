"""Tests for secure and resumable rule execution tracking."""

import tempfile
import unittest
from pathlib import Path

from pdfunlocker.learning.database import (
    connect,
    initialize_learning_database,
)
from pdfunlocker.learning.tracker import (
    fail_rule_run,
    finish_rule_run,
    get_rule_run,
    record_candidate_attempt,
    start_rule_run,
)
from pdfunlocker.profiles.store import create_profile
from pdfunlocker.scanner import utc_now


class LearningTrackerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "learning.db"
        initialize_learning_database(self.database)

        self.profile = create_profile(self.database, "Rupesh")
        self.sha = "a" * 64
        self.now = utc_now()

        with connect(self.database) as db:
            db.execute("""
                INSERT INTO documents (
                    sha256, file_size, encryption_status,
                    processing_status, first_seen_at, last_seen_at
                )
                VALUES (?, 100, 'encrypted', 'pending', ?, ?)
            """, (self.sha, self.now, self.now))

            db.execute("""
                INSERT INTO learning_batches (
                    profile_id, batch_number, status, created_at
                )
                VALUES (?, 1, 'processing', ?)
            """, (self.profile, self.now))

            db.execute("""
                INSERT INTO learning_batch_files (
                    profile_id, sha256, batch_number,
                    file_order, state, assigned_at
                )
                VALUES (?, ?, 1, 1, 'processing', ?)
            """, (self.profile, self.sha, self.now))

    def tearDown(self):
        self.temp_dir.cleanup()

    def start(self, candidate_set="candidate-set-v1"):
        return start_rule_run(
            self.database,
            self.sha,
            self.profile,
            "00017",
            "rule-fingerprint-v1",
            candidate_set,
            batch_number=1,
        )

    def test_creates_new_run(self):
        result = self.start()

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["outcome"], "running")
        self.assertEqual(result["attempted_candidates"], [])

    def test_resumes_running_run(self):
        created = self.start()

        record_candidate_attempt(
            self.database,
            created["run_id"],
            1,
            "opaque-candidate-1",
            "failed",
        )

        resumed = self.start()

        self.assertEqual(resumed["status"], "resumed")
        self.assertEqual(resumed["run_id"], created["run_id"])
        self.assertEqual(resumed["attempted_candidates"], [1])

    def test_identical_attempt_is_idempotent(self):
        run = self.start()

        first = record_candidate_attempt(
            self.database, run["run_id"], 1,
            "opaque-candidate-1", "failed",
        )
        second = record_candidate_attempt(
            self.database, run["run_id"], 1,
            "opaque-candidate-1", "failed",
        )

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

        details = get_rule_run(self.database, run["run_id"])
        self.assertEqual(len(details["attempts"]), 1)
        self.assertEqual(details["run"]["attempted_count"], 1)

    def test_conflicting_duplicate_candidate_rejected(self):
        run = self.start()

        record_candidate_attempt(
            self.database, run["run_id"], 1,
            "opaque-candidate-1", "failed",
        )

        with self.assertRaisesRegex(ValueError, "different data"):
            record_candidate_attempt(
                self.database, run["run_id"], 1,
                "different-fingerprint", "failed",
            )

    def test_success_completes_run(self):
        run = self.start()

        record_candidate_attempt(
            self.database, run["run_id"], 1,
            "opaque-candidate-1", "success",
        )

        details = get_rule_run(self.database, run["run_id"])
        self.assertEqual(details["run"]["outcome"], "success")
        self.assertIsNotNone(details["run"]["completed_at"])

        resumed = self.start()
        self.assertEqual(resumed["status"], "already_completed")
        self.assertEqual(resumed["outcome"], "success")

    def test_failed_candidates_can_be_marked_exhausted(self):
        run = self.start()

        for number in (1, 2, 3):
            record_candidate_attempt(
                self.database,
                run["run_id"],
                number,
                f"opaque-candidate-{number}",
                "failed",
            )

        result = finish_rule_run(
            self.database, run["run_id"], "exhausted"
        )

        self.assertEqual(result["outcome"], "exhausted")

        resumed = self.start()
        self.assertEqual(resumed["status"], "already_completed")

    def test_no_candidates_run(self):
        run = self.start()

        finish_rule_run(
            self.database, run["run_id"], "no_candidates"
        )

        self.assertEqual(
            get_rule_run(self.database, run["run_id"])
            ["run"]["outcome"],
            "no_candidates",
        )

    def test_engine_error_is_not_exhausted(self):
        run = self.start()

        record_candidate_attempt(
            self.database,
            run["run_id"],
            1,
            "opaque-candidate-1",
            "error",
            error_code="QPDF_ENGINE_ERROR",
        )

        details = get_rule_run(self.database, run["run_id"])

        self.assertEqual(details["run"]["outcome"], "error")
        self.assertEqual(
            details["attempts"][0]["result"], "error"
        )

        retry = self.start()
        self.assertEqual(retry["status"], "created")
        self.assertNotEqual(retry["run_id"], run["run_id"])


    def test_run_level_error_does_not_count_as_candidate_attempt(self):
        run = self.start()

        result = fail_rule_run(
            self.database, run["run_id"], "engine_unexpected_error"
        )

        details = get_rule_run(self.database, run["run_id"])
        self.assertEqual(result["outcome"], "error")
        self.assertFalse(result["duplicate"])
        self.assertEqual(details["run"]["outcome"], "error")
        self.assertEqual(details["run"]["attempted_count"], 0)
        self.assertEqual(details["attempts"], [])
        self.assertIsNotNone(details["run"]["completed_at"])
        self.assertEqual(
            details["run"]["last_error"], "engine_unexpected_error"
        )

        duplicate = fail_rule_run(
            self.database, run["run_id"], "engine_unexpected_error"
        )
        self.assertTrue(duplicate["duplicate"])

        retry = self.start()
        self.assertEqual(retry["status"], "created")
        self.assertNotEqual(retry["run_id"], run["run_id"])

    def test_run_level_error_rejects_completed_run(self):
        run = self.start()
        finish_rule_run(self.database, run["run_id"], "no_candidates")

        with self.assertRaisesRegex(ValueError, "not active"):
            fail_rule_run(
                self.database, run["run_id"], "engine_unexpected_error"
            )


    def test_completed_success_can_start_a_new_recovery_run(self):
        original = self.start()

        record_candidate_attempt(
            self.database,
            original["run_id"],
            1,
            "opaque-candidate-1",
            "success",
        )

        historical = get_rule_run(self.database, original["run_id"])
        self.assertEqual(historical["run"]["outcome"], "success")
        self.assertEqual(historical["run"]["attempted_count"], 1)

        retry = start_rule_run(
            self.database,
            self.sha,
            self.profile,
            "00017",
            "rule-fingerprint-v1",
            "candidate-set-v1",
            batch_number=1,
            retry_completed_success=True,
        )

        self.assertEqual(retry["status"], "created")
        self.assertNotEqual(retry["run_id"], original["run_id"])
        self.assertEqual(retry["attempted_candidates"], [])

        # The original successful history must remain unchanged.
        historical_after = get_rule_run(
            self.database, original["run_id"]
        )
        self.assertEqual(historical_after["run"]["outcome"], "success")
        self.assertEqual(historical_after["run"]["attempted_count"], 1)
        self.assertEqual(len(historical_after["attempts"]), 1)

    def test_retry_completed_success_requires_boolean(self):
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            start_rule_run(
                self.database,
                self.sha,
                self.profile,
                "00017",
                "rule-fingerprint-v1",
                "candidate-set-v1",
                batch_number=1,
                retry_completed_success=1,
            )

    def test_changed_candidate_set_starts_new_run(self):
        first = self.start("candidate-set-v1")

        record_candidate_attempt(
            self.database, first["run_id"], 1,
            "opaque-candidate-1", "failed",
        )

        second = self.start("candidate-set-v2")

        self.assertEqual(second["status"], "created")
        self.assertNotEqual(second["run_id"], first["run_id"])

    def test_other_profile_has_independent_run(self):
        other_profile = create_profile(self.database, "Priya")

        with connect(self.database) as db:
            db.execute("""
                INSERT INTO learning_batches (
                    profile_id, batch_number, status, created_at
                )
                VALUES (?, 1, 'processing', ?)
            """, (other_profile, self.now))

            db.execute("""
                INSERT INTO learning_batch_files (
                    profile_id, sha256, batch_number,
                    file_order, state, assigned_at
                )
                VALUES (?, ?, 1, 1, 'processing', ?)
            """, (other_profile, self.sha, self.now))

        first = self.start()

        second = start_rule_run(
            self.database,
            self.sha,
            other_profile,
            "00017",
            "rule-fingerprint-v1",
            "candidate-set-v1",
            batch_number=1,
        )

        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_batch_assignment_is_required(self):
        with self.assertRaisesRegex(ValueError, "not assigned"):
            start_rule_run(
                self.database,
                self.sha,
                self.profile,
                "00017",
                "rule-fingerprint-v1",
                "candidate-set-v1",
                batch_number=2,
            )

    def test_exhausted_requires_failed_attempts(self):
        run = self.start()

        with self.assertRaisesRegex(ValueError, "without attempts"):
            finish_rule_run(
                self.database, run["run_id"], "exhausted"
            )

        record_candidate_attempt(
            self.database, run["run_id"], 1,
            "opaque-candidate-1", "error",
            error_code="QPDF_ENGINE_ERROR",
        )

        with self.assertRaisesRegex(ValueError, "not active"):
            finish_rule_run(
                self.database, run["run_id"], "exhausted"
            )

    def test_no_candidates_rejects_existing_attempts(self):
        run = self.start()

        record_candidate_attempt(
            self.database, run["run_id"], 1,
            "opaque-candidate-1", "failed",
        )

        with self.assertRaisesRegex(ValueError, "with attempts"):
            finish_rule_run(
                self.database, run["run_id"], "no_candidates"
            )

    def test_invalid_candidate_values_rejected(self):
        run = self.start()

        for number in (0, -1, 1.5, True):
            with self.subTest(number=number):
                with self.assertRaises(ValueError):
                    record_candidate_attempt(
                        self.database, run["run_id"], number,
                        "opaque-candidate", "failed",
                    )

        with self.assertRaises(ValueError):
            record_candidate_attempt(
                self.database, run["run_id"], 1,
                "opaque-candidate", "wrong",
            )

    def test_missing_error_code_rejected(self):
        run = self.start()

        with self.assertRaisesRegex(ValueError, "requires an error_code"):
            record_candidate_attempt(
                self.database, run["run_id"], 1,
                "opaque-candidate", "error",
            )

    def test_plaintext_password_is_not_stored(self):
        run = self.start()

        record_candidate_attempt(
            self.database,
            run["run_id"],
            1,
            "opaque-fingerprint-only",
            "failed",
        )

        with connect(self.database) as db:
            columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(unlock_attempts)"
                )
            }

            self.assertNotIn("password", columns)
            self.assertNotIn("candidate", columns)

            row = db.execute("""
                SELECT *
                FROM unlock_attempts
                WHERE run_id = ?
            """, (run["run_id"],)).fetchone()

            self.assertNotIn(
                "plaintext-password-example",
                tuple(str(value) for value in row),
            )

    def test_unknown_run_returns_none(self):
        self.assertIsNone(get_rule_run(self.database, 9999))


if __name__ == "__main__":
    unittest.main()
