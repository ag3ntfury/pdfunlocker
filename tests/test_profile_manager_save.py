import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.profiles import manager, store


class ProfileManagerSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self.old_db_path = store.DB_PATH
        self.old_app_dir = manager.APP_DIR
        self.old_profiles_dir = manager.PROFILES_DIR
        self.old_sequence_file = manager.SEQUENCE_FILE

        store.DB_PATH = self.root / "database" / "profiles.sqlite3"
        manager.APP_DIR = self.root
        manager.PROFILES_DIR = self.root / "profiles"
        manager.SEQUENCE_FILE = self.root / "profiles" / "sequence.json"

        manager.PROFILES_DIR.mkdir(parents=True)
        store.initialize()

        self.profile_path = manager.PROFILES_DIR / "profile01.env"
        self.original = {
            "PROFILE_ID": "1",
            "PROFILE_NAME": "Save Test",
            "FIRST_NAME": "Original",
        }
        manager.save_env(self.profile_path, self.original)

    def tearDown(self):
        store.DB_PATH = self.old_db_path
        manager.APP_DIR = self.old_app_dir
        manager.PROFILES_DIR = self.old_profiles_dir
        manager.SEQUENCE_FILE = self.old_sequence_file
        self.tmp.cleanup()

    def test_export_failure_keeps_previous_export(self):
        updated = dict(self.original, FIRST_NAME="Updated")

        with patch.object(
            manager,
            "_save_env_file",
            side_effect=OSError("simulated export write failure"),
        ):
            with self.assertRaises(OSError):
                manager.save_env(self.profile_path, updated)

        self.assertEqual(manager._load_env_file(self.profile_path), self.original)
        self.assertEqual(store.load_profile(1), updated)

    def test_database_failure_keeps_previous_export(self):
        updated = dict(self.original, FIRST_NAME="Updated")

        with patch.object(
            store,
            "save_profile",
            side_effect=RuntimeError("simulated database failure"),
        ):
            with self.assertRaises(RuntimeError):
                manager.save_env(self.profile_path, updated)

        self.assertEqual(manager._load_env_file(self.profile_path), self.original)
        self.assertEqual(store.load_profile(1), self.original)

    def test_load_repairs_stale_export_from_database(self):
        updated = dict(self.original, FIRST_NAME="Database Value")
        store.save_profile(self.profile_path, updated)

        self.assertEqual(manager._load_env_file(self.profile_path), self.original)

        loaded = manager.load_env(self.profile_path)

        self.assertEqual(loaded, updated)
        self.assertEqual(manager._load_env_file(self.profile_path), updated)

    def test_load_returns_database_data_when_export_repair_fails(self):
        updated = dict(self.original, FIRST_NAME="Database Value")
        store.save_profile(self.profile_path, updated)

        with patch.object(
            manager,
            "_save_env_file",
            side_effect=OSError("simulated repair failure"),
        ):
            with patch("builtins.print") as mocked_print:
                loaded = manager.load_env(self.profile_path)

        self.assertEqual(loaded, updated)
        self.assertEqual(manager._load_env_file(self.profile_path), self.original)
        self.assertIn("repair failed", str(mocked_print.call_args).lower())


if __name__ == "__main__":
    unittest.main()
