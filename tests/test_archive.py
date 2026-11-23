import errno
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.profiles.store import initialize_database
from pdfunlocker.scanner import scan
from pdfunlocker.archive import (
    archive_documents,
    get_archive_status,
    archive_filename,
    connect,
)


class ArchiveTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "database" / "test.db"
        self.source = self.root / "source"
        self.original = self.root / "PDFUnlocker" / "Original"
        self.source.mkdir()

        initialize_database(self.database)

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

    def create_pdf(self, name, content):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def scan_sources(self):
        return scan(self.database, self.settings)

    def test_archive_uses_full_sha256_filename(self):
        content = b"%PDF-1.4\nArchive test\n"
        self.create_pdf("bank.pdf", content)
        self.scan_sources()

        result = archive_documents(self.database, self.original)

        expected_hash = hashlib.sha256(content).hexdigest()
        expected_path = self.original / f"{expected_hash}.pdf"

        self.assertEqual(result["archived"], 1)
        self.assertEqual(result["copied"], 1)
        self.assertTrue(expected_path.is_file())
        self.assertEqual(expected_path.read_bytes(), content)

    def test_duplicate_sources_create_only_one_archive_file(self):
        content = b"identical document"
        self.create_pdf("one.pdf", content)
        self.create_pdf("two.pdf", content)
        self.scan_sources()

        result = archive_documents(self.database, self.original)

        self.assertEqual(result["documents_found"], 1)
        self.assertEqual(result["archived"], 1)
        self.assertEqual(result["copied"], 1)
        self.assertEqual(len(list(self.original.glob("*.pdf"))), 1)

        status = get_archive_status(self.database)
        self.assertEqual(status["archived"], 1)

    def test_source_file_is_never_modified(self):
        content = b"original source content"
        source = self.create_pdf("source.pdf", content)
        before = source.read_bytes()
        self.scan_sources()

        archive_documents(self.database, self.original)

        self.assertEqual(source.read_bytes(), before)

    def test_existing_verified_archive_is_reused(self):
        content = b"existing archive content"
        self.create_pdf("existing.pdf", content)
        self.scan_sources()

        digest = hashlib.sha256(content).hexdigest()
        self.original.mkdir(parents=True)
        existing = self.original / f"{digest}.pdf"
        existing.write_bytes(content)

        result = archive_documents(self.database, self.original)

        self.assertEqual(result["archived"], 1)
        self.assertEqual(result["reused"], 1)
        self.assertEqual(result["copied"], 0)

    def test_wrong_existing_archive_is_not_overwritten(self):
        content = b"correct source"
        self.create_pdf("source.pdf", content)
        self.scan_sources()

        digest = hashlib.sha256(content).hexdigest()
        self.original.mkdir(parents=True)
        destination = self.original / f"{digest}.pdf"
        destination.write_bytes(b"wrong existing data")

        result = archive_documents(self.database, self.original)

        self.assertEqual(result["failed"], 1)
        self.assertEqual(destination.read_bytes(), b"wrong existing data")

        status = get_archive_status(self.database)
        self.assertEqual(status["failed"], 1)

    def test_archive_filename_rejects_invalid_hash(self):
        with self.assertRaises(ValueError):
            archive_filename("not-a-hash")

    def test_archive_records_all_duplicate_source_paths(self):
        content = b"same file content"
        first = self.create_pdf("first.pdf", content)
        second = self.create_pdf("second.pdf", content)
        self.scan_sources()

        archive_documents(self.database, self.original)

        digest = hashlib.sha256(content).hexdigest()

        with connect(self.database) as db:
            paths = {
                row["source_path"]
                for row in db.execute("""
                    SELECT source_path
                    FROM archive_sources
                    WHERE sha256 = ?
                """, (digest,)).fetchall()
            }

        self.assertEqual(
            paths,
            {str(first.resolve()), str(second.resolve())},
        )

    def test_archive_preserves_old_and_new_paths_after_move(self):
        content = b"document that will move"
        old_path = self.create_pdf("old-name.pdf", content)
        self.scan_sources()

        new_path = self.source / "new-name.pdf"
        old_path.rename(new_path)
        self.scan_sources()

        result = archive_documents(self.database, self.original)
        digest = hashlib.sha256(content).hexdigest()

        with connect(self.database) as db:
            paths = {
                row["source_path"]
                for row in db.execute("""
                    SELECT source_path
                    FROM archive_sources
                    WHERE sha256 = ?
                """, (digest,)).fetchall()
            }

        self.assertEqual(result["archived"], 1)
        self.assertEqual(
            paths,
            {str(old_path.resolve()), str(new_path.resolve())},
        )

    def test_filename_containing_newline_is_archived(self):
        content = b"newline filename document"
        source = self.create_pdf("line\nbreak.pdf", content)
        self.scan_sources()

        result = archive_documents(self.database, self.original)
        digest = hashlib.sha256(content).hexdigest()

        with connect(self.database) as db:
            paths = {
                row["source_path"]
                for row in db.execute("""
                    SELECT source_path
                    FROM archive_sources
                    WHERE sha256 = ?
                """, (digest,)).fetchall()
            }

        self.assertEqual(result["archived"], 1)
        self.assertEqual(paths, {str(source.resolve())})
        self.assertTrue((self.original / f"{digest}.pdf").is_file())

    def test_interrupted_fallback_copy_is_not_marked_archived(self):
        content = b"interrupted archive content"
        self.create_pdf("interrupted.pdf", content)
        self.scan_sources()

        digest = hashlib.sha256(content).hexdigest()
        destination = self.original / f"{digest}.pdf"

        def simulate_interrupted_copy(temporary, target):
            target.write_bytes(b"partial copy")
            raise OSError("Simulated interruption during fallback copy")

        with patch(
            "pdfunlocker.archive.os.link",
            side_effect=OSError(errno.EXDEV, "cross-device link"),
            create=True,
        ), patch(
            "pdfunlocker.archive._copy_exclusive",
            side_effect=simulate_interrupted_copy,
        ):
            result = archive_documents(self.database, self.original)

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["archived"], 0)
        self.assertTrue(destination.is_file())
        self.assertNotEqual(destination.read_bytes(), content)

        status = get_archive_status(self.database)
        self.assertEqual(status["archived"], 0)
        self.assertEqual(status["failed"], 1)

        # A retry must not mistake the partial destination for a valid archive.
        retry = archive_documents(self.database, self.original)
        self.assertEqual(retry["failed"], 1)
        self.assertEqual(retry["archived"], 0)



    def test_second_normal_run_skips_verified_archive_without_changing_record(self):
        content = b"incremental archive test"
        self.create_pdf("incremental.pdf", content)
        self.scan_sources()

        first = archive_documents(self.database, self.original)
        self.assertEqual(first["copied"], 1)

        digest = hashlib.sha256(content).hexdigest()

        with connect(self.database) as db:
            before = dict(db.execute("""
                SELECT status, updated_at, verified_at
                FROM archive_records WHERE sha256 = ?
            """, (digest,)).fetchone())

            event_count_before = db.execute("""
                SELECT COUNT(*) FROM archive_events
                WHERE sha256 = ?
            """, (digest,)).fetchone()[0]

        second = archive_documents(self.database, self.original)

        with connect(self.database) as db:
            after = dict(db.execute("""
                SELECT status, updated_at, verified_at
                FROM archive_records WHERE sha256 = ?
            """, (digest,)).fetchone())

            event_count_after = db.execute("""
                SELECT COUNT(*) FROM archive_events
                WHERE sha256 = ?
            """, (digest,)).fetchone()[0]

        self.assertEqual(second["archived"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(second["copied"], 0)
        self.assertEqual(after, before)
        self.assertEqual(event_count_after, event_count_before)

    def test_new_duplicate_source_is_recorded_without_recopying_archive(self):
        content = b"new duplicate source path"
        first = self.create_pdf("first-copy.pdf", content)
        self.scan_sources()
        initial = archive_documents(self.database, self.original)
        self.assertEqual(initial["copied"], 1)

        second = self.create_pdf("second-copy.pdf", content)
        self.scan_sources()
        result = archive_documents(self.database, self.original)

        digest = hashlib.sha256(content).hexdigest()

        with connect(self.database) as db:
            paths = {
                row["source_path"]
                for row in db.execute("""
                    SELECT source_path FROM archive_sources
                    WHERE sha256 = ?
                """, (digest,)).fetchall()
            }

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["copied"], 0)
        self.assertEqual(
            paths,
            {str(first.resolve()), str(second.resolve())},
        )


if __name__ == "__main__":
    unittest.main()
