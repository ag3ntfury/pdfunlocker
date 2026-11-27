import json
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


class InstallerPathTests(TemporaryTest):
    def test_android_defaults(self):
        with patch.object(installer, "detect_environment", return_value=("android", "Android")):
            paths = installer.get_default_paths()
        self.assertEqual(paths["install_path"], Path.home() / ".pdfunlocker")
        self.assertEqual(
            paths["pdf_storage_root"],
            Path("/storage/emulated/0/Documents/PDFUnlocker"),
        )

    def test_linux_defaults(self):
        with patch.object(installer, "detect_environment", return_value=("linux", "Linux")):
            paths = installer.get_default_paths()
        self.assertEqual(paths["install_path"], Path.home() / ".pdfunlocker")
        self.assertEqual(
            paths["pdf_storage_root"],
            Path.home() / "Documents" / "PDFUnlocker",
        )

    def test_install_and_public_storage_must_not_overlap(self):
        with self.assertRaises(RuntimeError):
            installer.validate_directory_relationships(self.root, self.root / "public")

    def test_separate_install_and_public_storage_are_valid(self):
        installer.validate_directory_relationships(
            self.root / ".pdfunlocker",
            self.root / "Documents" / "PDFUnlocker",
        )

    def test_no_manual_path_prompt_helper_remains(self):
        self.assertFalse(hasattr(installer, "ask_path"))


