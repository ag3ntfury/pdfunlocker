import hashlib
import tempfile
import unittest
from pathlib import Path

from pdfunlocker.profiles.store import initialize_database
from pdfunlocker.scanner import scan
from pdfunlocker.archive import archive_documents
from pdfunlocker.inbox import (
    initialize_inbox_database,
    prepare_inbox,
    record_unlock_result,
    get_workflow_status,
    cleanup_inbox_item,
    connect,
)


class InboxManagerTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "database" / "test.db"
        self.source = self.root / "source"
        self.storage = self.root / "PDFUnlocker"
        self.original = self.storage / "Original"
        self.source.mkdir()

        initialize_database(self.database)
        initialize_inbox_database(self.database)

        self.settings = {
            "scan": {
                "locations": [str(self.source)],
                "recursive": True,
                "follow_symlinks": False,
                "exclude_paths": [],
                "file_extensions": [".pdf"],
            }
        }

    def tearDown(self):
        self.temp.cleanup()

    def add_pdf(self, name, content):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def archive_sources(self):
        scan(self.database, self.settings)
        return archive_documents(self.database, self.original)

    def mark_locked(self, digest, locked):
        with connect(self.database) as db:
            now = "2026-01-01T00:00:00+00:00"
            db.execute("""
                INSERT INTO workflow_documents (
                    sha256, state, current_path, created_at, updated_at
                )
                SELECT sha256, 'locked', ?, ?, ?
                FROM documents WHERE sha256 = ?
            """, (str(locked), now, now, digest))

    def test_normal_run_prepares_one_copy_for_unique_document(self):
        content = b"same PDF content"
        self.add_pdf("one.pdf", content)
        self.add_pdf("two.pdf", content)
        self.archive_sources()

        result = prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        self.assertEqual(result["prepared"], 1)
        self.assertTrue((self.storage / "Inbox" / f"{digest}.pdf").is_file())
        self.assertEqual(len(list((self.storage / "Inbox").glob("*.pdf"))), 1)

    def test_normal_run_does_not_repeat_completed_documents(self):
        content = b"document"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        record_unlock_result(
            self.database, self.storage, digest, "already_unlocked"
        )

        result = prepare_inbox(self.database, self.storage)
        self.assertEqual(result["prepared"], 0)
        self.assertEqual(result["found"], 0)

    def test_force_prepares_previously_processed_document(self):
        content = b"force document"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        record_unlock_result(
            self.database, self.storage, digest, "already_unlocked"
        )

        result = prepare_inbox(self.database, self.storage, mode="force")
        self.assertEqual(result["prepared"], 1)

    def test_archive_original_is_not_modified(self):
        content = b"immutable original"
        self.add_pdf("one.pdf", content)
        self.archive_sources()

        digest = hashlib.sha256(content).hexdigest()
        original = self.original / f"{digest}.pdf"
        before = original.read_bytes()

        prepare_inbox(self.database, self.storage)

        self.assertEqual(original.read_bytes(), before)

    def test_wrong_inbox_destination_is_conflict(self):
        content = b"correct content"
        self.add_pdf("one.pdf", content)
        self.archive_sources()

        inbox = self.storage / "Inbox"
        inbox.mkdir(parents=True)
        digest = hashlib.sha256(content).hexdigest()
        destination = inbox / f"{digest}.pdf"
        destination.write_bytes(b"wrong content")

        result = prepare_inbox(self.database, self.storage)

        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(destination.read_bytes(), b"wrong content")

    def test_retry_prepares_locked_file(self):
        content = b"locked PDF"
        self.add_pdf("one.pdf", content)
        self.archive_sources()

        digest = hashlib.sha256(content).hexdigest()
        locked = self.storage / "Locked" / f"{digest}.pdf"
        locked.parent.mkdir(parents=True)
        locked.write_bytes(content)
        self.mark_locked(digest, locked)

        result = prepare_inbox(self.database, self.storage, mode="retry")

        self.assertEqual(result["prepared"], 1)
        self.assertTrue((self.storage / "Inbox" / f"{digest}.pdf").is_file())
        self.assertTrue(locked.is_file())

    def test_successful_unlock_output_is_published_and_verified(self):
        encrypted = b"encrypted original"
        unlocked = b"unlocked output"
        self.add_pdf("one.pdf", encrypted)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(encrypted).hexdigest()
        output = self.root / "unlocked-output.pdf"
        output.write_bytes(unlocked)

        result = record_unlock_result(
            self.database,
            self.storage,
            digest,
            "unlocked",
            unlocked_output=output,
        )

        destination = self.storage / "Unlocked" / f"{digest}.pdf"
        self.assertEqual(result["status"], "unlocked")
        self.assertEqual(destination.read_bytes(), unlocked)

    def test_already_unlocked_is_routed_to_unlocked(self):
        content = b"already unlocked"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        result = record_unlock_result(
            self.database, self.storage, digest, "already_unlocked"
        )

        destination = self.storage / "Unlocked" / f"{digest}.pdf"
        self.assertEqual(result["status"], "already_unlocked")
        self.assertEqual(destination.read_bytes(), content)

    def test_failed_unlock_keeps_inbox_copy(self):
        content = b"encrypted"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        result = record_unlock_result(
            self.database, self.storage, digest, "error"
        )

        self.assertTrue(result["inbox_preserved"])
        self.assertTrue((self.storage / "Inbox" / f"{digest}.pdf").is_file())

    def test_original_and_locked_are_not_deleted_during_retry(self):
        content = b"locked retry"
        self.add_pdf("one.pdf", content)
        self.archive_sources()

        digest = hashlib.sha256(content).hexdigest()
        locked = self.storage / "Locked" / f"{digest}.pdf"
        locked.parent.mkdir(parents=True)
        locked.write_bytes(content)
        self.mark_locked(digest, locked)

        prepare_inbox(self.database, self.storage, mode="retry")

        self.assertTrue(locked.is_file())
        self.assertTrue((self.original / f"{digest}.pdf").is_file())

    def test_workflow_status(self):
        content = b"status test"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        status = get_workflow_status(self.database)
        self.assertEqual(status["inbox"], 1)


    def test_cleanup_successful_unlock_removes_inbox_copy(self):
        content = b"cleanup unlocked document"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        output = self.root / "unlocked-output.pdf"
        output.write_bytes(b"verified unlocked output")

        record_unlock_result(
            self.database, self.storage, digest,
            "unlocked", unlocked_output=output
        )

        original = self.original / f"{digest}.pdf"
        original_before = original.read_bytes()

        result = cleanup_inbox_item(
            self.database, self.storage, digest
        )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["inbox_removed"])
        self.assertFalse((self.storage / "Inbox" / f"{digest}.pdf").exists())
        self.assertTrue((self.storage / "Unlocked" / f"{digest}.pdf").is_file())
        self.assertEqual(original.read_bytes(), original_before)

        with connect(self.database) as db:
            job = db.execute(
                "SELECT status FROM inbox_jobs ORDER BY job_id DESC LIMIT 1"
            ).fetchone()

        self.assertEqual(job["status"], "completed")

    def test_cleanup_locked_result_keeps_locked_copy(self):
        content = b"cleanup locked document"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()

        record_unlock_result(
            self.database, self.storage, digest, "locked"
        )

        result = cleanup_inbox_item(
            self.database, self.storage, digest
        )

        self.assertEqual(result["state"], "locked")
        self.assertTrue(result["inbox_removed"])
        self.assertFalse((self.storage / "Inbox" / f"{digest}.pdf").exists())
        self.assertEqual(
            (self.storage / "Locked" / f"{digest}.pdf").read_bytes(),
            content,
        )

    def test_cleanup_successful_retry_removes_old_locked_copy(self):
        content = b"cleanup retry document"
        self.add_pdf("one.pdf", content)
        self.archive_sources()

        digest = hashlib.sha256(content).hexdigest()
        locked = self.storage / "Locked" / f"{digest}.pdf"
        locked.parent.mkdir(parents=True)
        locked.write_bytes(content)
        self.mark_locked(digest, locked)

        prepare_inbox(self.database, self.storage, mode="retry")

        output = self.root / "retry-unlocked.pdf"
        output.write_bytes(b"successfully unlocked retry")

        record_unlock_result(
            self.database,
            self.storage,
            digest,
            "unlocked",
            unlocked_output=output,
            retry=True,
        )

        self.assertTrue(locked.is_file())

        result = cleanup_inbox_item(
            self.database, self.storage, digest
        )

        self.assertEqual(result["state"], "unlocked")
        self.assertTrue(result["inbox_removed"])
        self.assertTrue(result["locked_removed"])
        self.assertFalse(locked.exists())
        self.assertFalse((self.storage / "Inbox" / f"{digest}.pdf").exists())
        self.assertTrue(
            (self.storage / "Unlocked" / f"{digest}.pdf").is_file()
        )
        self.assertTrue(
            (self.original / f"{digest}.pdf").is_file()
        )

    def test_cleanup_locked_retry_keeps_locked_copy(self):
        content = b"still locked after retry"
        self.add_pdf("one.pdf", content)
        self.archive_sources()

        digest = hashlib.sha256(content).hexdigest()
        locked = self.storage / "Locked" / f"{digest}.pdf"
        locked.parent.mkdir(parents=True)
        locked.write_bytes(content)
        self.mark_locked(digest, locked)

        prepare_inbox(self.database, self.storage, mode="retry")

        record_unlock_result(
            self.database, self.storage, digest, "locked", retry=True
        )

        result = cleanup_inbox_item(
            self.database, self.storage, digest
        )

        self.assertEqual(result["state"], "locked")
        self.assertTrue(locked.is_file())
        self.assertFalse((self.storage / "Inbox" / f"{digest}.pdf").exists())

    def test_cleanup_refuses_modified_result_and_preserves_inbox(self):
        content = b"cleanup tamper test"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        record_unlock_result(
            self.database, self.storage, digest, "already_unlocked"
        )

        destination = self.storage / "Unlocked" / f"{digest}.pdf"
        destination.write_bytes(b"tampered result")

        inbox_file = self.storage / "Inbox" / f"{digest}.pdf"

        with self.assertRaises(RuntimeError):
            cleanup_inbox_item(self.database, self.storage, digest)

        self.assertTrue(inbox_file.is_file())

    def test_cleanup_preserves_inbox_after_unlock_error(self):
        content = b"cleanup error test"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        record_unlock_result(
            self.database, self.storage, digest, "error"
        )

        inbox_file = self.storage / "Inbox" / f"{digest}.pdf"

        with self.assertRaises(RuntimeError):
            cleanup_inbox_item(self.database, self.storage, digest)

        self.assertTrue(inbox_file.is_file())

    def test_cleanup_is_idempotent(self):
        content = b"cleanup idempotency test"
        self.add_pdf("one.pdf", content)
        self.archive_sources()
        prepare_inbox(self.database, self.storage)

        digest = hashlib.sha256(content).hexdigest()
        record_unlock_result(
            self.database, self.storage, digest, "already_unlocked"
        )

        first = cleanup_inbox_item(
            self.database, self.storage, digest
        )
        second = cleanup_inbox_item(
            self.database, self.storage, digest
        )

        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "already_completed")



if __name__ == "__main__":
    unittest.main(verbosity=2)
