from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.profiles import manager, store


class ProfileManagerDeleteTests(unittest.TestCase):
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
        manager.SEQUENCE_FILE = self.root / "profiles" / "profile_sequence.txt"
        manager.PROFILES_DIR.mkdir(parents=True)
        store.initialize()

        self.profile_path = manager.PROFILES_DIR / "profile01.env"
        self.values = {
            "PROFILE_ID": "1",
            "PROFILE_NAME": "Delete Test",
            "FIRST_NAME": "Test",
        }
        manager.save_env(self.profile_path, self.values)

    def tearDown(self):
        store.DB_PATH = self.old_db_path
        manager.APP_DIR = self.old_app_dir
        manager.PROFILES_DIR = self.old_profiles_dir
        manager.SEQUENCE_FILE = self.old_sequence_file
        self.tmp.cleanup()

    def test_database_failure_keeps_legacy_profile_file(self):
        with patch("builtins.input", return_value="y"), \
             patch.object(store, "delete_profile", side_effect=RuntimeError("simulated database failure")):
            manager.remove_profile(1)

        self.assertTrue(self.profile_path.exists())
        self.assertEqual(manager._load_env_file(self.profile_path), self.values)
        self.assertEqual(store.load_profile(1), self.values)


    def test_legacy_file_delete_failure_is_reported(self):
        with patch("builtins.input", return_value="y"), \
             patch.object(Path, "unlink", side_effect=OSError("simulated filesystem failure")), \
             patch("builtins.print") as mocked_print:
            manager.remove_profile(1)

        self.assertIsNone(store.load_profile(1))
        self.assertTrue(self.profile_path.exists())
        messages = " ".join(str(call) for call in mocked_print.call_args_list)
        self.assertIn("unable to remove legacy file", messages.lower())
        self.assertIn("Legacy profile file retained", messages)


if __name__ == "__main__":
    unittest.main()
