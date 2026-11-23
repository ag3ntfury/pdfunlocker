import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.cli import main as installer
from pdfunlocker.setup import scan_locations


class TemporaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)


class InstallerHelperTests(TemporaryTest):

    def test_detect_environment_returns_supported_environment(self):
        environment, name = installer.detect_environment()
        self.assertIn(environment, {"android", "linux"})
        self.assertTrue(name)

    def test_android_default_pdf_storage(self):
        with patch.object(installer, "detect_environment",
                          return_value=("android", "Android")):
            paths = installer.get_default_paths()
        self.assertEqual(paths["pdf_storage"], Path("/storage/emulated/0/PDFUnlocker"))

    def test_linux_default_pdf_storage(self):
        with patch.object(installer, "detect_environment",
                          return_value=("linux", "Linux")):
            paths = installer.get_default_paths()
        self.assertEqual(paths["pdf_storage"], Path.home() / "PDFUnlocker")

    def test_is_inside_child(self):
        self.assertTrue(installer.is_inside(self.root / "child", self.root))

    def test_is_inside_same_directory(self):
        self.assertTrue(installer.is_inside(self.root, self.root))

    def test_is_inside_unrelated_directory(self):
        self.assertFalse(installer.is_inside(Path("/tmp/one"), Path("/tmp/two")))

    def test_install_storage_same_path_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.validate_directory_relationships(self.root, self.root)

    def test_storage_inside_install_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.validate_directory_relationships(
                self.root, self.root / "storage"
            )

    def test_install_inside_storage_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.validate_directory_relationships(
                self.root / "app", self.root
            )

    def test_valid_separate_paths_accepted(self):
        installer.validate_directory_relationships(
            self.root / "app", self.root / "pdfs"
        )

    def test_root_install_path_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.validate_directory_relationships(Path("/"), self.root)

    def test_home_install_path_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.validate_directory_relationships(Path.home(), self.root)

    def test_prepare_pdf_storage_creates_all_folders(self):
        storage = self.root / "PDFUnlocker"
        installer.prepare_pdf_storage(storage)
        self.assertTrue(storage.is_dir())
        for folder in installer.PDF_STORAGE_FOLDERS:
            with self.subTest(folder=folder):
                self.assertTrue((storage / folder).is_dir())

    def test_prepare_pdf_storage_is_idempotent(self):
        storage = self.root / "PDFUnlocker"
        installer.prepare_pdf_storage(storage)
        installer.prepare_pdf_storage(storage)
        for folder in installer.PDF_STORAGE_FOLDERS:
            self.assertTrue((storage / folder).is_dir())

    def test_save_settings_writes_json(self):
        path = self.root / "config" / "settings.json"
        installer.save_settings(path, {"environment": "test"})
        self.assertEqual(
            json.loads(path.read_text())["environment"], "test"
        )

    def test_save_settings_merges_existing_keys(self):
        path = self.root / "settings.json"
        path.write_text(json.dumps({"keep": 1, "change": 1}))
        installer.save_settings(path, {"change": 2})
        data = json.loads(path.read_text())
        self.assertEqual(data, {"keep": 1, "change": 2})

    def test_save_settings_rejects_invalid_json(self):
        path = self.root / "settings.json"
        path.write_text("{broken")
        with self.assertRaises(RuntimeError):
            installer.save_settings(path, {"new": True})

    def test_save_settings_rejects_non_object_json(self):
        path = self.root / "settings.json"
        path.write_text(json.dumps(["not", "an", "object"]))
        with self.assertRaises(RuntimeError):
            installer.save_settings(path, {"new": True})

    def test_copy_application_preserves_destination_settings(self):
        source = self.root / "source"
        destination = self.root / "destination"
        (source / "src/pdfunlocker/cli").mkdir(parents=True)
        (source / "src/pdfunlocker/cli/main.py").write_text("# source")
        (source / "config").mkdir()
        (source / "config/settings.json").write_text('{"source": true}')
        (destination / "config").mkdir(parents=True)
        (destination / "config/settings.json").write_text('{"target": true}')

        installer.copy_application(source, destination)

        data = json.loads((destination / "config/settings.json").read_text())
        self.assertEqual(data, {"target": True})

    def test_copy_application_creates_runtime_directories(self):
        source = self.root / "source"
        destination = self.root / "destination"
        (source / "src/pdfunlocker/cli").mkdir(parents=True)
        (source / "src/pdfunlocker/cli/main.py").write_text("# source")

        installer.copy_application(source, destination)

        for name in ("database", "profiles", "logs", "temp", "exports"):
            with self.subTest(directory=name):
                self.assertTrue((destination / name).is_dir())

    def test_copy_application_ignores_python_cache(self):
        source = self.root / "source"
        destination = self.root / "destination"
        package = source / "src/pdfunlocker"
        (package / "__pycache__").mkdir(parents=True)
        (package / "main.py").write_text("# source")
        (package / "cli").mkdir()
        (package / "cli/main.py").write_text("# required installer entry point")
        (package / "__pycache__/cached.pyc").write_bytes(b"cache")

        installer.copy_application(source, destination)

        self.assertTrue((destination / "src/pdfunlocker/main.py").is_file())
        self.assertTrue(
            (destination / "src/pdfunlocker/cli/main.py").is_file()
        )
        self.assertFalse(
            (destination / "src/pdfunlocker/__pycache__").exists()
        )


