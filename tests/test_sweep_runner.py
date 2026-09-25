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
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

import sweep_runner
from sweep_findings import FINDING_DDL, findings_for
from sweep_patch import PATCH_DDL
from sweep_queue import QUEUE_DDL, seed_clusters
from sweep_runner import claim, record


def _db() -> sqlite3.Connection:
    con = core_db()
    con.row_factory = sqlite3.Row
    for ddl in (PATCH_DDL, QUEUE_DDL, FINDING_DDL):
        con.executescript(ddl)
    con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword, "
                "headword_search, headword_sort, headword_search)VALUES (1,'te_aka','79','aho','aho', '', '')")
    con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword, "
                "headword_search, headword_sort, headword_search)VALUES (2,'williams','54','Aho','aho', '', '')")
    con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
                "VALUES (10,1,1,'weft, woof')")
    con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
                "VALUES (11,2,1,'A fishing-line.')")
    con.execute("INSERT INTO concept (id, status, confidence, headword, gloss_en) "
                "VALUES (1,'proposed','medium','aho','cord, string')")
    con.execute("INSERT INTO concept_member (id, concept_id, source_id, "
                "source_entry_id, sense_number, status, confidence) "
                "VALUES (1,1,'te_aka','79',1,'proposed','medium')")
    con.execute("INSERT INTO concept_member_evidence (member_id, kind, detail, weight) "
                "VALUES (1,'shared_gloss','matches williams:54 gloss \"weft, woof\"',1.0)")
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


