"""The audit sweep's durable cluster queue.

55,827 clusters, judged over many sessions. A session will die — tokens, a
crash, a closed laptop — so the queue is built so that dying costs at most one
cluster: a cluster is claimed, worked, and completed in one transaction, and the
cursor advances only on commit.

Ordering is priority, then tier: the calibration slice runs first, then the
hardest clusters (5+ sources, 7% of the corpus but 46% of its text), then down.

Every completed cluster records the rubric version that judged it, because a
finding class discovered at cluster 40,000 invalidates the 39,999 before it and
a targeted re-sweep needs to know which those are.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from sweep_queue import (QUEUE_DDL, claim_next, complete, mark_calibration,
                         progress, release_stale, requeue_before_rubric,
                         seed_clusters)


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, headword_search TEXT);
        CREATE TABLE sense (id INTEGER PRIMARY KEY, entry_id INTEGER);
    """)
    con.executescript(QUEUE_DDL)
    rows = [
        # 'aho' — 5 sources -> tier 1
        *[(None, s, "aho") for s in
          ("te_aka", "williams", "ngata", "paekupu", "hepatakakupu")],
        # 'kai' — 3 sources -> tier 2
        *[(None, s, "kai") for s in ("te_aka", "williams", "ngata")],
        # 'rua' — 2 sources -> tier 3
        *[(None, s, "rua") for s in ("te_aka", "williams")],
        # 'zzz' — 1 source -> tier 4
        (None, "te_aka", "zzz"),
    ]
    con.executemany(
        "INSERT INTO entry (id, source_id, headword_search) VALUES (?,?,?)", rows)
    for eid, in con.execute("SELECT id FROM entry"):
        con.execute("INSERT INTO sense (entry_id) VALUES (?)", (eid,))
    con.commit()
    return con


class Seeding(unittest.TestCase):
    def test_one_row_per_cluster_with_its_tier(self):
        con = _db()
        seed_clusters(con)
        got = dict(con.execute("SELECT cluster_key, tier FROM sweep_cluster"))
        self.assertEqual(got, {"aho": 1, "kai": 2, "rua": 3, "zzz": 4})

    def test_counts_are_recorded(self):
        con = _db()
        seed_clusters(con)
        row = con.execute("SELECT entry_count, source_count, sense_count "
                          "FROM sweep_cluster WHERE cluster_key='aho'").fetchone()
        self.assertEqual(row, (5, 5, 5))

    def test_seeding_twice_does_not_duplicate(self):
        con = _db()
        seed_clusters(con)
        seed_clusters(con)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM sweep_cluster").fetchone()[0], 4)

    def test_reseeding_does_not_reopen_completed_work(self):
        con = _db()
        seed_clusters(con)
        key = claim_next(con, "S1")
        complete(con, key, rubric_version="v1")
        seed_clusters(con)
        self.assertEqual(
            con.execute("SELECT status FROM sweep_cluster WHERE cluster_key=?",
                        (key,)).fetchone()[0], "done")


class Claiming(unittest.TestCase):
    def test_the_hardest_cluster_comes_first(self):
        con = _db()
        seed_clusters(con)
        self.assertEqual(claim_next(con, "S1"), "aho")

    def test_a_claimed_cluster_is_not_handed_out_again(self):
        con = _db()
        seed_clusters(con)
        self.assertEqual(claim_next(con, "S1"), "aho")
        self.assertEqual(claim_next(con, "S2"), "kai")

    def test_claiming_records_who_holds_it(self):
        con = _db()
        seed_clusters(con)
        claim_next(con, "S1")
        self.assertEqual(
            con.execute("SELECT claimed_by, status FROM sweep_cluster "
                        "WHERE cluster_key='aho'").fetchone(), ("S1", "in_progress"))

    def test_an_empty_queue_returns_none(self):
        con = _db()
        seed_clusters(con)
        for _ in range(4):
            complete(con, claim_next(con, "S1"), rubric_version="v1")
        self.assertIsNone(claim_next(con, "S1"))

    def test_a_tier_can_be_requested(self):
        con = _db()
        seed_clusters(con)
        self.assertEqual(claim_next(con, "S1", tier=4), "zzz")


class Calibration(unittest.TestCase):
    def test_the_calibration_slice_is_served_before_everything(self):
        con = _db()
        seed_clusters(con)
        mark_calibration(con, per_tier=1, seed=7)
        # every tier contributes one, and they all precede ordinary work
        first4 = [claim_next(con, "S1") for _ in range(4)]
        self.assertEqual(sorted(first4), ["aho", "kai", "rua", "zzz"])
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM sweep_cluster WHERE priority=0")
               .fetchone()[0], 4)

    def test_calibration_selection_is_deterministic(self):
        a, b = _db(), _db()
        for con in (a, b):
            seed_clusters(con)
            mark_calibration(con, per_tier=1, seed=7)
        pick = lambda c: sorted(
            r[0] for r in c.execute("SELECT cluster_key FROM sweep_cluster "
                                    "WHERE priority=0"))
        self.assertEqual(pick(a), pick(b))


class Recovery(unittest.TestCase):
    def test_an_abandoned_claim_returns_to_the_queue(self):
        con = _db()
        seed_clusters(con)
        claim_next(con, "S1")
        con.execute("UPDATE sweep_cluster SET claimed_at='2000-01-01T00:00:00+00:00' "
                    "WHERE cluster_key='aho'")
        self.assertEqual(release_stale(con, older_than_minutes=60), 1)
        self.assertEqual(claim_next(con, "S2"), "aho")

    def test_a_fresh_claim_is_not_released(self):
        con = _db()
        seed_clusters(con)
        claim_next(con, "S1")
        self.assertEqual(release_stale(con, older_than_minutes=60), 0)

    def test_completed_work_is_never_released(self):
        con = _db()
        seed_clusters(con)
        complete(con, claim_next(con, "S1"), rubric_version="v1")
        con.execute("UPDATE sweep_cluster SET claimed_at='2000-01-01T00:00:00+00:00'")
        self.assertEqual(release_stale(con, older_than_minutes=60), 0)


class RubricVersioning(unittest.TestCase):
    def test_completion_records_the_rubric_and_its_tallies(self):
        con = _db()
        seed_clusters(con)
        complete(con, claim_next(con, "S1"), rubric_version="v1",
                 finding_count=3, patch_count=2)
        row = con.execute("SELECT rubric_version, finding_count, patch_count, status "
                          "FROM sweep_cluster WHERE cluster_key='aho'").fetchone()
        self.assertEqual(row, ("v1", 3, 2, "done"))

    def test_clusters_judged_under_an_older_rubric_can_be_requeued(self):
        con = _db()
        seed_clusters(con)
        complete(con, claim_next(con, "S1"), rubric_version="v1")
        complete(con, claim_next(con, "S1"), rubric_version="v2")
        self.assertEqual(requeue_before_rubric(con, ["v2"]), 1)
        self.assertEqual(claim_next(con, "S2"), "aho")


class Progress(unittest.TestCase):
    def test_progress_reports_by_status(self):
        con = _db()
        seed_clusters(con)
        complete(con, claim_next(con, "S1"), rubric_version="v1")
        claim_next(con, "S1")
        p = progress(con)
        self.assertEqual(p["done"], 1)
        self.assertEqual(p["in_progress"], 1)
        self.assertEqual(p["pending"], 2)


if __name__ == "__main__":
    unittest.main()
