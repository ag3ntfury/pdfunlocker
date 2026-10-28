import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from pdfunlocker.rules import manager


class RuleManagerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.rules_dir = self.root / "rules"
        self.rules_dir.mkdir()
        self.patch_rules = patch.object(manager, "RULES_DIR", self.rules_dir)
        self.patch_rules.start()

    def tearDown(self):
        self.patch_rules.stop()
        self.temp_dir.cleanup()

    def write_rule(self, number, rule_id, priority="Z", name="Test rule"):
        path = self.rules_dir / f"rule{number}.yml"
        data = {
            "rule": {
                "number": number,
                "id": rule_id,
                "name": name,
                "category": "test",
                "priority": priority,
            },
            "pattern": {
                "fields": [
                    {
                        "field_id": "001",
                        "slice": {"mode": "full"},
                    }
                ]
            },
            "transform": {"case": "raw"},
        }
        path.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def test_new_rule_number_uses_highest_number_including_archive(self):
        self.write_rule("00003", "00003")
        archive = self.rules_dir / "archive-test"
        archive.mkdir()
        archived = archive / "rule00012.yml"
        archived.write_text(
            yaml.safe_dump({
                "rule": {"number": "00012", "id": "00012"}
            }),
            encoding="utf-8",
        )

        self.assertEqual(manager._next_rule_number(), "00013")

    def test_next_id_accounts_for_archived_stored_id(self):
        archive = self.rules_dir / "archive-mismatch"
        archive.mkdir()
        (archive / "rule00014.yml").write_text(
            yaml.safe_dump({"rule": {"number": "00014", "id": "00020"}}),
            encoding="utf-8",
        )
        self.assertEqual(manager._next_rule_number(), "00021")

    def test_rule_number_and_id_can_match_and_load(self):
        self.write_rule("00155", "00155", priority="B8")

        rules = manager.load_rules()

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].number, "00155")
        self.assertEqual(rules[0].rule_id, "00155")

    def test_priority_allocator_skips_used_priority(self):
        self.write_rule("00001", "00001", priority="B8")
        self.write_rule("00002", "00002", priority="B9")

        self.assertEqual(manager._next_available_priority("B8"), "B10")

    def test_archived_rules_are_not_active_but_reserve_ids(self):
        archive = self.rules_dir / "archive-test"
        archive.mkdir()
        archived = archive / "rule00010.yml"
        archived.write_text(
            yaml.safe_dump({
                "rule": {
                    "number": "00010",
                    "id": "00010",
                    "name": "Archived",
                    "category": "test",
                    "priority": "Z",
                },
                "pattern": {"fields": [{"field_id": "001"}]},
                "transform": {"case": "raw"},
            }),
            encoding="utf-8",
        )

        self.assertEqual(manager.load_rules(), [])
        self.assertIn("00010", manager._all_used_ids())
        self.assertEqual(manager._next_rule_number(), "00011")


    def test_z_rules_remain_visible_but_are_not_executable(self):
        self.write_rule("00001", "00001", priority="Z")
        self.write_rule("00002", "00002", priority="A1")

        self.assertEqual(
            [rule.number for rule in manager.load_rules()],
            ["00002", "00001"],
        )
        self.assertEqual(
            [rule.number for rule in manager.load_executable_rules()],
            ["00002"],
        )

    def test_malformed_archived_rule_mapping_does_not_break_id_scan(self):
        archive = self.rules_dir / "archive-malformed"
        archive.mkdir()
        (archive / "rule00003.yml").write_text(
            "rule: []\n", encoding="utf-8"
        )
        self.write_rule("00004", "00004")

        self.assertEqual(manager._next_rule_number(), "00005")

    def test_noncanonical_priorities_are_rejected(self):
        for priority in ("A01", "W00", "X0", "X01", "Z1"):
            with self.subTest(priority=priority):
                with self.assertRaises(manager.RuleError):
                    manager._priority_key(priority)

    def test_unlimited_x_priority_is_supported(self):
        self.assertEqual(manager._priority_key("X11"), (23, 11))
        self.assertEqual(manager._priority_key("X100000"), (23, 100000))


    def test_next_x_priority_is_not_capped_at_99999(self):
        self.write_rule("00001", "00001", priority="X99999")
        self.assertEqual(manager._next_available_priority("X99999"), "X100000")

    def test_list_rules_displays_only_one_rule_identifier(self):
        self.write_rule("00001", "00001", priority="A1")
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as output:
            manager.list_rules()
        text = output.getvalue()
        self.assertIn("RULE", text)
        header = text.splitlines()[2]
        self.assertNotIn("NUMBER", header)
        self.assertNotIn("ID", header)


    def test_modify_preserves_existing_case_variants_without_prompt(self):
        path = self.write_rule("00001", "00001", priority="A1")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["transform"] = {"cases": ["raw", "lower", "upper"]}
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        parts = [manager.FieldPart("001")]
        answers = iter(["00001", "Renamed", "test", "A1"])

        with patch.object(
            manager, "_prompt_optional",
            side_effect=lambda *args, **kwargs: next(answers),
        ) as optional_prompt, patch.object(
            manager, "_prompt_existing_parts", return_value=parts
        ):
            manager.modify_rule("00001")

        updated = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(
            updated["transform"]["cases"], ["raw", "lower", "upper"]
        )
        self.assertEqual(
            [call.args[0] for call in optional_prompt.call_args_list],
            ["Rule ID", "Rule name", "Category", "Priority (Z or A1-Xn)"],
        )


    def test_add_rule_retries_invalid_priority(self):
        answers = iter(["Retry test", "test", "Y2", "A1"])
        with patch.object(manager, "_prompt_required", side_effect=lambda *a, **k: next(answers)), \
             patch.object(manager, "_prompt_optional", side_effect=lambda *a, **k: next(answers)), \
             patch.object(manager, "_prompt_field_parts", return_value=[manager.FieldPart("001")]), \
             patch("builtins.print") as printed:
            manager.add_rule()

        rule_path = self.rules_dir / "rule00001.yml"
        self.assertTrue(rule_path.is_file())
        data = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
        self.assertEqual(data["rule"]["priority"], "A1")
        self.assertTrue(any("Invalid priority" in str(call) for call in printed.call_args_list))

    def test_existing_rule_file_is_never_overwritten(self):
        path = self.write_rule("00001", "00001")
        original = path.read_text(encoding="utf-8")

        with self.assertRaises(manager.RuleError):
            manager._write_rule(
                "00001",
                "00001",
                "Replacement",
                "test",
                "Z",
                [manager.FieldPart("001")],
                "raw",
            )

        self.assertEqual(path.read_text(encoding="utf-8"), original)


    def test_default_rules_are_sorted_by_numeric_rule_number(self):
        self.write_rule("00010", "default10", priority="Z")
        self.write_rule("00002", "default2", priority="Z")
        self.write_rule("00001", "normal1", priority="A1")

        defaults = manager.load_default_rules()

        self.assertEqual([rule.number for rule in defaults], ["00002", "00010"])
        self.assertEqual([rule.number for rule in manager.load_executable_rules()], ["00001"])


if __name__ == "__main__":
    unittest.main()