class ConceptActions(unittest.TestCase):
    """Concept decisions nest inside findings, exactly as patches do: a
    membership cannot change without a recorded reason."""

    def test_a_confirm_marks_the_membership(self):
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "te_aka:79#1",
            "summary": "same word as williams:54",
            "action": "applied",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "te_aka:79#1"}]}])
        record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=1").fetchone()[0],
            "confirmed")

    def test_a_confirm_confirms_the_concept_too(self):
        # Without this the sweep cannot change what ships: nothing else sets
        # concept.status, so a confirmed membership of an uncertain concept
        # stayed uncertain, the export dropped it, and the judgement never
        # reached users. A concept may be confirmed while another member is
        # still proposed — that is the common case.
        con = _db()
        con.execute("UPDATE concept SET confidence='uncertain' WHERE id=1")
        con.commit()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "te_aka:79#1",
            "summary": "same word as williams:54",
            "action": "applied",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "te_aka:79#1"}]}])
        record(con, "S1", p)
        row = con.execute("SELECT status, confidence, last_updated "
                          "FROM concept WHERE id=1").fetchone()
        self.assertEqual(row["status"], "confirmed")
        # The confidence is what the evidence earned; the status is the
        # judgement. The export threshold reads either, so status alone is
        # enough to carry a confirmed grouping through.
        self.assertEqual(row["confidence"], "uncertain")
        self.assertIsNotNone(row["last_updated"])

    def test_a_reject_leaves_the_concept_alone(self):
        # Rejecting one member says nothing about the rest of the grouping.
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "homograph", "subject": "te_aka:79#1",
            "summary": "not actually the same word",
            "action": "applied",
            "concept_actions": [{"action": "reject_member",
                                 "member": "te_aka:79#1"}]}])
        record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept WHERE id=1").fetchone()[0], "proposed")

    def test_a_reject_marks_the_membership(self):
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "homograph", "subject": "te_aka:79#1",
            "summary": "not actually the same word",
            "action": "applied",
            "concept_actions": [{"action": "reject_member",
                                 "member": "te_aka:79#1"}]}])
        record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=1").fetchone()[0],
            "rejected")

    def test_a_member_with_no_sense_number_matches_null(self):
        con = _db()
        con.execute("INSERT INTO concept_member (id, concept_id, source_id, "
                    " source_entry_id, sense_number, status, confidence) "
                    " VALUES (2,1,'paekupu','himoemoe',NULL,'proposed','probable')")
        con.commit()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "paekupu:himoemoe",
            "summary": "matches this cluster",
            "action": "applied",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "paekupu:himoemoe"}]}])
        record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=2").fetchone()[0],
            "confirmed")

    def test_an_unknown_action_is_refused(self):
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "te_aka:79#1", "summary": "y",
            "concept_actions": [{"action": "explode",
                                 "member": "te_aka:79#1"}]}])
        with self.assertRaises(ValueError):
            record(con, "S1", p)

    def test_an_unknown_member_is_refused(self):
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "te_aka:79#1", "summary": "y",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "nosuch:9#9"}]}])
        with self.assertRaises(ValueError):
            record(con, "S1", p)

    def test_a_bad_concept_action_leaves_the_membership_untouched(self):
        # All-or-nothing: the payload's earlier patch must not survive a
        # later concept_action that fails validation or application.
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "te_aka:79#1", "summary": "y",
            "action": "applied",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "nosuch:9#9"}]}])
        with self.assertRaises(ValueError):
            record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=1").fetchone()[0],
            "proposed")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sweep_finding")
                         .fetchone()[0], 0)
        self.assertEqual(
            con.execute("SELECT gloss_en FROM sense WHERE id=10").fetchone()[0],
            "weft, woof")

    def test_a_later_findings_bad_member_undoes_an_earlier_ones_confirm(self):
        # Two findings: the first confirms a real membership, the second
        # names one that does not exist. Nothing in the payload may survive:
        # not the first membership change, not either finding. This is the
        # scenario that only proved itself by hand in round 1 — the earlier
        # single-finding version of this test passed even with no rollback
        # at all, because the bad member never touched a row to begin with.
        con = _db()
        claim(con, "S1")
        p = _payload(findings=[
            {"kind": "duplicate", "subject": "te_aka:79#1", "summary": "a",
             "concept_actions": [{"action": "confirm_member",
                                  "member": "te_aka:79#1"}]},
            {"kind": "duplicate", "subject": "x", "summary": "b",
             "concept_actions": [{"action": "confirm_member",
                                  "member": "nosuch:9#9"}]},
        ])
        with self.assertRaises(ValueError):
            record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=1").fetchone()[0],
            "proposed")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sweep_finding")
                         .fetchone()[0], 0)

    def test_a_member_with_the_wrong_sense_number_is_refused(self):
        # williams:1251#9 is well-formed and williams:1251 exists, but only
        # at sense #1 -- the address must be rejected outright at
        # validation, not treated as a no-op that quietly does nothing.
        con = _db()
        con.execute("INSERT INTO concept_member (id, concept_id, source_id, "
                    " source_entry_id, sense_number, status, confidence) "
                    " VALUES (2,1,'williams','1251',1,'proposed','probable')")
        con.commit()
        claim(con, "S1")
        p = _payload(findings=[{
            "kind": "duplicate", "subject": "williams:1251#9", "summary": "y",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "williams:1251#9"}]}])
        with self.assertRaises(ValueError):
            record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=2").fetchone()[0],
            "proposed")

    def test_the_rollback_undoes_a_membership_the_row_race_would_otherwise_commit(self):
        # Defense in depth: _validate resolves every member up front, so in
        # ordinary use _apply_concept_actions cannot fail. But it is not the
        # only thing that could fail after a membership is already applied
        # and before the payload finishes, so record()'s rollback has to
        # still work for that case. This simulates it: the first finding's
        # confirm succeeds and is (deliberately) left uncommitted, then the
        # second finding's apply is made to raise -- standing in for
        # anything going wrong after a successful membership change and
        # before record()'s own final commit.
        con = _db()
        con.execute("INSERT INTO concept_member (id, concept_id, source_id, "
                    " source_entry_id, sense_number, status, confidence) "
                    " VALUES (2,1,'williams','54',1,'proposed','probable')")
        con.commit()
        claim(con, "S1")
        p = _payload(findings=[
            {"kind": "duplicate", "subject": "te_aka:79#1", "summary": "a",
             "concept_actions": [{"action": "confirm_member",
                                  "member": "te_aka:79#1"}]},
            {"kind": "duplicate", "subject": "williams:54#1", "summary": "b",
             "concept_actions": [{"action": "confirm_member",
                                  "member": "williams:54#1"}]},
        ])
        real_apply = sweep_runner._apply_concept_actions
        calls = []

        def flaky_apply(con, finding):
            calls.append(finding)
            if len(calls) == 2:
                raise RuntimeError("something else went wrong right here")
            real_apply(con, finding)

        with mock.patch.object(sweep_runner, "_apply_concept_actions",
                               side_effect=flaky_apply):
            with self.assertRaises(RuntimeError):
                record(con, "S1", p)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=1").fetchone()[0],
            "proposed")


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


