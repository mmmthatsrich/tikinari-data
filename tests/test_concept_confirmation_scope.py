"""A confirmation covers the grouping it was granted to, not every later one (D47).

A member-level confirm sets a concept-level status, which is right — nothing
else sets `concept.status`, and without it the sweep could not change what
ships. But the rebuild re-derived that status from scratch against whatever
membership now existed:

    status = "confirmed" if any(judged[...] == "confirmed" for m in members)

`any()`. One confirmed member made the whole rebuilt concept confirmed, however
many new and unjudged members had joined since. The confirmation is sticky to
the MEMBER, its effect lands on the CONCEPT, and the concept is rebuilt from
nothing every run.

It happened. A sweep session confirmed `te_aka:516#1` and `#2` in a concept
holding only te_aka; the D44 fix merged `hepatakakupu:4287#1` into it; and the
rebuilt concept was confirmed, with hepatakakupu's membership — which no judge
had seen — inside it. That outcome was right, because hepatakakupu:4287 *is*
the same word, but it was right by luck rather than by check.

It matters beyond bookkeeping: `filter_concepts` ships a concept when
`status = 'confirmed' OR confidence IN (certain, probable)`, so a confirmed
concept bypasses the confidence filter entirely and an unjudged member rides
someone else's confirmation out to users.

**The rule.** A confirm records the grouping it saw. The rebuild confirms the
concept only when the current grouping adds nothing to that. Losing a member
is fine — the judge saw more than is there now, and nothing unexamined has
appeared. Gaining one is not.

**Nothing is destroyed.** The member keeps its own `confirmed` status either
way; only the concept-level claim waits to be re-earned. A lost judgement is
unrecoverable and this is not.
"""
import importlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

build = importlib.import_module("54_build_concepts")
runner = importlib.import_module("sweep_runner")
init_db = importlib.import_module("00_init_db")

A = ("te_aka", "516", 1)
B = ("te_aka", "516", 2)
C = ("hepatakakupu", "4287", 1)


def _judged(status="confirmed", grouping=None):
    """The {member_key: (concept_id, status, confidence, grouping)} shape."""
    return (1, status, "probable",
            None if grouping is None else [list(k) for k in grouping])


class TheStatusRule(unittest.TestCase):
    def test_an_unchanged_grouping_stays_confirmed(self):
        judged = {A: _judged(grouping=[A, B])}
        self.assertEqual(build._concept_status([A, B], judged), "confirmed")

    def test_a_grouping_that_gained_a_member_reverts_to_proposed(self):
        # The te_aka:516 + hepatakakupu:4287 case, exactly.
        judged = {A: _judged(grouping=[A, B])}
        self.assertEqual(build._concept_status([A, B, C], judged), "proposed")

    def test_a_grouping_that_only_lost_a_member_stays_confirmed(self):
        # The judge saw more than is here now. Nothing unexamined appeared,
        # so the confirmation still covers what remains.
        judged = {A: _judged(grouping=[A, B, C])}
        self.assertEqual(build._concept_status([A, B], judged), "confirmed")

    def test_a_confirmation_with_no_recorded_grouping_cannot_confirm(self):
        # Rows judged before this existed. Their grouping is unknown, so it
        # cannot be checked, and an unverifiable claim is not a confirmation.
        # The member keeps its own status; the concept waits to be re-judged.
        judged = {A: _judged(grouping=None)}
        self.assertEqual(build._concept_status([A, B], judged), "proposed")

    def test_no_confirmed_member_is_proposed(self):
        judged = {A: _judged(status="rejected", grouping=[A])}
        self.assertEqual(build._concept_status([A, B], judged), "proposed")

    def test_any_one_verified_confirmation_is_enough(self):
        # A concept can be confirmed while another member is still proposed:
        # five witnesses obviously the same word, a sixth uncertain.
        judged = {A: _judged(grouping=None),
                  B: _judged(grouping=[A, B])}
        self.assertEqual(build._concept_status([A, B], judged), "confirmed")

    def test_a_rejected_member_is_not_part_of_the_grouping(self):
        # A rejection records that the sense does NOT belong, so its presence
        # is not a new witness the judge failed to see.
        judged = {A: _judged(grouping=[A, B]),
                  C: _judged(status="rejected", grouping=None)}
        self.assertEqual(build._concept_status([A, B, C], judged), "confirmed")


def _db():
    con = sqlite3.connect(":memory:")
    init_db.initialise(con)
    con.execute("INSERT INTO concept (id, status, confidence) "
                " VALUES (1, 'proposed', 'probable')")
    for src, seid, sn in (A, B, C):
        con.execute(
            "INSERT INTO concept_member (concept_id, source_id, "
            " source_entry_id, sense_number, status, confidence) "
            " VALUES (1,?,?,?,'proposed','probable')", (src, seid, sn))
    con.commit()
    return con


def _grouping(con, key):
    raw = con.execute(
        "SELECT confirmed_grouping FROM concept_member WHERE source_id=? "
        "  AND source_entry_id=? AND sense_number IS ?", key).fetchone()[0]
    return None if raw is None else [tuple(x) for x in json.loads(raw)]


class ConfirmingRecordsWhatTheJudgeSaw(unittest.TestCase):
    def test_a_confirm_snapshots_the_concept_s_members(self):
        con = _db()
        runner._apply_concept_actions(con, {"concept_actions": [
            {"action": "confirm_member", "member": "te_aka:516#1"}]})
        got = _grouping(con, A)
        self.assertEqual(sorted(got), sorted([A, B, C]))

    def test_the_snapshot_excludes_a_rejected_member(self):
        con = _db()
        con.execute("UPDATE concept_member SET status='rejected' "
                    " WHERE source_id='hepatakakupu'")
        runner._apply_concept_actions(con, {"concept_actions": [
            {"action": "confirm_member", "member": "te_aka:516#1"}]})
        self.assertEqual(sorted(_grouping(con, A)), sorted([A, B]))

    def test_a_reject_records_no_grouping(self):
        con = _db()
        runner._apply_concept_actions(con, {"concept_actions": [
            {"action": "reject_member", "member": "hepatakakupu:4287#1"}]})
        self.assertIsNone(_grouping(con, C))

    def test_a_confirm_still_confirms_the_concept(self):
        con = _db()
        runner._apply_concept_actions(con, {"concept_actions": [
            {"action": "confirm_member", "member": "te_aka:516#1"}]})
        self.assertEqual(
            con.execute("SELECT status FROM concept WHERE id=1").fetchone()[0],
            "confirmed")


if __name__ == "__main__":
    unittest.main()
