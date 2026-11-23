"""Acceptance tests for approved v1 PDF-level success-rate ranking."""
import tempfile
import unittest
from pathlib import Path
import yaml

from pdfunlocker.learning.database import connect, initialize_learning_database
from pdfunlocker.learning.ranking import get_rule_ranking, get_rule_order
from pdfunlocker.profiles.store import create_profile
from pdfunlocker.scanner import utc_now


class ApprovedV1RankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "learning.db"
        self.rules = self.root / "rules"
        self.rules.mkdir()
        initialize_learning_database(self.db)
        self.p1 = create_profile(self.db, "Profile One")
        self.p2 = create_profile(self.db, "Profile Two")
        self.now = utc_now()
        for rid in ("00010", "00017", "00018", "00030"):
            (self.rules / f"rule{rid}.yml").write_text(yaml.safe_dump({
                "rule": {"id": rid, "name": rid}, "status": "active"
            }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def add_batch(self, profile, number, hashes, status="completed"):
        with connect(self.db) as db:
            db.execute("INSERT INTO learning_batches (profile_id,batch_number,status,created_at,completed_at) VALUES (?,?,?,?,?)",
                (profile, number, status, self.now, self.now if status == "completed" else None))
            for i, sha in enumerate(hashes, 1):
                db.execute("INSERT OR IGNORE INTO documents (sha256,file_size,encryption_status,processing_status,first_seen_at,last_seen_at) VALUES (?,100,'encrypted','pending',?,?)", (sha,self.now,self.now))
                db.execute("INSERT INTO learning_batch_files (profile_id,sha256,batch_number,file_order,state,assigned_at,completed_at) VALUES (?,?,?,?,'locked',?,?)", (profile,sha,number,i,self.now,self.now))

    def add_run(self, profile, batch, sha, rule, outcome):
        with connect(self.db) as db:
            db.execute("INSERT INTO rule_runs (sha256,profile_id,rule_id,rule_fingerprint,candidate_set_fingerprint,batch_number,outcome,attempted_count,started_at,completed_at) VALUES (?,?,?,'r','c',?,?,1,?,?)",
                (sha,profile,rule,batch,outcome,self.now,self.now))

    def test_success_rate_precedes_success_count(self):
        hashes = [f"{i:064x}" for i in range(1, 11)]
        self.add_batch(self.p1, 1, hashes)
        # 00017: 2/2 = 100%; 00010: 8/10 = 80%.
        for sha in hashes[:8]: self.add_run(self.p1,1,sha,"00010","success")
        for sha in hashes[8:]: self.add_run(self.p1,1,sha,"00010","exhausted")
        for sha in hashes[:2]: self.add_run(self.p1,1,sha,"00017","success")
        ranked = get_rule_ranking(self.db,self.rules)
        self.assertEqual([x["rule_id"] for x in ranked], ["00017","00010","00018","00030"])
        self.assertEqual(ranked[0]["success_rate"], 1.0)
        self.assertEqual(ranked[1]["success_rate"], 0.8)

    def test_ties_use_success_count_then_yaml_order(self):
        hashes = [f"{i:064x}" for i in range(1, 5)]
        self.add_batch(self.p1,1,hashes)
        for sha in hashes[:3]: self.add_run(self.p1,1,sha,"00010","success")
        for sha in hashes[:2]: self.add_run(self.p1,1,sha,"00017","success")
        for sha in hashes[:2]: self.add_run(self.p1,1,sha,"00018","success")
        self.assertEqual([x["rule_id"] for x in get_rule_ranking(self.db,self.rules)], ["00010","00017","00018","00030"])

    def test_first_batch_uses_global_history(self):
        sha = "a" * 64
        self.add_batch(self.p1,1,[sha])
        self.add_run(self.p1,1,sha,"00018","success")
        self.add_batch(self.p2,1,["b" * 64])
        order = get_rule_order(self.db,self.rules,self.p2,1)
        self.assertEqual(order[0],"00018")

    def test_incomplete_batches_do_not_influence_ranking(self):
        sha = "c" * 64
        self.add_batch(self.p1,1,[sha],status="processing")
        self.add_run(self.p1,1,sha,"00030","success")
        self.assertFalse(any(x["tested"] for x in get_rule_ranking(self.db,self.rules)))


if __name__ == "__main__":
    unittest.main()
