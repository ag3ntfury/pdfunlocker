"""Integration tests for the per-rule unique candidate ceiling."""
import tempfile
import unittest
from pathlib import Path

import yaml

from pdfunlocker.learning.candidates import (
    MAX_CANDIDATES_PER_RULE,
    CandidateLimitExceeded,
    generate_candidates,
)
from pdfunlocker.learning.database import connect, initialize_learning_database
from pdfunlocker.profiles.store import create_profile


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/profile/default_profile_template.yml"


class CandidateLimitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "database" / "test.db"
        self.rules = self.root / "rules"
        self.rules.mkdir()
        self.key = self.root / "private" / "candidate.key"
        initialize_learning_database(self.db)
        self.profile = create_profile(self.db, "Candidate Limit")
        self.write_rule()

    def tearDown(self):
        self.temp.cleanup()

    def write_rule(self):
        rule = {
            "rule": {"id": "00001", "name": "limit", "category": "test"},
            "pattern": {"fields": [
                {"field_id": "1008", "slice": {"mode": "full"}}
            ]},
            "transform": {"cases": ["raw"]},
            "status": "active",
        }
        (self.rules / "rule00001.yml").write_text(
            yaml.safe_dump(rule), encoding="utf-8"
        )

    def add_values(self, count):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.db) as db:
            db.executemany("""
                INSERT INTO profile_values (
                    profile_id, value_id, field_id, value,
                    value_order, created_at, updated_at
                ) VALUES (?, ?, '1008', ?, ?, ?, ?)
            """, [
                (
                    self.profile,
                    f"1008_{i}",
                    f"candidate-{i:05d}",
                    i,
                    now,
                    now,
                )
                for i in range(1, count + 1)
            ])

    def generate(self):
        return generate_candidates(
            self.db, TEMPLATE, self.rules,
            self.profile, "00001", self.key,
        )

    def test_exactly_ten_thousand_unique_candidates_are_allowed(self):
        self.add_values(MAX_CANDIDATES_PER_RULE)
        result = self.generate()
        self.assertEqual(result["count"], MAX_CANDIDATES_PER_RULE)

    def test_ten_thousand_and_one_candidate_rejects_entire_rule(self):
        self.add_values(MAX_CANDIDATES_PER_RULE + 1)
        with self.assertRaises(CandidateLimitExceeded) as caught:
            self.generate()
        self.assertEqual(caught.exception.limit, MAX_CANDIDATES_PER_RULE)
        self.assertNotIn("candidate-", str(caught.exception).lower())

    def test_exception_does_not_include_candidate_plaintext(self):
        error = CandidateLimitExceeded()
        self.assertEqual(error.limit, MAX_CANDIDATES_PER_RULE)
        self.assertNotIn("password", str(error).lower())


if __name__ == "__main__":
    unittest.main()