class ScanLocationHelperTests(TemporaryTest):

    def test_resolve_existing_directory(self):
        path = scan_locations.resolve_directory(self.root)
        self.assertEqual(path, self.root.resolve())

    def test_resolve_missing_directory_fails(self):
        with self.assertRaises((OSError, RuntimeError, ValueError)):
            scan_locations.resolve_directory(self.root / "missing")

    def test_validate_existing_directory(self):
        path, error = scan_locations.validate_directory(self.root)
        self.assertIsNone(error)
        self.assertEqual(path, self.root.resolve())

    def test_validate_missing_directory(self):
        path, error = scan_locations.validate_directory(self.root / "missing")
        self.assertIsNone(path)
        self.assertIsNotNone(error)

    def test_validate_file_rejected(self):
        file = self.root / "document.txt"
        file.write_text("test")
        path, error = scan_locations.validate_directory(file)
        self.assertIsNone(path)
        self.assertIsNotNone(error)

    def test_add_first_location(self):
        locations = []
        self.assertTrue(scan_locations.add_location(locations, self.root))
        self.assertEqual(locations, [self.root])

    def test_add_nested_location_rejected(self):
        child = self.root / "child"
        child.mkdir()
        locations = [self.root]
        self.assertFalse(scan_locations.add_location(locations, child))
        self.assertEqual(locations, [self.root])

    def test_add_parent_replaces_child(self):
        child = self.root / "child"
        child.mkdir()
        locations = [child]
        self.assertTrue(scan_locations.add_location(locations, self.root))
        self.assertEqual(locations, [self.root])

    def test_add_duplicate_location_rejected(self):
        locations = [self.root]
        self.assertFalse(scan_locations.add_location(locations, self.root))
        self.assertEqual(locations, [self.root])

    def test_decode_mount_spaces(self):
        self.assertEqual(
            scan_locations.decode_mount_path("/mnt/My\\040Drive"),
            "/mnt/My Drive",
        )

    def test_decode_mount_tabs(self):
        self.assertEqual(
            scan_locations.decode_mount_path("/mnt/a\\011b"),
            "/mnt/a\tb",
        )

    def test_decode_mount_newlines(self):
        self.assertEqual(
            scan_locations.decode_mount_path("/mnt/a\\012b"),
            "/mnt/a\nb",
        )

    def test_decode_mount_backslash(self):
        self.assertEqual(
            scan_locations.decode_mount_path("/mnt/a\\134b"),
            "/mnt/a\\b",
        )

    def test_is_inside_child(self):
        self.assertTrue(scan_locations.is_inside(
            self.root / "child", self.root
        ))

    def test_is_inside_unrelated_path(self):
        self.assertFalse(scan_locations.is_inside(
            Path("/tmp/one"), Path("/tmp/two")
        ))


