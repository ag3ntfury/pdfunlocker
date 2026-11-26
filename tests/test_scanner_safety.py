import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.profiles.store import initialize_database
from pdfunlocker.scanner import scan, connect


class ScannerSafetyTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "database" / "test.db"
        self.source = self.root / "source"
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

    def create_pdf(self, path, content=b"%PDF-1.4\nTest\n"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def get_file_status(self, path):
        with connect(self.database) as db:
            row = db.execute(
                "SELECT file_status FROM file_instances WHERE path = ?",
                (str(path.resolve()),),
            ).fetchone()
        return row["file_status"] if row else None

    def test_unavailable_root_does_not_mark_old_files_missing(self):
        original = self.create_pdf(self.source / "existing.pdf")
        first = scan(self.database, self.settings)

        self.assertEqual(first["status"], "completed")
        self.assertEqual(self.get_file_status(original), "present")

        # Simulate a disconnected drive: the configured mount path vanishes,
        # while its previously indexed files are no longer accessible.
        offline_source = self.root / "offline-source"
        self.source.rename(offline_source)

        second = scan(self.database, self.settings)

        self.assertEqual(second["status"], "partial")
        self.assertGreater(second["errors"], 0)
        self.assertEqual(self.get_file_status(original), "present")

    def test_traversal_permission_error_preserves_old_file_status(self):
        original = self.create_pdf(self.source / "protected.pdf")
        scan(self.database, self.settings)

        def failing_walk(*args, **kwargs):
            error = PermissionError(
                errno.EACCES,
                "Permission denied during traversal",
                str(self.source),
            )
            kwargs["onerror"](error)
            return iter(())

        with patch(
            "pdfunlocker.scanner.os.walk",
            side_effect=failing_walk,
        ):
            result = scan(self.database, self.settings)

        self.assertEqual(result["status"], "partial")
        self.assertGreater(result["errors"], 0)
        self.assertEqual(self.get_file_status(original), "present")

    def test_symlink_directory_loop_does_not_repeat_or_hang(self):
        self.create_pdf(self.source / "inside.pdf")

        loop = self.source / "loop"
        try:
            loop.symlink_to(self.source, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Directory symlinks are unavailable.")

        self.settings["scan"]["follow_symlinks"] = True

        result = scan(self.database, self.settings)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["files_seen"], 1)
        self.assertEqual(result["files_hashed"], 1)

        with connect(self.database) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM file_instances"
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_file_mutated_during_hash_is_not_recorded_as_scanned(self):
        changing_file = self.create_pdf(
            self.source / "changing.pdf",
            b"original content",
        )

        real_fstat = os.fstat
        calls = {"count": 0}

        def mutate_during_hash(file_descriptor):
            info = real_fstat(file_descriptor)
            calls["count"] += 1

            if calls["count"] == 1:
                with changing_file.open("ab") as output:
                    output.write(b"\nchanged during scan")

            return info

        with patch(
            "pdfunlocker.scanner.os.fstat",
            side_effect=mutate_during_hash,
        ):
            result = scan(self.database, self.settings)

        self.assertEqual(result["status"], "partial")
        self.assertGreater(result["errors"], 0)
        self.assertEqual(result["files_hashed"], 0)
        self.assertIsNone(self.get_file_status(changing_file))

        with connect(self.database) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_completed_root_marks_genuinely_deleted_file_missing(self):
        original = self.create_pdf(self.source / "deleted.pdf")

        first = scan(self.database, self.settings)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(self.get_file_status(original), "present")

        original.unlink()

        second = scan(self.database, self.settings)

        self.assertEqual(second["status"], "completed")
        self.assertEqual(self.get_file_status(original), "missing")


if __name__ == "__main__":
    unittest.main()
