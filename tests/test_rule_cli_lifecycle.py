import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pdfunlocker.cli import main as cli
from pdfunlocker.rules import manager


class RuleCliLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rules_dir = Path(self.temp.name) / "rules"
        self.rules_dir.mkdir()
        self.patch_rules = patch.object(manager, "RULES_DIR", self.rules_dir)
        self.patch_rules.start()

    def tearDown(self):
        self.patch_rules.stop()
        self.temp.cleanup()

    def run_cli(self, *args):
        with patch("sys.argv", ["pdfunlocker", *args]):
            cli.main()

    def test_create_modify_and_remove_rule_through_cli(self):
        parts = [manager.FieldPart("001"), manager.FieldPart("002")]

        # CREATE through the real CLI parser and command handler.
        with patch.object(
            manager, "_prompt_required", return_value="CLI lifecycle test"
        ), patch.object(
            manager, "_prompt_optional",
            side_effect=["test", "Z"],
        ), patch.object(
            manager, "_prompt_field_parts", return_value=parts
        ):
            self.run_cli("rules", "add")

        rule_path = self.rules_dir / "rule00001.yml"
        self.assertTrue(rule_path.is_file())
        created = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        self.assertEqual(created["rule"]["number"], "00001")
        self.assertEqual(created["rule"]["id"], "00001")
        self.assertEqual(created["transform"], {"cases": ["capitalize", "upper", "lower"]})
        self.assertEqual(
            [item["field_id"] for item in created["pattern"]["fields"]],
            ["001", "002"],
        )

        # MODIFY the same rule through the real CLI.
        with patch.object(
            manager, "_prompt_optional",
            side_effect=["00001", "Modified by CLI", "test", "Z"],
        ), patch.object(
            manager, "_prompt_existing_parts", return_value=parts
        ):
            self.run_cli("rules", "modify", "00001")

        modified = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        self.assertEqual(modified["rule"]["name"], "Modified by CLI")
        self.assertEqual(modified["transform"], {"cases": ["capitalize", "upper", "lower"]})
        self.assertEqual(len(list(self.rules_dir.glob("rule*.yml"))), 1)

        # REMOVE confirms and archives; it must not permanently delete the rule.
        with patch("builtins.input", return_value="y"):
            self.run_cli("rules", "remove", "00001")

        self.assertFalse(rule_path.exists())
        archived = list(self.rules_dir.glob("archive-*/rule00001.yml"))
        self.assertEqual(len(archived), 1)
        archived_data = yaml.safe_load(archived[0].read_text(encoding="utf-8"))
        self.assertEqual(archived_data["rule"]["id"], "00001")
        self.assertEqual(archived_data["transform"], {"cases": ["capitalize", "upper", "lower"]})
        self.assertIn("00001", manager._all_used_ids())


if __name__ == "__main__":
    unittest.main()
