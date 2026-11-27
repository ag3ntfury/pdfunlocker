import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.cli import main as installer
from pdfunlocker.profiles import store


class ProfileInstallerStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / ".pdfunlocker"
        self.database = self.install / "database" / "pdfunlocker.db"
        self.config = self.install / "config" / "settings.json"
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps({
            "environment": "linux",
            "setup": {
                "paths_configured": True,
                "scan_locations_configured": True,
                "completed": False,
            },
        }), encoding="utf-8")

    def test_first_profile_completes_installation(self):
        def create_profile(root=None):
            store.initialize_database(self.database)
            return store.create_profile(self.database, "Test Profile")

        with patch(
            "pdfunlocker.cli.profiles.create_profile_interactive",
            side_effect=create_profile,
        ), patch(
            "pdfunlocker.cli.profiles.prompt",
            side_effect=["n", "y"],
        ):
            result = installer.run_profile_setup(self.install, self.config)

        self.assertEqual(result, 0)
        settings = json.loads(self.config.read_text())
        self.assertTrue(settings["setup"]["profile_configured"])
        self.assertTrue(settings["setup"]["completed"])
        self.assertEqual(len(store.list_profiles(self.database)), 1)

    def test_existing_profile_is_reused_without_duplicate(self):
        store.initialize_database(self.database)
        existing_id = store.create_profile(self.database, "Existing")

        with patch(
            "pdfunlocker.cli.profiles.create_profile_interactive",
        ) as create, patch(
            "pdfunlocker.cli.profiles.prompt",
            side_effect=["n", "y"],
        ):
            result = installer.run_profile_setup(self.install, self.config)

        self.assertEqual(result, 0)
        create.assert_not_called()
        profiles = store.list_profiles(self.database)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["profile_id"], existing_id)

    def test_disabled_only_profiles_do_not_complete_installation(self):
        store.initialize_database(self.database)
        profile_id = store.create_profile(self.database, "Disabled")
        store.set_profile_enabled(self.database, profile_id, False)

        result = installer.run_profile_setup(self.install, self.config)

        self.assertEqual(result, 1)
        settings = json.loads(self.config.read_text())
        self.assertFalse(settings["setup"].get("completed", False))
        self.assertFalse(settings["setup"].get("profile_configured", False))

    def test_cancelled_first_profile_keeps_installation_incomplete(self):
        with patch(
            "pdfunlocker.cli.profiles.create_profile_interactive",
            return_value=None,
        ):
            result = installer.run_profile_setup(self.install, self.config)

        self.assertEqual(result, 1)
        self.assertEqual(store.list_profiles(self.database), [])
        settings = json.loads(self.config.read_text())
        self.assertFalse(settings["setup"].get("completed", False))


    def test_unconfirmed_execution_order_keeps_existing_order_and_completes_setup(self):
        store.initialize_database(self.database)
        store.create_profile(self.database, "Existing")

        with patch(
            "pdfunlocker.cli.profiles.prompt",
            return_value="no",
        ):
            result = installer.run_profile_setup(self.install, self.config)

        self.assertEqual(result, 0)

        profiles = store.list_profiles(self.database)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Existing")
        self.assertEqual(profiles[0]["execution_order"], 1)

        settings = json.loads(self.config.read_text())
        self.assertTrue(settings["setup"].get("completed", False))
        self.assertTrue(settings["setup"].get("profile_configured", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
