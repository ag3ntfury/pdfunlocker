import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pdfunlocker.config.paths import default_paths, resolve_paths, validate_path_relationships
from pdfunlocker.database.backup import create_database_snapshot, export_database, migrate_database
from pdfunlocker.cli.profiles import paths as profile_paths


class PathDefaultsTests(unittest.TestCase):
    def test_android_defaults(self):
        paths = default_paths("android", "/tmp/example-home")
        self.assertEqual(paths["installation"], Path("/tmp/example-home/.pdfunlocker"))
        self.assertEqual(paths["pdf_storage_root"], Path("/storage/emulated/0/Documents/PDFUnlocker"))

    def test_linux_defaults(self):
        paths = default_paths("linux", "/tmp/example-home")
        self.assertEqual(paths["installation"], Path("/tmp/example-home/.pdfunlocker"))
        self.assertEqual(paths["pdf_storage_root"], Path("/tmp/example-home/Documents/PDFUnlocker"))

    def test_paths_are_independently_configurable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "app"
            root.mkdir()
            custom_root = Path(temp) / "documents" / "PDFUnlocker"
            custom = {
                "environment": "linux",
                "paths": {
                    "installation": str(root),
                    "pdf_storage_root": str(custom_root),
                    "processed": str(custom_root / "Processed"),
                    "exports": str(custom_root / "Export"),
                },
            }
            (root / "config").mkdir()
            (root / "config/settings.json").write_text(json.dumps(custom))
            resolved = resolve_paths(root)
            self.assertEqual(resolved["pdf_storage_root"], custom_root)
            self.assertEqual(resolved["processed"], custom_root / "Processed")
            self.assertEqual(resolved["database"], root / "database/pdfunlocker.db")
            self.assertEqual(resolved["database_manual_exports"], custom_root / "Export/Database/Manual")

    def test_data_may_be_inside_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertTrue(validate_path_relationships(root / ".pdfunlocker", root / "PDFUnlocker"))


    def test_profile_cli_uses_configured_data_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "app"
            (root / "config").mkdir(parents=True)
            custom_data = Path(temp) / "user-data"
            settings = {"environment": "linux", "paths": {"installation": str(root), "pdf_storage_root": str(Path(temp) / "PDFUnlocker")}}
            (root / "config/settings.json").write_text(json.dumps(settings))
            resolved = profile_paths(root)
            self.assertEqual(resolved["database"], root / "database/pdfunlocker.db")
            self.assertEqual(resolved["template"], root / "templates/profile/default_profile_template.yml")

    def test_data_cannot_be_ancestor_of_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                validate_path_relationships(root / "app", root)

    def test_pdf_library_cannot_overlap_application_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                validate_path_relationships(root / ".pdfunlocker", root / ".pdfunlocker/data/pdfs")


    def test_android_public_root_is_documents_pdfunlocker(self):
        paths = default_paths("android", "/tmp/termux")
        self.assertEqual(paths["processed"], Path("/storage/emulated/0/Documents/PDFUnlocker/Processed"))
        self.assertEqual(paths["exports"], Path("/storage/emulated/0/Documents/PDFUnlocker/Export"))

    def test_fixed_private_tree_has_all_hidden_pdf_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / ".pdfunlocker"
            from pdfunlocker.config.paths import create_internal_structure
            create_internal_structure(root)
            for folder in ("Original", "Locked", "Unlocked", "Corrupted", "Unsupported", "Duplicates"):
                self.assertTrue((root / "storage" / folder).is_dir())



class DatabaseExportTests(unittest.TestCase):
    def test_snapshot_is_integrity_checked_and_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "active.sqlite3"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE example(value TEXT)")
                db.execute("INSERT INTO example VALUES ('preserved')")
            snapshot = create_database_snapshot(db_path, root / "exports", "manual")
            self.assertTrue(snapshot.is_file())
            with sqlite3.connect(snapshot) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("SELECT value FROM example").fetchone()[0], "preserved")

    def test_export_uses_pdf_library_export_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "active.sqlite3"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE sample(value INTEGER)")
                db.execute("INSERT INTO sample VALUES (7)")
            result = export_database(db_path, root / "PDFUnlocker", "manual", root / "private-backups")
            self.assertEqual(result["export"].parent, root / "PDFUnlocker/Export/Database/Manual")
            self.assertEqual(result["recovery"].parent, root / "private-backups")
            self.assertTrue(result["export"].is_file())
            self.assertTrue(result["recovery"].is_file())


    def test_legacy_database_migration_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy.sqlite3"
            destination = root / "data/database/pdfunlocker.db"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE preserved(value TEXT)")
                db.execute("INSERT INTO preserved VALUES ('original')")
            migrated = migrate_database(source, destination)
            self.assertTrue(source.is_file())
            self.assertEqual(migrated, destination)
            with sqlite3.connect(source) as db:
                self.assertEqual(db.execute("SELECT value FROM preserved").fetchone()[0], "original")
            with sqlite3.connect(destination) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("SELECT value FROM preserved").fetchone()[0], "original")

    def test_migration_refuses_to_overwrite_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy.sqlite3"
            destination = root / "new.sqlite3"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE t(value)")
            destination.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                migrate_database(source, destination)
            self.assertEqual(destination.read_bytes(), b"keep")

    def test_missing_database_does_not_create_empty_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(FileNotFoundError):
                create_database_snapshot(root / "missing.sqlite3", root / "exports")
            self.assertFalse((root / "exports").exists())


if __name__ == "__main__":
    unittest.main()
