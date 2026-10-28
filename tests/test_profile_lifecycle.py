from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pdfunlocker.profiles import manager, store


class ProfileLifecycleTests(unittest.TestCase):
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

    def tearDown(self):
        store.DB_PATH = self.old_db_path
        manager.APP_DIR = self.old_app_dir
        manager.PROFILES_DIR = self.old_profiles_dir
        manager.SEQUENCE_FILE = self.old_sequence_file
        self.tmp.cleanup()

    def test_create_load_modify_reload_and_delete_profile(self):
        path = manager.profile_path(1)
        original = {
            "PROFILE_ID": "1",
            "PROFILE_NAME": "Lifecycle Test",
            "FIRST_NAME": "Original",
            "MOBILE_01": "+919876543210",
        }

        # Create and persist a profile in isolated temporary storage.
        manager.save_env(path, original)
        self.assertTrue(path.is_file())
        self.assertEqual(store.load_profile(1), original)
        self.assertEqual(manager.load_env(path), original)

        # Modify and verify both SQLite and the legacy export.
        updated = dict(original, FIRST_NAME="Updated", EMAIL_01="test@example.invalid")
        manager.save_env(path, updated)
        self.assertEqual(store.load_profile(1), updated)
        self.assertEqual(manager._load_env_file(path), updated)
        self.assertEqual(manager.load_env(path), updated)

        # Delete and verify the profile is gone from SQLite.
        store.delete_profile(1)
        self.assertIsNone(store.load_profile(1))

        # This test deletes only its temporary export.
        path.unlink()
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