class ApplicationCopyTests(TemporaryTest):
    def make_source(self, source):
        package = source / "src/pdfunlocker/cli"
        package.mkdir(parents=True)
        (package / "main.py").write_text("# installer")
        (source / "pyproject.toml").write_text("[project]\nname='pdfunlocker'\n")

    def test_copy_application_creates_required_internal_tree(self):
        source = self.root / "source"
        destination = self.root / "destination"
        self.make_source(source)

        installer.copy_application(source, destination)

        for relative in (
            "config",
            "database",
            "profiles",
            "rules",
            "learning",
            "storage/Original",
            "storage/Locked",
            "storage/Unlocked",
            "queue/Pending",
            "backups/Database",
            "logs/Application",
            "reports",
            "temp",
            "cache",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((destination / relative).is_dir())

    def test_copy_application_preserves_destination_settings_and_profile_data(self):
        source = self.root / "source"
        destination = self.root / "destination"
        self.make_source(source)

        (source / "config").mkdir()
        (source / "config/settings.json").write_text('{"source": true}')
        (source / "profiles").mkdir()
        (source / "profiles/source-profile.yml").write_text("source: true")

        (destination / "config").mkdir(parents=True)
        (destination / "config/settings.json").write_text('{"destination": true}')
        (destination / "profiles").mkdir()
        (destination / "profiles/existing-profile.yml").write_text("keep: true")

        installer.copy_application(source, destination)

        self.assertEqual(
            json.loads((destination / "config/settings.json").read_text()),
            {"destination": True},
        )
        self.assertTrue((destination / "profiles/existing-profile.yml").is_file())
        self.assertTrue((destination / "profiles/source-profile.yml").is_file())

    def test_source_settings_are_migrated_if_destination_has_none(self):
        source = self.root / "source"
        destination = self.root / "destination"
        self.make_source(source)
        (source / "config").mkdir()
        (source / "config/settings.json").write_text('{"keep": "old-settings"}')

        installer.copy_application(source, destination)

        self.assertEqual(
            json.loads((destination / "config/settings.json").read_text()),
            {"keep": "old-settings"},
        )

    def test_copy_application_skips_python_cache(self):
        source = self.root / "source"
        destination = self.root / "destination"
        package = source / "src/pdfunlocker"
        (package / "cli").mkdir(parents=True)
        (package / "cli/main.py").write_text("# installer")
        (package / "__pycache__").mkdir()
        (package / "__pycache__/cached.pyc").write_bytes(b"cache")

        installer.copy_application(source, destination)

        self.assertTrue((destination / "src/pdfunlocker/cli/main.py").is_file())
        self.assertFalse((destination / "src/pdfunlocker/__pycache__").exists())


class InstallerFlowTests(TemporaryTest):
    def test_setup_finishes_when_optional_profile_is_skipped(self):
        source = Path(__file__).resolve().parents[1]
        install = self.root / ".pdfunlocker"
        public = self.root / "Documents" / "PDFUnlocker"
        defaults = {
            "environment": "linux",
            "environment_name": "Linux",
            "install_path": install,
            "pdf_storage_root": public,
            "processed": public / "Processed",
            "exports": public / "Export",
        }
        scan = {
            "locations": [str(self.root)],
            "recursive": True,
            "follow_symlinks": False,
            "exclude_paths": [str(install), str(public)],
            "location_exclusions": {},
            "file_extensions": [".pdf"],
            "duplicate_detection": "sha256",
            "source_files": "never_modify",
        }

        with patch.object(installer, "get_default_paths", return_value=defaults), \
             patch.object(installer, "_scan_settings", return_value=scan), \
             patch.object(installer, "register_launcher", return_value=self.root / "bin/pdfunlocker"), \
             patch.object(installer, "migrate_existing_database", return_value={
                 "database": install / "database/pdfunlocker.db",
                 "migrated_from": None,
             }), \
             patch("pdfunlocker.cli.profiles.prompt", return_value="n"):
            self.assertEqual(installer.run_setup(), 0)

        settings = json.loads((install / "config/settings.json").read_text())
        self.assertEqual(settings["setup"]["installer_stage"], "setup_completed")
        self.assertTrue(settings["setup"]["scan_locations_configured"])
        self.assertFalse(settings["setup"]["profile_configured"])
        self.assertTrue(settings["setup"]["completed"])
        self.assertTrue((public / "Processed").is_dir())
        self.assertTrue((public / "Export").is_dir())

    def test_setup_yes_invokes_existing_profile_setup(self):
        source = Path(__file__).resolve().parents[1]
        install = self.root / ".pdfunlocker"
        public = self.root / "Documents" / "PDFUnlocker"
        defaults = {
            "environment": "linux",
            "environment_name": "Linux",
            "install_path": install,
            "pdf_storage_root": public,
            "processed": public / "Processed",
            "exports": public / "Export",
        }
        scan = {
            "locations": [str(self.root)],
            "recursive": True,
            "follow_symlinks": False,
            "exclude_paths": [str(install), str(public)],
            "location_exclusions": {},
            "file_extensions": [".pdf"],
            "duplicate_detection": "sha256",
            "source_files": "never_modify",
        }

        with patch.object(installer, "get_default_paths", return_value=defaults), \
             patch.object(installer, "_scan_settings", return_value=scan), \
             patch.object(installer, "register_launcher", return_value=self.root / "bin/pdfunlocker"), \
             patch.object(installer, "migrate_existing_database", return_value={
                 "database": install / "database/pdfunlocker.db",
                 "migrated_from": None,
             }), \
             patch("pdfunlocker.cli.profiles.prompt", return_value="yes"), \
             patch.object(installer, "run_profile_setup", return_value=0) as profile_setup:
            self.assertEqual(installer.run_setup(), 0)

        profile_setup.assert_called_once_with(
            install,
            install / "config" / "settings.json",
        )


    def test_profile_setup_completes_when_existing_order_is_not_confirmed(self):
        install = self.root / ".pdfunlocker"
        config = install / "config" / "settings.json"
        database = install / "database" / "pdfunlocker.db"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"setup": {"completed": False}}))

        from pdfunlocker.profiles.store import (
            create_profile,
            initialize_database,
            list_profiles,
        )

        initialize_database(database)
        create_profile(database, "Existing profile")

        with patch(
            "pdfunlocker.cli.profiles.prompt",
            side_effect=["n", "n"],
        ):
            self.assertEqual(installer.run_profile_setup(install, config), 0)

        settings = json.loads(config.read_text())
        self.assertTrue(settings["setup"]["profile_configured"])
        self.assertTrue(settings["setup"]["installer_stage_completed"])
        self.assertTrue(settings["setup"]["completed"])
        self.assertEqual(settings["setup"]["installer_stage"], "profile_configured")

        profiles = list_profiles(database, include_disabled=False)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Existing profile")
        self.assertEqual(profiles[0]["execution_order"], 1)

    def test_setup_preserves_existing_settings_and_profile_files(self):
        source = Path(__file__).resolve().parents[1]
        install = self.root / ".pdfunlocker"
        public = self.root / "Documents" / "PDFUnlocker"
        install.mkdir()
        (install / "config").mkdir()
        (install / "config/settings.json").write_text(
            json.dumps({"custom_setting": "preserve", "setup": {"profile_configured": False}})
        )
        (install / "profiles").mkdir()
        (install / "profiles/user-profile.yml").write_text("profile: keep")
        defaults = {
            "environment": "linux",
            "environment_name": "Linux",
            "install_path": install,
            "pdf_storage_root": public,
            "processed": public / "Processed",
            "exports": public / "Export",
        }
        scan = {
            "locations": [str(self.root)],
            "recursive": True,
            "follow_symlinks": False,
            "exclude_paths": [str(install), str(public)],
            "location_exclusions": {},
            "file_extensions": [".pdf"],
            "duplicate_detection": "sha256",
            "source_files": "never_modify",
        }

        with patch.object(installer, "get_default_paths", return_value=defaults), \
             patch.object(installer, "_scan_settings", return_value=scan), \
             patch.object(installer, "register_launcher", return_value=self.root / "bin/pdfunlocker"), \
             patch.object(installer, "migrate_existing_database", return_value={
                 "database": install / "database/pdfunlocker.db",
                 "migrated_from": None,
             }), \
             patch("pdfunlocker.cli.profiles.prompt", return_value="n"):
            self.assertEqual(installer.run_setup(), 0)

        settings = json.loads((install / "config/settings.json").read_text())
        self.assertEqual(settings["custom_setting"], "preserve")
        self.assertTrue((install / "profiles/user-profile.yml").is_file())


    def test_scan_configure_updates_only_scan_and_preserves_other_settings(self):
        install = self.root / ".pdfunlocker"
        config = install / "config" / "settings.json"
        config.parent.mkdir(parents=True)
        original = {
            "environment": "linux",
            "custom_key": "keep-me",
            "paths": {
                "installation": str(install),
                "pdf_storage_root": str(self.root / "Documents" / "PDFUnlocker"),
            },
            "setup": {"profile_configured": False, "completed": False},
            "scan": {"locations": ["/old/location"]},
        }
        config.write_text(json.dumps(original))
        fake_main = install / "src/pdfunlocker/cli/main.py"
        fake_main.parent.mkdir(parents=True)
        fake_main.write_text("# test")
        new_scan = {
            "locations": [str(self.root)],
            "recursive": True,
            "follow_symlinks": False,
            "exclude_paths": [str(install)],
            "location_exclusions": {},
            "file_extensions": [".pdf"],
            "duplicate_detection": "sha256",
            "source_files": "never_modify",
        }

        with patch.object(installer, "__file__", str(fake_main)), \
             patch.object(installer, "_scan_settings", return_value=new_scan):
            self.assertEqual(installer.run_scan_configure(), 0)

        updated = json.loads(config.read_text())
        self.assertEqual(updated["custom_key"], "keep-me")
        self.assertEqual(updated["scan"], new_scan)
        self.assertEqual(updated["paths"], original["paths"])
        self.assertFalse(updated["setup"]["completed"])
        self.assertTrue(list(config.parent.glob("settings.json.before-v1.3-*")))


