import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pdfunlocker.rules import manager


class RuleCreationDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rules_dir = Path(self.temp.name) / "rules"
        self.rules_dir.mkdir()
        self.patch_rules = patch.object(manager, "RULES_DIR", self.rules_dir)
        self.patch_rules.start()

    def tearDown(self):
        self.patch_rules.stop()
        self.temp.cleanup()

    def run_add_rule(self):
        # Only category and priority are optional prompts; no case prompt.
        answers = iter(["test", "Z"])
        parts = [manager.FieldPart("001"), manager.FieldPart("002")]

        with patch.object(
            manager, "_prompt_required", return_value="Name and mobile"
        ), patch.object(
            manager, "_prompt_optional",
            side_effect=lambda *a, **k: next(answers),
        ) as optional_prompt, patch.object(
            manager, "_prompt_field_parts", return_value=parts
        ):
            manager.add_rule()

        self.assertEqual(
            [call.args[0] for call in optional_prompt.call_args_list],
            ["Category", "Priority (A1-W10, X1-Xn, or Z)"],
        )
        path = self.rules_dir / "rule00001.yml"
        self.assertTrue(path.is_file())
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_new_rule_defaults_to_raw_without_transform_prompt(self):
        data = self.run_add_rule()
        self.assertEqual(data["rule"]["number"], "00001")
        self.assertEqual(data["rule"]["id"], "00001")
        self.assertEqual(data["transform"], {"cases": ["capitalize", "upper", "lower"]})
        self.assertEqual(
            [item["field_id"] for item in data["pattern"]["fields"]],
            ["001", "002"],
        )
        self.assertEqual(len(list(self.rules_dir.glob("rule*.yml"))), 1)


if __name__ == "__main__":
    unittest.main()
