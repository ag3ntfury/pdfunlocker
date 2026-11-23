"""Tests for the PDF Unlocker learning database."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from pdfunlocker.learning.database import (
    connect,
    get_learning_status,
    get_rule_statistics,
    initialize_learning_database,
)
from pdfunlocker.profiles.store import create_profile
from pdfunlocker.scanner import utc_now


class LearningDatabaseTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "learning.db"

        initialize_learning_database(self.database)

        self.profile_one = create_profile(self.database, "Test One")
        self.profile_two = create_profile(self.database, "Test Two")

        self.now = utc_now()

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_document(self, sha):
        with connect(self.database) as db:
            db.execute("""
                INSERT INTO documents (
                    sha256, file_size, encryption_status,
                    processing_status, first_seen_at, last_seen_at
                )
                VALUES (?, 100, 'encrypted', 'pending', ?, ?)
            """, (sha, self.now, self.now))

    def add_rule_run(
        self, sha, profile_id, rule_id, outcome,
        attempted_count=1
    ):
        with connect(self.database) as db:
            db.execute("""
                INSERT INTO rule_runs (
                    sha256, profile_id, rule_id,
                    rule_fingerprint, candidate_set_fingerprint,
                    outcome, attempted_count, started_at, completed_at
                )
                VALUES (?, ?, ?, 'rule-hash', 'candidate-hash',
                        ?, ?, ?, ?)
            """, (
                sha, profile_id, rule_id, outcome,
                attempted_count, self.now, self.now
            ))

    def test_all_learning_tables_created(self):
        expected = {
            "learning_batches",
            "learning_batch_files",
            "document_ownership",
            "rule_runs",
            "unlock_attempts",
        }

        with connect(self.database) as db:
            actual = {
                row["name"]
                for row in db.execute("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                """)
            }

        self.assertTrue(expected.issubset(actual))

    def test_initialization_is_idempotent(self):
        initialize_learning_database(self.database)
        initialize_learning_database(self.database)

        with connect(self.database) as db:
            row = db.execute("""
                SELECT value
                FROM app_metadata
                WHERE key = 'learning_schema_version'
            """).fetchone()

        self.assertEqual(row["value"], "1")

    def test_shared_statistics_merge_profiles(self):
        self.add_document("a" * 64)
        self.add_document("b" * 64)
        self.add_document("c" * 64)

        self.add_rule_run(
            "a" * 64, self.profile_one, "00017", "success", 4
        )
        self.add_rule_run(
            "b" * 64, self.profile_one, "00017", "success", 3
        )
        self.add_rule_run(
            "c" * 64, self.profile_two, "00017", "exhausted", 5
        )
        self.add_rule_run(
            "c" * 64, self.profile_two, "00010", "success", 2
        )

        stats = get_rule_statistics(self.database)

        self.assertEqual(stats[0]["rule_id"], "00017")
        self.assertEqual(stats[0]["successful_files"], 2)
        self.assertEqual(stats[0]["completed_files"], 3)
        self.assertEqual(stats[0]["candidate_attempts"], 12)

        self.assertEqual(stats[1]["rule_id"], "00010")
        self.assertEqual(stats[1]["successful_files"], 1)

    def test_same_pdf_counts_once_per_rule(self):
        self.add_document("d" * 64)

        self.add_rule_run(
            "d" * 64, self.profile_one, "00017", "success"
        )
        self.add_rule_run(
            "d" * 64, self.profile_two, "00017", "success"
        )

        stats = get_rule_statistics(self.database)

        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["successful_files"], 1)

    def test_document_has_single_owner(self):
        self.add_document("e" * 64)

        with connect(self.database) as db:
            db.execute("""
                INSERT INTO document_ownership (
                    sha256, owner_profile_id, successful_rule_id,
                    output_sha256, unlocked_at
                )
                VALUES (?, ?, '00017', ?, ?)
            """, (
                "e" * 64, self.profile_one, "f" * 64, self.now
            ))

            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""
                    INSERT INTO document_ownership (
                        sha256, owner_profile_id, successful_rule_id,
                        output_sha256, unlocked_at
                    )
                    VALUES (?, ?, '00010', ?, ?)
                """, (
                    "e" * 64, self.profile_two, "f" * 64, self.now
                ))

    def test_attempt_table_does_not_store_passwords(self):
        with connect(self.database) as db:
            columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(unlock_attempts)"
                )
            }

        self.assertNotIn("password", columns)
        self.assertIn("candidate_fingerprint", columns)
        self.assertIn("candidate_number", columns)

    def test_learning_status_empty_database(self):
        status = get_learning_status(self.database)

        self.assertEqual(status["batches"], [])
        self.assertEqual(status["ownership"], [])
        self.assertEqual(status["attempts"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
