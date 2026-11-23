"""Tests for PDF Unlocker learning batch assignment."""

import tempfile
import unittest
from pathlib import Path

from pdfunlocker.learning.database import (
    connect,
    initialize_learning_database,
)
from pdfunlocker.learning.batch_manager import (
    assign_batches,
    get_batches,
    get_batch_files,
    update_batch_file_state,
)
from pdfunlocker.profiles.store import create_profile
from pdfunlocker.scanner import utc_now


class LearningBatchManagerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "learning.db"

        initialize_learning_database(self.database)

        self.rupesh = create_profile(self.database, "Rupesh")
        self.priya = create_profile(self.database, "Priya")
        self.now = utc_now()

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_archived_documents(self, count):
        hashes = []

        with connect(self.database) as db:
            for number in range(count):
                sha = f"{number + 1:064x}"
                hashes.append(sha)

                db.execute("""
                    INSERT INTO documents (
                        sha256, file_size, encryption_status,
                        processing_status, first_seen_at, last_seen_at
                    )
                    VALUES (?, 100, 'encrypted', 'pending', ?, ?)
                """, (sha, self.now, self.now))

                db.execute("""
                    INSERT INTO archive_records (
                        sha256, archive_path, file_size, status,
                        created_at, updated_at, verified_at
                    )
                    VALUES (?, ?, 100, 'archived', ?, ?, ?)
                """, (
                    sha,
                    f"/original/{sha}.pdf",
                    self.now,
                    self.now,
                    self.now,
                ))

        return hashes

    def complete_profile_one(self, hashes, locked_hashes):
        for sha in hashes:
            state = "locked" if sha in locked_hashes else "unlocked"
            update_batch_file_state(
                self.database, self.rupesh, sha, state
            )

    def test_assigns_ten_files_per_batch(self):
        hashes = self.add_archived_documents(23)

        result = assign_batches(
            self.database, self.rupesh, batch_size=10
        )

        self.assertEqual(result["assigned"], 23)
        self.assertEqual(result["batches_created"], 3)
        self.assertEqual(result["first_batch"], 1)
        self.assertEqual(result["last_batch"], 3)

        batches = get_batches(self.database, self.rupesh)

        self.assertEqual(
            [batch["total_files"] for batch in batches],
            [10, 10, 3],
        )

        self.assertEqual(
            [item["sha256"] for item in
             get_batch_files(self.database, self.rupesh, 1)],
            hashes[:10],
        )

    def test_assignment_is_idempotent(self):
        self.add_archived_documents(12)

        first = assign_batches(self.database, self.rupesh)
        second = assign_batches(self.database, self.rupesh)

        self.assertEqual(first["assigned"], 12)
        self.assertEqual(second["assigned"], 0)
        self.assertEqual(len(get_batches(self.database, self.rupesh)), 2)

    def test_profile_two_requires_previous_completion(self):
        hashes = self.add_archived_documents(12)
        assign_batches(self.database, self.rupesh)

        with self.assertRaisesRegex(ValueError, "unfinished batches"):
            assign_batches(
                self.database,
                self.priya,
                previous_profile_id=self.rupesh,
            )

        for sha in hashes[:10]:
            update_batch_file_state(
                self.database, self.rupesh, sha, "locked"
            )

        for sha in hashes[10:]:
            update_batch_file_state(
                self.database, self.rupesh, sha, "unlocked"
            )

        result = assign_batches(
            self.database,
            self.priya,
            previous_profile_id=self.rupesh,
        )

        self.assertEqual(result["assigned"], 10)
        self.assertEqual(
            {item["sha256"] for item in result["files"]},
            set(hashes[:10]),
        )

    def test_profile_two_never_receives_owned_documents(self):
        hashes = self.add_archived_documents(3)
        assign_batches(self.database, self.rupesh)

        with connect(self.database) as db:
            db.execute("""
                INSERT INTO document_ownership (
                    sha256, owner_profile_id, successful_rule_id,
                    output_sha256, unlocked_at
                )
                VALUES (?, ?, '00017', ?, ?)
            """, (
                hashes[0], self.rupesh, hashes[1], self.now
            ))

        for sha in hashes:
            update_batch_file_state(
                self.database, self.rupesh, sha, "locked"
            )

        result = assign_batches(
            self.database,
            self.priya,
            previous_profile_id=self.rupesh,
        )

        self.assertEqual(result["assigned"], 2)
        self.assertNotIn(
            hashes[0],
            {item["sha256"] for item in result["files"]},
        )

    def test_batch_completes_when_all_files_are_terminal(self):
        hashes = self.add_archived_documents(2)
        assign_batches(
            self.database, self.rupesh, batch_size=2
        )

        first = update_batch_file_state(
            self.database, self.rupesh, hashes[0], "locked"
        )
        self.assertFalse(first["batch_completed"])

        second = update_batch_file_state(
            self.database, self.rupesh, hashes[1], "unlocked"
        )
        self.assertTrue(second["batch_completed"])

        self.assertEqual(
            get_batches(self.database, self.rupesh)[0]["status"],
            "completed",
        )

    def test_failed_file_keeps_batch_incomplete(self):
        hashes = self.add_archived_documents(2)
        assign_batches(
            self.database, self.rupesh, batch_size=2
        )

        update_batch_file_state(
            self.database, self.rupesh, hashes[0], "locked"
        )
        update_batch_file_state(
            self.database, self.rupesh, hashes[1], "failed"
        )

        batch = get_batches(self.database, self.rupesh)[0]

        self.assertNotEqual(batch["status"], "completed")
        self.assertEqual(batch["failed"], 1)

    def test_invalid_batch_size_rejected(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    assign_batches(
                        self.database,
                        self.rupesh,
                        batch_size=value,
                    )

    def test_unknown_profile_rejected(self):
        with self.assertRaisesRegex(ValueError, "Profile not found"):
            assign_batches(self.database, "999")

    def test_disabled_profile_rejected(self):
        with connect(self.database) as db:
            db.execute("""
                UPDATE profiles SET enabled = 0 WHERE profile_id = ?
            """, (self.rupesh,))

        with self.assertRaisesRegex(ValueError, "disabled"):
            assign_batches(self.database, self.rupesh)


if __name__ == "__main__":
    unittest.main()