class ScanConfigurationTests(TemporaryTest):

    def test_android_scan_configuration_defaults(self):
        storage = self.root / "PDFUnlocker"
        location = self.root / "Documents"
        storage.mkdir()
        location.mkdir()

        with patch.object(
            scan_locations, "android_scan_locations",
            return_value=[location],
        ):
            result = scan_locations.select_scan_locations("android", storage)

        self.assertEqual(result["locations"], [str(location)])
        self.assertTrue(result["recursive"])
        self.assertFalse(result["follow_symlinks"])
        self.assertEqual(result["exclude_paths"], [str(storage)])
        self.assertEqual(result["file_extensions"], [".pdf"])
        self.assertEqual(result["duplicate_detection"], "sha256")
        self.assertEqual(result["source_files"], "never_modify")

    def test_linux_scan_configuration_excludes_system_mounts(self):
        storage = self.root / "PDFUnlocker"
        location = self.root / "data"
        storage.mkdir()
        location.mkdir()

        with patch.object(
            scan_locations, "linux_scan_locations",
            return_value=[location],
        ):
            result = scan_locations.select_scan_locations("linux", storage)

        self.assertIn(str(storage), result["exclude_paths"])
        for system_mount in scan_locations.SYSTEM_MOUNTS:
            self.assertIn(system_mount, result["exclude_paths"])

    def test_pdf_storage_removed_from_scan_locations(self):
        storage = self.root / "PDFUnlocker"
        location = self.root / "Documents"
        storage.mkdir()
        location.mkdir()

        with patch.object(
            scan_locations, "android_scan_locations",
            return_value=[storage, location],
        ):
            result = scan_locations.select_scan_locations("android", storage)

        self.assertEqual(result["locations"], [str(location)])

    def test_child_inside_pdf_storage_removed(self):
        storage = self.root / "PDFUnlocker"
        child = storage / "Inbox"
        child.mkdir(parents=True)

        with patch.object(
            scan_locations, "android_scan_locations",
            return_value=[child],
        ):
            with self.assertRaises(RuntimeError):
                scan_locations.select_scan_locations("android", storage)

    def test_empty_scan_locations_rejected(self):
        storage = self.root / "PDFUnlocker"
        storage.mkdir()

        with patch.object(
            scan_locations, "android_scan_locations",
            return_value=[],
        ):
            with self.assertRaises(RuntimeError):
                scan_locations.select_scan_locations("android", storage)

    def test_nested_locations_recorded_as_exclusions(self):
        parent = self.root / "Documents"
        child = parent / "Bank"
        child.mkdir(parents=True)
        storage = self.root / "PDFUnlocker"
        storage.mkdir()

        with patch.object(
            scan_locations, "android_scan_locations",
            return_value=[parent, child],
        ):
            result = scan_locations.select_scan_locations("android", storage)

        self.assertEqual(
            result["location_exclusions"],
            {str(parent): [str(child)]},
        )


class AndroidSelectionTests(TemporaryTest):

    def setUp(self):
        super().setUp()
        self.android_root = self.root / "shared"
        self.android_root.mkdir()
        self.storage = self.android_root / "PDFUnlocker"
        self.storage.mkdir()
        (self.android_root / "Download").mkdir()
        (self.android_root / "Documents").mkdir()
        (self.android_root / "WhatsApp" / "Media").mkdir(parents=True)

    def test_blank_input_selects_entire_storage(self):
        with patch.object(scan_locations, "ANDROID_STORAGE", self.android_root):
            with patch("builtins.input", return_value=""):
                result = scan_locations.android_scan_locations(self.storage)

        self.assertEqual(result, [self.android_root.resolve()])

    def test_folder_name_selects_android_folder(self):
        with patch.object(scan_locations, "ANDROID_STORAGE", self.android_root):
            with patch("builtins.input", side_effect=["Download", ""]):
                result = scan_locations.android_scan_locations(self.storage)

        self.assertEqual(result, [(self.android_root / "Download").resolve()])

    def test_nested_android_folder_selection(self):
        with patch.object(scan_locations, "ANDROID_STORAGE", self.android_root):
            with patch("builtins.input", side_effect=["WhatsApp/Media", ""]):
                result = scan_locations.android_scan_locations(self.storage)

        self.assertEqual(
            result,
            [(self.android_root / "WhatsApp/Media").resolve()],
        )

    def test_pdf_unlocker_storage_cannot_be_selected(self):
        with patch.object(scan_locations, "ANDROID_STORAGE", self.android_root):
            with patch(
                "builtins.input",
                side_effect=["PDFUnlocker", "Download", ""],
            ):
                result = scan_locations.android_scan_locations(self.storage)

        self.assertEqual(result, [(self.android_root / "Download").resolve()])

    def test_outside_android_path_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()

        with patch.object(scan_locations, "ANDROID_STORAGE", self.android_root):
            with patch("builtins.input", side_effect=[str(outside), "Download", ""]):
                result = scan_locations.android_scan_locations(self.storage)

        self.assertEqual(result, [(self.android_root / "Download").resolve()])


if __name__ == "__main__":
    unittest.main(verbosity=2)