class CliPrintsMaori(unittest.TestCase):
    """The CLI must survive a console that is not UTF-8.

    Found on the first real `next` of the calibration sweep: the claim
    committed, then `print(text)` died with UnicodeEncodeError and left the
    cluster stranded `in_progress`. Windows consoles default to cp1252 and
    Māori headwords carry macrons, so this was not an edge case — it was
    most clusters. A dozen sibling scripts already call
    `sys.stdout.reconfigure(encoding='utf-8')`; this module did not.

    Forcing PYTHONIOENCODING makes the reproduction independent of whatever
    locale the machine running the tests happens to have.
    """

    def test_importing_the_runner_makes_stdout_utf8(self):
        import os
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        script = ("import sys; sys.path.insert(0, %r); import sweep_runner; "
                  "print('m\u0101ori')"
                  % str(Path(__file__).parent.parent / "scripts"))
        # Decode as UTF-8 explicitly: PYTHONIOENCODING forces the CHILD's
        # console to cp1252, which is the condition under test, but the child
        # now writes UTF-8 and this side must read it as such.
        run = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, encoding="utf-8",
                             errors="replace", env=env)
        self.assertEqual(
            0, run.returncode,
            "the runner cannot print a macron on a cp1252 console:\n"
            + run.stderr)


class MemberAddressesWithHashInTheEntryId(unittest.TestCase):
    """Four sources put '#' inside source_entry_id. The sense separator is
    also '#', so the address is ambiguous and 42,062 of 175,101 memberships
    — ngata 33,775, te_matatiki 5,097, kimikupu_hou 2,839,
    tregear_exceptions 351 — could not be confirmed or rejected at all.

    ngata ids ('WR-HMN.11059#41666~1') failed to parse outright; te_matatiki
    ids ('WR-TM.666#48292') parsed into an entry and sense that do not exist,
    so the judgement was refused as a missing membership. Found on the fifth
    cluster of the concept calibration round, trying to confirm te_matatiki.

    The database is what disambiguates: try the whole string as the entry id
    first, and only split on a trailing '#N' if that finds nothing.
    """

    def setUp(self):
        self.con = _db()
        self.con.executemany(
            "INSERT INTO concept_member (concept_id, source_id, "
            " source_entry_id, sense_number, status, confidence) "
            " VALUES (1,?,?,?,'proposed','probable')",
            [("te_matatiki", "WR-TM.666#48292", None),
             ("ngata", "WR-HMN.11059#41666~1", None)])
        self.con.commit()

    def test_a_te_matatiki_address_resolves_to_its_own_row(self):
        self.assertEqual(
            ("te_matatiki", "WR-TM.666#48292", None),
            sweep_runner.resolve_member(self.con, "te_matatiki:WR-TM.666#48292"))

    def test_an_ngata_address_resolves_to_its_own_row(self):
        self.assertEqual(
            ("ngata", "WR-HMN.11059#41666~1", None),
            sweep_runner.resolve_member(self.con, "ngata:WR-HMN.11059#41666~1"))

    def test_a_plain_sense_suffix_still_means_a_sense(self):
        self.assertEqual(
            ("te_aka", "79", 1),
            sweep_runner.resolve_member(self.con, "te_aka:79#1"))

    def test_an_address_matching_nothing_is_refused(self):
        with self.assertRaises(ValueError):
            sweep_runner.resolve_member(self.con, "te_aka:99999#1")

    def test_confirming_a_hash_id_member_actually_marks_THAT_row(self):
        """Validation and apply must resolve the address the same way.

        _validate resolving correctly is not enough: if the apply pass parses
        the address differently it writes to a different row, or to none, and
        the judgement is silently lost after passing every check.
        """
        payload = {
            "cluster_key": "aho",
            "findings": [{
                "kind": "observation",
                "subject": "te_matatiki:WR-TM.666#48292",
                "summary": "confirmed while judging the calibration round",
                "concept_actions": [
                    {"action": "confirm_member",
                     "member": "te_matatiki:WR-TM.666#48292"}],
            }],
        }
        claim(self.con, "S1")
        record(self.con, "S1", json.dumps(payload))
        self.assertEqual(
            "confirmed",
            self.con.execute(
                "SELECT status FROM concept_member WHERE source_id = ? "
                "  AND source_entry_id = ?",
                ("te_matatiki", "WR-TM.666#48292")).fetchone()[0])
