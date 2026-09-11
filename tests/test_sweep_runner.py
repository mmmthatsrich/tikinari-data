"""The sweep runner: claim a cluster, record what was judged, close it — atomically.

The runner supplies primitives; the judgement is the model's. What it guarantees
is that a cluster's findings, its patches and its completion land together or not
at all. A session that dies mid-cluster must leave that cluster claimable again
with nothing half-written, which is what makes dying cost one cluster.

Every patch hangs off a finding. A field changed with no recorded reason is
exactly what the log exists to prevent, so the structure makes it impossible
rather than discouraged.
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from sweep_findings import FINDING_DDL, findings_for
from sweep_patch import PATCH_DDL
from sweep_queue import QUEUE_DDL, seed_clusters
from sweep_runner import claim, record


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
            headword TEXT, headword_search TEXT, headword_en TEXT,
            part_of_speech TEXT, part_of_speech_en TEXT, part_of_speech_mi TEXT,
            dialect TEXT, loan_marker TEXT, locator TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            gloss_en TEXT, gloss_mi TEXT, definition_raw TEXT, register TEXT,
            note TEXT, part_of_speech TEXT, part_of_speech_en TEXT);
        CREATE TABLE example (
            id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
            text_mi TEXT, text_en TEXT, citation TEXT, source_abbrev TEXT,
            sort_no INTEGER);
        CREATE TABLE form (
            id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT, form_type TEXT);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER, target_sense_id INTEGER,
            note TEXT);
        CREATE TABLE entry_domain (
            id INTEGER PRIMARY KEY, entry_id INTEGER, domain TEXT, domain_lang TEXT);
        CREATE TABLE ETY_cognateset (
            id INTEGER PRIMARY KEY, protoform TEXT, level TEXT, gloss TEXT);
        CREATE TABLE ETY_entry_link (
            id INTEGER PRIMARY KEY, cognateset_id INTEGER, entry_id INTEGER,
            sense_id INTEGER, source TEXT, match_method TEXT);
    """)
    for ddl in (PATCH_DDL, QUEUE_DDL, FINDING_DDL):
        con.executescript(ddl)
    con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword, "
                "headword_search) VALUES (1,'te_aka','79','aho','aho')")
    con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword, "
                "headword_search) VALUES (2,'williams','54','Aho','aho')")
    con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
                "VALUES (10,1,1,'weft, woof')")
    con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
                "VALUES (11,2,1,'A fishing-line.')")
    con.commit()
    seed_clusters(con)
    return con


def _payload(**kw):
    base = {
        "cluster_key": "aho",
        "findings": [{
            "kind": "field_placement",
            "subject": "te_aka:79#1",
            "summary": "gloss lacks the trailing stop every other source uses",
            "detail": "williams:54#1 ends 'A fishing-line.'",
            "severity": "low", "confidence": "certain", "action": "applied",
            "patches": [{
                "source_id": "te_aka", "source_entry_id": "79", "sense_number": 1,
                "target_table": "sense", "field": "gloss_en",
                "old_value": "weft, woof", "new_value": "weft, woof.",
                "reason": "consistency with the rest of the cluster",
            }],
        }],
    }
    base.update(kw)
    return base


class Claiming(unittest.TestCase):
    def test_a_claim_returns_the_rendered_batch(self):
        con = _db()
        key, batch, text = claim(con, "S1")
        self.assertEqual(key, "aho")
        self.assertEqual(batch["entry_count"], 2)
        self.assertIn("te_aka:79", text)
        self.assertIn("williams:54", text)

    def test_claiming_marks_the_cluster_in_progress(self):
        con = _db()
        claim(con, "S1")
        self.assertEqual(
            con.execute("SELECT status, claimed_by FROM sweep_cluster "
                        "WHERE cluster_key='aho'").fetchone()["status"],
            "in_progress")

    def test_an_empty_queue_claims_nothing(self):
        con = _db()
        claim(con, "S1")
        record(con, "S1", _payload())
        self.assertEqual(claim(con, "S1"), (None, None, None))


