import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.pdf.candidates import generate_rule_candidates
from pdfunlocker.rules.manager import FieldPart, Rule


class CandidateHardeningTests(unittest.TestCase):
    def setUp(self):
        self.rule = Rule(
            number="99999",
            rule_id="99999",
            name="Isolated hard test",
            category="Test",
            priority="A1",
            components=(),
            case="raw",
            path=Path("/tmp/nonexistent-candidate-hard-test.yml"),
            fields=(FieldPart("001"),),
            cases=("raw", "lower", "upper"),
        )
        self.registry = [{
            "field_number": 1,
            "field_key": "FIRST_NAME",
            "label": "First name",
            "allows_multiple": False,
            "archived": False,
        }]

    def generate(self, profile, limit=100):
        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=self.registry,
        ):
            return generate_rule_candidates(
                self.rule, profile, max_candidates=limit
            )

    def test_zero_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.generate({"FIRST_NAME": "Rupesh"}, 0)

    def test_negative_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.generate({"FIRST_NAME": "Rupesh"}, -1)

    def test_boolean_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.generate({"FIRST_NAME": "Rupesh"}, True)

    def test_non_integer_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.generate({"FIRST_NAME": "Rupesh"}, 1.5)

    def test_positive_limit_caps_candidates(self):
        candidates, _ = self.generate({"FIRST_NAME": "Rupesh"}, 2)
        self.assertEqual(
            [candidate.password for candidate in candidates],
            ["Rupesh", "rupesh"],
        )

    def test_missing_field_returns_no_candidates(self):
        candidates, message = self.generate({})
        self.assertEqual(candidates, [])
        self.assertEqual(message, "missing profile value for field '001'")


if __name__ == "__main__":
    unittest.main()


    def test_default_generation_is_not_capped_at_100(self):
        profile = {"FIRST_NAME": "Rupesh"}
        with patch(
            "pdfunlocker.profiles.store.list_fields",
            return_value=[{
                "field_number": 1,
                "field_key": "FIRST_NAME",
                "label": "First name",
                "allows_multiple": True,
                "archived": False,
            }],
        ):
            from pdfunlocker.pdf.candidates import generate_rule_candidates
            values = {
                **profile,
                **{f"FIRST_NAME_{i}": f"Value{i:03d}" for i in range(1, 151)},
            }
            candidates, message = generate_rule_candidates(self.rule, values)

        self.assertEqual(len(candidates), 151)
        self.assertEqual(message, "151 candidate(s)")
