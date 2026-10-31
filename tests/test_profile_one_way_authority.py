from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from pdfunlocker.profiles import manager, store


class ProfileOneWayAuthorityTests(unittest.TestCase):
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
        manager.SEQUENCE_FILE = (
            manager.PROFILES_DIR / "profile_sequence.txt"
        )

        manager.PROFILES_DIR.mkdir(parents=True)
        store.initialize()

    def tearDown(self):
        store.DB_PATH = self.old_db_path
        manager.APP_DIR = self.old_app_dir
        manager.PROFILES_DIR = self.old_profiles_dir
        manager.SEQUENCE_FILE = self.old_sequence_file
        self.tmp.cleanup()

    def create_profile(self, profile_id=1):
        path = manager.profile_path(profile_id)
        values = {
            "PROFILE_ID": str(profile_id),
            "PROFILE_NAME": f"Authority Test {profile_id}",
            "FIRST_NAME": "Database Value",
        }
        manager.save_env(path, values)
        return path, values

    def test_orphan_env_is_never_imported_into_sqlite(self):
        orphan = manager.PROFILES_DIR / "profile91.env"
        orphan.write_text(
            "PROFILE_ID=91\n"
            "PROFILE_NAME=Orphan Profile\n"
            "FIRST_NAME=Must Not Be Imported\n",
            encoding="utf-8",
        )

        loaded = manager.load_env(orphan)

        self.assertEqual(loaded, {})
        self.assertIsNone(store.load_profile(91))
        self.assertTrue(orphan.exists())
        self.assertEqual(
            manager._load_env_file(orphan)["FIRST_NAME"],
            "Must Not Be Imported",
        )

    def test_manual_env_edit_cannot_overwrite_database(self):
        path, original = self.create_profile()

        path.write_text(
            "PROFILE_ID=1\n"
            "PROFILE_NAME=Tampered Name\n"
            "FIRST_NAME=Tampered Value\n",
            encoding="utf-8",
        )

        loaded = manager.load_env(path)

        self.assertEqual(loaded, original)
        self.assertEqual(store.load_profile(1), original)
        self.assertEqual(manager._load_env_file(path), original)

    def test_missing_env_is_regenerated_from_sqlite(self):
        path, original = self.create_profile()
        path.unlink()

        self.assertFalse(path.exists())

        loaded = manager.load_env(path)

        self.assertEqual(loaded, original)
        self.assertTrue(path.is_file())
        self.assertEqual(manager._load_env_file(path), original)
        self.assertEqual(store.load_profile(1), original)

    def test_listing_and_name_lookup_work_without_env_export(self):
        path, original = self.create_profile()
        path.unlink()

        self.assertFalse(path.exists())

        names = manager.profile_names()
        self.assertEqual(names, {"authority test 1": 1})

        output = StringIO()
        with redirect_stdout(output):
            manager.list_profiles()

        displayed = output.getvalue()
        self.assertIn("Authority Test 1", displayed)
        self.assertIn("profile01.env", displayed)

        # Listing must not require the export file to exist.
        self.assertFalse(path.exists())

    def test_profile_id_allocation_ignores_orphan_env_files(self):
        orphan = manager.PROFILES_DIR / "profile999.env"
        orphan.write_text(
            "PROFILE_ID=999\n"
            "PROFILE_NAME=Orphan Profile\n",
            encoding="utf-8",
        )

        allocated = manager.next_profile_id()

        self.assertEqual(allocated, 1)
        self.assertIsNone(store.load_profile(999))
        self.assertTrue(orphan.exists())


if __name__ == "__main__":
    unittest.main()
