import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.pdf.candidates import generate_rule_candidates
from pdfunlocker.rules.manager import FieldPart, Rule


class MultiCaseCandidateTests(unittest.TestCase):
    def make_rule(self, fields, cases=("raw", "lower", "upper")):
        return Rule(
            number="99999",
            rule_id="99999",
            name="Isolated candidate test",
            category="Test",
            priority="Z",
            components=(),
            case=cases[0],
            path=Path("/tmp/nonexistent-test-rule.yml"),
            fields=tuple(fields),
            cases=tuple(cases),
        )

    def registry(self, multiple=False):
        return [
            {
                "field_number": 1,
                "field_key": "FIRST_NAME",
                "label": "First name",
                "allows_multiple": False,
                "archived": False,
            },
            {
                "field_number": 2,
                "field_key": "MOBILE",
                "label": "Mobile",
                "allows_multiple": multiple,
                "archived": False,
            },
        ]

    def test_combines_fields_and_generates_all_case_variants(self):
        rule = self.make_rule([
            FieldPart("001", "first", 3),
            FieldPart("002", "last", 4),
        ])
        profile = {"FIRST_NAME": "Example", "MOBILE": "9876543210"}

        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=self.registry(),
        ):
            candidates, message = generate_rule_candidates(rule, profile)

        self.assertEqual(
            [item.password for item in candidates],
            ["Exa3210", "exa3210", "EXA3210"],
        )
        self.assertEqual(message, "3 candidate(s)")

    def test_repeatable_values_are_combined_with_case_variants(self):
        rule = self.make_rule([
            FieldPart("001"),
            FieldPart("002", "last", 2),
        ])
        profile = {
            "FIRST_NAME": "Example",
            "MOBILE_1": "1234",
            "MOBILE_02": "5678",
        }

        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=self.registry(multiple=True),
        ):
            candidates, _ = generate_rule_candidates(rule, profile)

        self.assertEqual(
            [item.password for item in candidates],
            [
                "Example34", "example34", "EXAMPLE34",
                "Example78", "example78", "EXAMPLE78",
            ],
        )

    def test_duplicate_variants_are_deduplicated(self):
        rule = self.make_rule(
            [FieldPart("001", "first", 3)],
            cases=("raw", "lower", "upper"),
        )

        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=self.registry(),
        ):
            candidates, _ = generate_rule_candidates(
                rule, {"FIRST_NAME": "ABC"}
            )

        self.assertEqual(
            [item.password for item in candidates],
            ["ABC", "abc"],
        )

    def test_candidate_limit_is_respected(self):
        rule = self.make_rule([
            FieldPart("001"),
            FieldPart("002"),
        ])
        profile = {
            "FIRST_NAME": "A",
            **{f"MOBILE_{index}": f"{index:03d}" for index in range(1, 61)},
        }

        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=self.registry(multiple=True),
        ):
            candidates, message = generate_rule_candidates(
                rule, profile, max_candidates=100
            )

        self.assertEqual(len(candidates), 100)
        self.assertEqual(message, "100 candidate(s)")

    def test_unknown_field_returns_missing_value_message(self):
        rule = self.make_rule([FieldPart("999")])

        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=self.registry(),
        ):
            candidates, message = generate_rule_candidates(rule, {})

        self.assertEqual(candidates, [])
        self.assertEqual(message, "missing profile value for field '999'")


if __name__ == "__main__":
    unittest.main()