class Recording(unittest.TestCase):
    def test_findings_patches_and_completion_land_together(self):
        con = _db()
        claim(con, "S1")
        out = record(con, "S1", _payload())
        self.assertEqual(out["findings"], 1)
        self.assertEqual(out["patches"], 1)
        self.assertEqual(out["applied"], 1)
        row = con.execute("SELECT status, finding_count, patch_count, rubric_version "
                          "FROM sweep_cluster WHERE cluster_key='aho'").fetchone()
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["finding_count"], 1)
        self.assertEqual(row["patch_count"], 1)
        self.assertTrue(row["rubric_version"])

    def test_the_patch_actually_changed_the_data(self):
        con = _db()
        claim(con, "S1")
        record(con, "S1", _payload())
        self.assertEqual(
            con.execute("SELECT gloss_en FROM sense WHERE id=10").fetchone()[0],
            "weft, woof.")

    def test_a_patch_is_linked_to_the_finding_that_justified_it(self):
        con = _db()
        claim(con, "S1")
        record(con, "S1", _payload())
        fid = findings_for(con, cluster_key="aho")[0]["finding_id"]
        self.assertEqual(
            con.execute("SELECT finding_id FROM sweep_patch").fetchone()[0], fid)

    def test_a_clean_cluster_completes_with_no_findings(self):
        con = _db()
        claim(con, "S1")
        out = record(con, "S1", {"cluster_key": "aho", "findings": []})
        self.assertEqual(out["findings"], 0)
        self.assertEqual(
            con.execute("SELECT status FROM sweep_cluster WHERE cluster_key='aho'")
               .fetchone()[0], "done")

    def test_an_observation_only_finding_needs_no_patch(self):
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "homograph", "subject": "te_aka:79 vs williams:54",
            "summary": "different words sharing a search key",
            "action": "none"}])
        out = record(con, "S1", p)
        self.assertEqual((out["findings"], out["patches"]), (1, 0))


class Atomicity(unittest.TestCase):
    def _bad(self):
        p = _payload()
        p["findings"][0]["patches"][0]["field"] = "not_a_field"
        return p

    def test_a_bad_patch_aborts_the_whole_cluster(self):
        con = _db()
        claim(con, "S1")
        with self.assertRaises(ValueError):
            record(con, "S1", self._bad())
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sweep_finding")
                         .fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sweep_patch")
                         .fetchone()[0], 0)

    def test_a_rejected_payload_leaves_the_cluster_claimed_for_retry(self):
        # Validation runs before any write, so nothing happened and the cluster
        # is still this session's to try again. Releasing it here would let
        # another worker take a cluster someone is still working on.
        con = _db()
        claim(con, "S1")
        with self.assertRaises(ValueError):
            record(con, "S1", self._bad())
        self.assertEqual(
            con.execute("SELECT status, claimed_by FROM sweep_cluster "
                        "WHERE cluster_key='aho'").fetchone()["status"],
            "in_progress")

    def test_a_failure_part_way_through_writing_hands_the_cluster_back(self):
        # The payload validates but the write fails. Nothing may be left behind
        # and the cluster must return to the queue.
        con = _db()
        claim(con, "S1")
        con.execute("DROP TABLE sweep_patch")
        con.commit()
        with self.assertRaises(Exception):
            record(con, "S1", _payload())
        self.assertEqual(
            con.execute("SELECT status FROM sweep_cluster WHERE cluster_key='aho'")
               .fetchone()["status"], "pending")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sweep_finding")
                         .fetchone()[0], 0)

    def test_a_bad_finding_aborts_before_anything_is_written(self):
        con = _db()
        claim(con, "S1")
        with self.assertRaises(ValueError):
            record(con, "S1", _payload(findings=[{"kind": "nonsense",
                                                  "subject": "x", "summary": "y"}]))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sweep_finding")
                         .fetchone()[0], 0)

    def test_recording_a_cluster_nobody_claimed_is_refused(self):
        con = _db()
        with self.assertRaises(ValueError):
            record(con, "S1", _payload())

    def test_recording_someone_elses_claim_is_refused(self):
        con = _db()
        claim(con, "S1")
        with self.assertRaises(ValueError):
            record(con, "S2", _payload())


class PayloadValidation(unittest.TestCase):
    def test_a_payload_must_name_its_cluster(self):
        con = _db()
        claim(con, "S1")
        with self.assertRaises(ValueError):
            record(con, "S1", {"findings": []})

    def test_json_text_is_accepted_as_well_as_a_dict(self):
        con = _db()
        claim(con, "S1")
        out = record(con, "S1", json.dumps(_payload()))
        self.assertEqual(out["findings"], 1)


if __name__ == "__main__":
    unittest.main()
