import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.profiles import manager, store


class TestProfileIdAllocation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.profiles_dir = self.root / "profiles"
        self.profiles_dir.mkdir()
        self.sequence_file = self.profiles_dir / "profile_sequence.txt"
        self.database = self.root / "profiles.sqlite3"

        self.patches = [
            patch.object(manager, "APP_DIR", self.root),
            patch.object(manager, "PROFILES_DIR", self.profiles_dir),
            patch.object(manager, "SEQUENCE_FILE", self.sequence_file),
            patch.object(store, "DB_PATH", self.database),
        ]
        for item in self.patches:
            item.start()

        store.initialize()
        store.save_profile(self.profiles_dir / "profile14.env", {
            "PROFILE_ID": "14",
            "PROFILE_NAME": "Temporary allocation test",
        })

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_missing_sequence_uses_next_id_after_existing_profiles(self):
        self.assertFalse(self.sequence_file.exists())
        self.assertEqual(manager.next_profile_id(), 15)

    def test_corrupted_sequence_uses_next_id_after_existing_profiles(self):
        self.sequence_file.write_text("not-a-number\n", encoding="utf-8")
        self.assertEqual(manager.next_profile_id(), 15)

    def test_stale_sequence_uses_next_id_after_existing_profiles(self):
        self.sequence_file.write_text("3\n", encoding="utf-8")
        self.assertEqual(manager.next_profile_id(), 15)

    def test_correct_sequence_allocates_next_id(self):
        self.sequence_file.write_text("14\n", encoding="utf-8")
        self.assertEqual(manager.next_profile_id(), 15)

    def test_deleted_id_is_not_reused_after_sequence_file_is_lost(self):
        self.sequence_file.write_text("14\n", encoding="utf-8")
        allocated_id = manager.next_profile_id()
        self.assertEqual(allocated_id, 15)

        store.save_profile(self.profiles_dir / f"profile{allocated_id:02d}.env", {
            "PROFILE_ID": str(allocated_id),
            "PROFILE_NAME": "Temporary second test profile",
        })
        store.delete_profile(allocated_id)
        self.sequence_file.unlink()

        self.assertEqual(manager.next_profile_id(), 16)


if __name__ == "__main__":
    unittest.main()