class ScanValidationTests(TemporaryTest):
    def test_validate_existing_directory(self):
        path, error = scan_locations.validate_directory(self.root)
        self.assertEqual(path, self.root.resolve())
        self.assertIsNone(error)

    def test_validate_missing_directory(self):
        path, error = scan_locations.validate_directory(self.root / "missing")
        self.assertIsNone(path)
        self.assertIsNotNone(error)

    def test_validate_file_rejected(self):
        file_path = self.root / "file.pdf"
        file_path.write_text("not a directory")
        path, error = scan_locations.validate_directory(file_path)
        self.assertIsNone(path)
        self.assertIsNotNone(error)

    def test_add_location_deduplicates_nested_roots(self):
        parent = self.root / "Documents"
        child = parent / "Bank"
        child.mkdir(parents=True)
        locations = [child]
        self.assertTrue(scan_locations.add_location(locations, parent))
        self.assertEqual(locations, [parent.resolve()])
        self.assertFalse(scan_locations.add_location(locations, child))


class AndroidSelectionTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        self.shared = self.root / "shared"
        self.shared.mkdir()
        self.public = self.shared / "Documents" / "PDFUnlocker"
        self.public.mkdir(parents=True)
        (self.shared / "Download").mkdir()
        (self.shared / "Documents").mkdir(exist_ok=True)
        (self.shared / "Pictures").mkdir()

    def test_empty_enter_selects_entire_shared_storage_only(self):
        with patch.object(scan_locations, "ANDROID_STORAGE", self.shared), \
             patch("builtins.input", return_value=""):
            result = scan_locations.android_scan_locations(self.public)
        self.assertEqual(result, [self.shared.resolve()])

    def test_multiple_number_selection(self):
        # Sorted display order: Documents, Download, Pictures.
        with patch.object(scan_locations, "ANDROID_STORAGE", self.shared), \
             patch("builtins.input", return_value="3,1"):
            result = scan_locations.android_scan_locations(self.public)
        self.assertEqual(
            result,
            [(self.shared / "Pictures").resolve(), (self.shared / "Documents").resolve()],
        )

    def test_invalid_number_reprompts(self):
        with patch.object(scan_locations, "ANDROID_STORAGE", self.shared), \
             patch("builtins.input", side_effect=["0", "99", "2"]):
            result = scan_locations.android_scan_locations(self.public)
        self.assertEqual(result, [(self.shared / "Download").resolve()])


