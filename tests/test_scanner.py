import tempfile
import unittest
from pathlib import Path

from pdfunlocker.profiles.store import (
    initialize_database,
    create_profile,
    set_profile_value,
    get_profile,
)
from pdfunlocker.scanner import (
    scan,
    get_scan_status,
    get_duplicates,
    connect,
)


class ScannerTests(unittest.TestCase):

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

    def test_duplicate_detection(self):
        self.create_pdf(self.source / "one.pdf", b"same")
        self.create_pdf(self.source / "two.pdf", b"same")
        self.create_pdf(self.source / "three.pdf", b"different")

        result = scan(self.database, self.settings)

        self.assertEqual(result["files_hashed"], 3)
        self.assertEqual(result["duplicate_groups"], 1)
        self.assertEqual(len(get_duplicates(self.database)), 1)

    def test_changed_file_content(self):
        path = self.create_pdf(self.source / "changed.pdf", b"original")
        scan(self.database, self.settings)

        self.create_pdf(path, b"modified")
        scan(self.database, self.settings)

        with connect(self.database) as db:
            row = db.execute("""
                SELECT file_status FROM file_instances
                WHERE path = ?
            """, (str(path),)).fetchone()

        self.assertEqual(row["file_status"], "changed")

    def test_moved_file_keeps_document_identity(self):
        original = self.create_pdf(self.source / "old.pdf", b"same content")
        scan(self.database, self.settings)

        moved_folder = self.source / "new_folder"
        moved_folder.mkdir()
        moved = moved_folder / "new.pdf"
        original.rename(moved)

        result = scan(self.database, self.settings)
        self.assertEqual(result["files_hashed"], 1)

        with connect(self.database) as db:
            documents = db.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0]

            instances = db.execute(
                "SELECT COUNT(*) FROM file_instances"
            ).fetchone()[0]

            moved_row = db.execute("""
                SELECT path, file_status
                FROM file_instances
            """).fetchone()

            event = db.execute("""
                SELECT event_type, details
                FROM document_events
                WHERE event_type = 'file_moved'
                ORDER BY event_id DESC LIMIT 1
            """).fetchone()

        self.assertEqual(documents, 1)
        self.assertEqual(instances, 1)
        self.assertEqual(moved_row["path"], str(moved))
        self.assertEqual(moved_row["file_status"], "present")
        self.assertIsNotNone(event)

        import json
        details = json.loads(event["details"])
        self.assertEqual(details["old_path"], str(original))
        self.assertEqual(details["new_path"], str(moved))

    def test_identical_existing_copy_is_not_misidentified_as_move(self):
        original = self.create_pdf(self.source / "old.pdf", b"same content")
        duplicate = self.create_pdf(self.source / "copy.pdf", b"same content")
        scan(self.database, self.settings)

        moved_folder = self.source / "new_folder"
        moved_folder.mkdir()
        moved = moved_folder / "new.pdf"
        original.rename(moved)

        scan(self.database, self.settings)

        with connect(self.database) as db:
            instances = db.execute(
                "SELECT COUNT(*) FROM file_instances"
            ).fetchone()[0]
            move_events = db.execute("""
                SELECT COUNT(*) FROM document_events
                WHERE event_type = 'file_moved'
            """).fetchone()[0]
            present_paths = {
                row["path"] for row in db.execute("""
                    SELECT path FROM file_instances
                    WHERE file_status = 'present'
                """).fetchall()
            }

        self.assertEqual(instances, 3)
        self.assertEqual(move_events, 0)
        self.assertIn(str(moved), present_paths)
        self.assertIn(str(duplicate), present_paths)

    def test_excluded_directory(self):
        excluded = self.source / "excluded"
        excluded.mkdir()
        self.create_pdf(excluded / "hidden.pdf")

        self.settings["scan"]["exclude_paths"] = [str(excluded)]

        result = scan(self.database, self.settings)
        self.assertEqual(result["files_hashed"], 0)

    def test_non_pdf_files_are_ignored(self):
        (self.source / "notes.txt").write_text("not a PDF")
        (self.source / "image.jpg").write_bytes(b"image")

        result = scan(self.database, self.settings)
        self.assertEqual(result["files_seen"], 0)
        self.assertEqual(result["files_hashed"], 0)

    def test_symlink_is_not_followed(self):
        target = self.create_pdf(self.root / "outside.pdf")

        link = self.source / "linked.pdf"

        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable in this environment.")

        result = scan(self.database, self.settings)
        self.assertEqual(result["files_hashed"], 0)

    def test_profile_data_survives_scanning(self):
        profile_id = create_profile(self.database, "Preservation Test")
        template = Path("templates/profile/default_profile_template.yml")

        value_id = set_profile_value(
            self.database, template, profile_id, "1001", "Mr"
        )

        self.create_pdf(self.source / "test.pdf")
        scan(self.database, self.settings)

        profile, values = get_profile(self.database, profile_id)

        self.assertEqual(profile["name"], "Preservation Test")
        self.assertTrue(any(
            value["value_id"] == value_id and value["value"] == "Mr"
            for value in values
        ))

    def test_scan_history(self):
        self.create_pdf(self.source / "test.pdf")

        first = scan(self.database, self.settings)
        second = scan(self.database, self.settings)

        self.assertNotEqual(first["scan_id"], second["scan_id"])

        with connect(self.database) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM scan_runs"
            ).fetchone()[0]

        self.assertEqual(count, 2)

    def test_status_summary(self):
        self.create_pdf(self.source / "one.pdf", b"same")
        self.create_pdf(self.source / "two.pdf", b"same")

        scan(self.database, self.settings)
        status = get_scan_status(self.database)

        self.assertEqual(status["unique_documents"], 1)
        self.assertEqual(status["present_file_instances"], 2)
        self.assertEqual(status["duplicate_groups"], 1)


if __name__ == "__main__":
    unittest.main()
