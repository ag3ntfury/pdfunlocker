import tempfile
import unittest
from pathlib import Path

import yaml

from pdfunlocker.rules.manager import _parse_rule


class MultiCaseParserTests(unittest.TestCase):
    def parse_yaml(self, transform):
        data = {
            "rule": {
                "number": "90001",
                "id": "90001",
                "name": "Parser Test",
                "category": "test",
                "priority": "Z",
            },
            "pattern": {
                "fields": [
                    {"field_id": "001", "slice": {"mode": "full"}}
                ]
            },
            "transform": transform,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rule90001.yml"
            path.write_text(
                yaml.safe_dump(data, sort_keys=False),
                encoding="utf-8",
            )
            return _parse_rule(path)

    def test_plural_cases_are_parsed(self):
        rule = self.parse_yaml(
            {"cases": ["capitalize", "upper", "lower"]}
        )
        self.assertEqual(tuple(rule.cases), ("capitalize", "upper", "lower"))

    def test_single_plural_case_is_parsed(self):
        rule = self.parse_yaml({"cases": ["upper"]})
        self.assertEqual(tuple(rule.cases), ("upper",))

    def test_legacy_singular_case_remains_supported(self):
        rule = self.parse_yaml({"case": "lower"})
        self.assertEqual(rule.case, "lower")
        self.assertEqual(tuple(rule.cases), ("lower",))

    def test_empty_cases_are_rejected(self):
        with self.assertRaises(Exception):
            self.parse_yaml({"cases": []})

    def test_invalid_case_is_rejected(self):
        with self.assertRaises(Exception):
            self.parse_yaml({"cases": ["raw", "unsupported"]})

    def test_duplicate_cases_are_rejected(self):
        with self.assertRaises(Exception):
            self.parse_yaml({"cases": ["raw", "raw"]})

    def test_singular_and_plural_together_are_rejected(self):
        with self.assertRaises(Exception):
            self.parse_yaml({"case": "raw", "cases": ["upper"]})

    def test_cases_must_be_a_list(self):
        with self.assertRaises(Exception):
            self.parse_yaml({"cases": "raw"})


if __name__ == "__main__":
    unittest.main()
