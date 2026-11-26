"""Tests for secure PDF password candidate generation."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from pdfunlocker.learning.candidates import (
    generate_candidates,
)
from pdfunlocker.learning.database import (
    initialize_learning_database,
)
from pdfunlocker.profiles.store import (
    create_profile,
    set_profile_value,
)


class LearningCandidateTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.database = self.root / "database" / "learning.db"
        self.template = (
            Path("templates/profile/default_profile_template.yml")
        )
        self.rules = self.root / "rules"
        self.rules.mkdir()

        self.key = self.root / "private" / "candidate_hmac.key"

        initialize_learning_database(self.database)

        self.profile = create_profile(
            self.database, "Candidate Test"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_rule(
        self,
        rule_id="00001",
        fields=None,
        cases=None,
        status="active",
    ):
        if fields is None:
            fields = [
                {
                    "field_id": "1002",
                    "slice": {"mode": "full"},
                }
            ]

        if cases is None:
            cases = ["lower", "upper", "raw"]

        data = {
            "rule": {
                "id": rule_id,
                "name": "Candidate test",
                "category": "test",
            },
            "pattern": {"fields": fields},
            "transform": {"cases": cases},
            "status": status,
        }

        path = self.rules / f"rule{rule_id}.yml"
        path.write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

    def set_value(self, field_id, value):
        return set_profile_value(
            self.database,
            self.template,
            self.profile,
            field_id,
            value,
        )

    def generate(self, rule_id="00001"):
        return generate_candidates(
            self.database,
            self.template,
            self.rules,
            self.profile,
            rule_id,
            self.key,
        )

    def test_public_synthetic_fixture_generates_expected_candidates(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "public_test_profile"
            / "profile.yml"
        )
        fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))

        self.assertTrue(fixture["profile"]["synthetic"])
        self.assertEqual(
            fixture["profile"]["purpose"],
            "automated-testing-only",
        )

        # This profile is created only in this test's temporary database.
        profile_id = create_profile(
            self.database,
            fixture["profile"]["name"],
        )

        for field_id, field_values in fixture["values"].items():
            values = field_values if isinstance(field_values, list) else [field_values]
            for value in values:
                set_profile_value(
                    self.database,
                    self.template,
                    profile_id,
                    str(field_id),
                    value,
                )

        source_rule = (
            Path(__file__).resolve().parents[1]
            / "rules"
            / "rule00000.yml"
        )
        shutil.copy2(source_rule, self.rules / "rule00000.yml")

        result = generate_candidates(
            self.database,
            self.template,
            self.rules,
            profile_id,
            "00000",
            self.key,
        )

        self.assertEqual(
            [item["value"] for item in result["candidates"]],
            ["alex1995", "ALEX1995", "Alex1995"],
        )


    def test_generates_lower_upper_and_raw(self):
        self.set_value("1002", "RuPeSh")

        self.write_rule()

        result = self.generate()

        self.assertEqual(
            [item["value"] for item in result["candidates"]],
            ["rupesh", "RUPESH", "RuPeSh"],
        )

    def test_first_and_last_slicing(self):
        self.set_value("1002", "Rupesh")
        self.set_value("1008", "9876543210")

        self.write_rule(
            fields=[
                {
                    "field_id": "1002",
                    "slice": {"mode": "first", "count": 4},
                },
                {
                    "field_id": "1008",
                    "slice": {"mode": "last", "count": 4},
                },
            ],
            cases=["raw"],
        )

        result = self.generate()

        self.assertEqual(
            [item["value"] for item in result["candidates"]],
            ["Rupe3210"],
        )

    def test_full_slice(self):
        self.set_value("1005", "11022000")

        self.write_rule(
            fields=[
                {
                    "field_id": "1005",
                    "slice": {"mode": "full"},
                }
            ],
            cases=["raw"],
        )

        self.assertEqual(
            self.generate()["candidates"][0]["value"],
            "11022000",
        )

    def test_multiple_values_are_combined_in_order(self):
        self.set_value("1002", "Rupesh")
        self.set_value("1008", "1111111111")
        self.set_value("1008", "2222222222")

        self.write_rule(
            fields=[
                {
                    "field_id": "1002",
                    "slice": {"mode": "first", "count": 2},
                },
                {
                    "field_id": "1008",
                    "slice": {"mode": "last", "count": 2},
                },
            ],
            cases=["raw"],
        )

        result = self.generate()

        self.assertEqual(
            [item["value"] for item in result["candidates"]],
            ["Ru11", "Ru22"],
        )

    def test_multiple_multiple_fields_use_cartesian_combinations(self):
        self.set_value("1008", "1111111111")
        self.set_value("1008", "2222222222")
        self.set_value("1009", "one@example.com")
        self.set_value("1009", "two@example.com")

        self.write_rule(
            fields=[
                {
                    "field_id": "1008",
                    "slice": {"mode": "last", "count": 1},
                },
                {
                    "field_id": "1009",
                    "slice": {"mode": "first", "count": 3},
                },
            ],
            cases=["raw"],
        )

        result = self.generate()

        self.assertEqual(
            [item["value"] for item in result["candidates"]],
            ["1one", "1two", "2one", "2two"],
        )

    def test_duplicate_candidates_are_removed_preserving_order(self):
        self.set_value("1002", "RUPESH")

        self.write_rule(
            fields=[
                {
                    "field_id": "1002",
                    "slice": {"mode": "full"},
                }
            ],
            cases=["lower", "upper", "raw"],
        )

        result = self.generate()

        self.assertEqual(
            [item["value"] for item in result["candidates"]],
            ["rupesh", "RUPESH"],
        )

    def test_missing_field_returns_empty_candidate_set(self):
        self.write_rule()

        result = self.generate()

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["candidates"], [])

    def test_inactive_rule_rejected(self):
        self.set_value("1002", "Rupesh")
        self.write_rule(status="inactive")

        with self.assertRaisesRegex(ValueError, "inactive"):
            self.generate()

    def test_unknown_field_rejected(self):
        self.write_rule(
            fields=[
                {
                    "field_id": "9999",
                    "slice": {"mode": "full"},
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "Unknown profile field"):
            self.generate()

    def test_invalid_slice_count_rejected(self):
        self.set_value("1002", "Rupesh")

        self.write_rule(
            fields=[
                {
                    "field_id": "1002",
                    "slice": {"mode": "first", "count": 0},
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "positive integer"):
            self.generate()

    def test_unsupported_transform_rejected(self):
        self.set_value("1002", "Rupesh")
        self.write_rule(cases=["lower", "capitalize"])

        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.generate()

    def test_candidate_set_fingerprint_is_stable(self):
        self.set_value("1002", "Rupesh")
        self.write_rule()

        first = self.generate()
        second = self.generate()

        self.assertEqual(
            first["candidate_set_fingerprint"],
            second["candidate_set_fingerprint"],
        )

    def test_candidate_set_fingerprint_changes_with_values(self):
        self.set_value("1002", "Rupesh")
        self.write_rule()

        first = self.generate()["candidate_set_fingerprint"]

        self.set_value("1002", "Priya")

        second = self.generate()["candidate_set_fingerprint"]

        self.assertNotEqual(first, second)

    def test_candidate_fingerprints_do_not_expose_plaintext(self):
        self.set_value("1002", "SecretCandidate123")
        self.write_rule(cases=["raw"])

        result = self.generate()

        self.assertNotIn(
            "SecretCandidate123",
            result["candidates"][0]["fingerprint"],
        )

        self.assertEqual(
            len(result["candidates"][0]["fingerprint"]),
            64,
        )

    def test_hmac_key_is_created_with_restrictive_permissions(self):
        self.set_value("1002", "Rupesh")
        self.write_rule()

        self.generate()

        self.assertTrue(self.key.is_file())
        self.assertEqual(len(self.key.read_bytes()), 32)
        self.assertEqual(
            os.stat(self.key).st_mode & 0o777,
            0o600,
        )

    def test_invalid_hmac_key_length_rejected(self):
        self.key.parent.mkdir(parents=True)
        self.key.write_bytes(b"short")

        self.set_value("1002", "Rupesh")
        self.write_rule()

        with self.assertRaisesRegex(ValueError, "invalid length"):
            self.generate()

    def test_key_change_changes_candidate_fingerprint(self):
        self.set_value("1002", "Rupesh")
        self.write_rule()

        first = self.generate()["candidate_set_fingerprint"]

        self.key.write_bytes(b"x" * 32)
        os.chmod(self.key, 0o600)

        second = self.generate()["candidate_set_fingerprint"]

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
