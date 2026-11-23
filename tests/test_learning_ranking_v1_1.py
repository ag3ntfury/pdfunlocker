"""Focused acceptance tests for staged global ranking v1.1."""
import tempfile
import unittest
from pathlib import Path
import yaml
from pdfunlocker.learning.database import connect, initialize_learning_database
from pdfunlocker.learning.ranking import (
    get_completed_rule_statistics, get_global_completed_pdf_count,
    get_rule_ranking,
)
from pdfunlocker.profiles.store import create_profile
from pdfunlocker.scanner import utc_now


class StagedRankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "db.sqlite"
        self.rules = self.root / "rules"
        self.rules.mkdir()
        initialize_learning_database(self.db)
        self.p1 = create_profile(self.db, "One")
        self.p2 = create_profile(self.db, "Two")
        self.now = utc_now()
        for rid in ("00010", "00020", "00030"):
            data = {"rule":{"id":rid,"name":rid,"category":"test"},
                    "pattern":{"fields":[]},
                    "transform":{"cases":["raw"]},"status":"active"}
            (self.rules / f"rule{rid}.yml").write_text(
                yaml.safe_dump(data), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def add_batch(self, profile, number, hashes):
        with connect(self.db) as db:
            db.execute("""INSERT INTO learning_batches
                (profile_id,batch_number,status,created_at,completed_at)
                VALUES (?,?,'completed',?,?)""",
                (profile, number, self.now, self.now))
            for i, sha in enumerate(hashes, 1):
                db.execute("""INSERT OR IGNORE INTO documents
                    (sha256,file_size,encryption_status,processing_status,
                     first_seen_at,last_seen_at)
                    VALUES (?,100,'encrypted','pending',?,?)""",
                    (sha,self.now,self.now))
                db.execute("""INSERT OR IGNORE INTO learning_batch_files
                    (profile_id,sha256,batch_number,file_order,state,
                     assigned_at,completed_at)
                    VALUES (?,?,?,?,'locked',?,?)""",
                    (profile,sha,number,i,self.now,self.now))

    def add_run(self, profile, sha, rule, outcome):
        with connect(self.db) as db:
            db.execute("""INSERT INTO rule_runs
                (sha256,profile_id,rule_id,rule_fingerprint,
                 candidate_set_fingerprint,batch_number,outcome,
                 attempted_count,started_at,completed_at)
                VALUES (?,?,?,'rfp','cfp',1,?,1,?,?)""",
                (sha,profile,rule,outcome,self.now,self.now))

    def test_global_threshold_deduplicates_across_profiles(self):
        shas = [f"{i:064x}" for i in range(1,51)]
        self.add_batch(self.p1,1,shas)
        self.add_batch(self.p2,1,shas)
        self.assertEqual(get_global_completed_pdf_count(self.db),50)

    def test_switches_to_rate_at_100(self):
        a = [f"{i:064x}" for i in range(1,51)]
        b = [f"{i:064x}" for i in range(51,101)]
        self.add_batch(self.p1,1,a)
        self.add_batch(self.p2,1,b)
        for sha in a[:9]: self.add_run(self.p1,sha,"00010","success")
        self.add_run(self.p1,a[9],"00010","exhausted")
        for sha in a: self.add_run(self.p1,sha,"00020","success")
        for sha in b: self.add_run(self.p2,sha,"00020","exhausted")
        result = get_rule_ranking(self.db,self.rules)
        self.assertEqual(result[0]["ranking_method"],"success_rate")
        self.assertEqual(result[0]["global_completed_pdfs"],100)
        self.assertEqual(result[0]["rule_id"],"00010")

    def test_before_100_uses_success_count(self):
        shas = [f"{i:064x}" for i in range(1,11)]
        self.add_batch(self.p1,1,shas)
        for sha in shas[:3]: self.add_run(self.p1,sha,"00010","success")
        for sha in shas[:2]: self.add_run(self.p1,sha,"00020","success")
        result = get_rule_ranking(self.db,self.rules)
        self.assertEqual(result[0]["ranking_method"],"success_count")
        self.assertEqual(result[0]["rule_id"],"00010")

    def test_error_is_not_in_rate_denominator(self):
        shas = ["a"*64,"b"*64]
        self.add_batch(self.p1,1,shas)
        self.add_run(self.p1,shas[0],"00010","success")
        self.add_run(self.p1,shas[1],"00010","error")
        stats = get_completed_rule_statistics(self.db)
        self.assertEqual(stats["00010"]["attempted_files"],1)
        self.assertEqual(stats["00010"]["success_rate"],1.0)

    def test_no_candidates_and_skipped_are_excluded(self):
        shas = ["a"*64,"b"*64,"c"*64]
        self.add_batch(self.p1,1,shas)
        self.add_run(self.p1,shas[0],"00010","success")
        self.add_run(self.p1,shas[1],"00010","no_candidates")
        self.add_run(self.p1,shas[2],"00010","skipped")
        self.assertEqual(
            get_completed_rule_statistics(self.db)["00010"]["attempted_files"],1)

    def test_untested_rules_stay_in_original_order(self):
        sha = "d"*64
        self.add_batch(self.p1,1,[sha])
        self.add_run(self.p1,sha,"00020","success")
        result = get_rule_ranking(self.db,self.rules)
        self.assertEqual([x["rule_id"] for x in result],
                         ["00020","00010","00030"])
        self.assertFalse(result[1]["tested"])
        self.assertFalse(result[2]["tested"])


if __name__ == "__main__":
    unittest.main()
