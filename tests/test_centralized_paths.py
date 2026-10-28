import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker import paths
from pdfunlocker.database import manager as database_manager


class CentralizedPathTests(unittest.TestCase):
    def test_configured_path_uses_configured_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "config.json"
            configured = root / "custom-database"
            config_file.write_text(
                json.dumps({"database_directory": str(configured)}),
                encoding="utf-8",
            )

            with patch.object(paths, "CONFIG_FILE", config_file):
                result = paths.configured_path(
                    "database_directory", root / "default"
                )

            self.assertEqual(result, configured)

    def test_invalid_config_uses_default_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "config.json"
            config_file.write_text("{invalid", encoding="utf-8")

            with patch.object(paths, "CONFIG_FILE", config_file):
                result = paths.configured_path(
                    "database_directory", root / "default"
                )

            self.assertEqual(result, root / "default")

    def test_database_path_uses_central_database_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured = Path(tmp) / "database"

            with patch.object(paths, "DATABASE_DIR", configured):
                result = database_manager.database_path()

            self.assertEqual(result, configured / "pdfunlocker.sqlite3")
            self.assertTrue(configured.is_dir())


if __name__ == "__main__":
    unittest.main()