class LinuxSelectionTests(TemporaryTest):
    def setUp(self):
        super().setUp()
        self.home = self.root / "home" / "fury"
        self.home.mkdir(parents=True)
        self.public = self.home / "Documents" / "PDFUnlocker"
        self.public.mkdir(parents=True)

    def test_empty_enter_uses_home_default(self):
        with patch("builtins.input", return_value=""):
            result = scan_locations.linux_scan_locations(self.public, home=self.home)
        self.assertEqual(result, [self.home.resolve()])

    def test_custom_paths_replace_home_default(self):
        first = self.root / "storage1" / "Documents"
        second = self.root / "srv" / "services" / "paperless"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        with patch("builtins.input", side_effect=[str(first), str(second), ""]):
            result = scan_locations.linux_scan_locations(self.public, home=self.home)
        self.assertEqual(result, [first.resolve(), second.resolve()])
        self.assertNotIn(self.home.resolve(), result)

    def test_relative_path_rejected(self):
        folder = self.root / "Documents"
        folder.mkdir()
        with patch("builtins.input", side_effect=["Documents", str(folder), ""]):
            result = scan_locations.linux_scan_locations(self.public, home=self.home)
        self.assertEqual(result, [folder.resolve()])

    def test_invalid_path_reprompts(self):
        folder = self.root / "valid"
        folder.mkdir()
        with patch("builtins.input", side_effect=[str(self.root / "missing"), str(folder), ""]):
            result = scan_locations.linux_scan_locations(self.public, home=self.home)
        self.assertEqual(result, [folder.resolve()])

    def test_nested_custom_paths_are_deduplicated(self):
        parent = self.root / "Documents"
        child = parent / "Bank"
        child.mkdir(parents=True)
        with patch("builtins.input", side_effect=[str(child), str(parent), ""]):
            result = scan_locations.linux_scan_locations(self.public, home=self.home)
        self.assertEqual(result, [parent.resolve()])


class ScanConfigurationTests(TemporaryTest):
    def test_android_full_storage_excludes_public_output_and_install(self):
        shared = self.root / "shared"
        shared.mkdir()
        public = shared / "Documents" / "PDFUnlocker"
        public.mkdir(parents=True)
        install = self.root / ".pdfunlocker"
        install.mkdir()

        with patch.object(scan_locations, "ANDROID_STORAGE", shared), \
             patch("builtins.input", return_value=""):
            result = scan_locations.select_scan_locations(
                "android", public, installation=install
            )

        self.assertEqual(result["locations"], [str(shared.resolve())])
        self.assertIn(str(public.resolve()), result["exclude_paths"])
        self.assertIn(str(install.resolve()), result["exclude_paths"])
        self.assertFalse(result["follow_symlinks"])
        self.assertEqual(result["source_files"], "never_modify")

    def test_android_documents_selection_excludes_nested_public_output(self):
        shared = self.root / "shared"
        documents = shared / "Documents"
        public = documents / "PDFUnlocker"
        public.mkdir(parents=True)
        (shared / "Download").mkdir()
        install = self.root / ".pdfunlocker"
        install.mkdir()

        with patch.object(scan_locations, "ANDROID_STORAGE", shared), \
             patch("builtins.input", return_value="1"):
            result = scan_locations.select_scan_locations(
                "android", public, installation=install
            )

        self.assertEqual(result["locations"], [str(documents.resolve())])
        self.assertIn(str(public.resolve()), result["exclude_paths"])

    def test_linux_default_home_excludes_app_and_public_output(self):
        home = self.root / "home"
        home.mkdir()
        public = home / "Documents" / "PDFUnlocker"
        public.mkdir(parents=True)
        install = home / ".pdfunlocker"
        install.mkdir()

        result = scan_locations.select_scan_locations(
            "linux", public, installation=install, default=True, home=home
        )

        self.assertEqual(result["locations"], [str(home.resolve())])
        self.assertIn(str(public.resolve()), result["exclude_paths"])
        self.assertIn(str(install.resolve()), result["exclude_paths"])


    def test_linux_custom_paths_replace_home_and_exclude_output_and_install(self):
        home = self.root / "home"
        home.mkdir()
        custom = self.root / "storage" / "Documents"
        custom.mkdir(parents=True)
        public = home / "Documents" / "PDFUnlocker"
        public.mkdir(parents=True)
        install = home / ".pdfunlocker"
        install.mkdir()

        with patch("builtins.input", side_effect=[str(custom), ""]):
            result = scan_locations.select_scan_locations(
                "linux", public, installation=install, home=home
            )

        self.assertEqual(result["locations"], [str(custom.resolve())])
        self.assertNotIn(str(home.resolve()), result["locations"])
        self.assertIn(str(public.resolve()), result["exclude_paths"])
        self.assertIn(str(install.resolve()), result["exclude_paths"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
