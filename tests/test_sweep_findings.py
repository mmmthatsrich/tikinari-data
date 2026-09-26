"""The audit sweep's findings log — the record that gets reviewed.

You chose to review the LOG rather than gate a queue, so the log is the control
surface: it has to say what was judged, why, and what was done about it, for
findings that changed something and for findings that changed nothing.

Not every finding is a patch. 'This cognate set is spurious homophony' and
'these two entries are the same word' change no field on any row, and an
observation-only finding still has to be recorded or the log understates what
the sweep looked at.

Reverting a finding reverts the patches it produced, so the unit you undo is the
judgement rather than its consequences.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

from sweep_findings import (FINDING_DDL, record_finding, findings_for,
                            render_log, revert_finding, session_summary)
from sweep_patch import PATCH_DDL, apply_patches, record_patch


def _db() -> sqlite3.Connection:
    con = core_db()
    con.row_factory = sqlite3.Row
    con.executescript(PATCH_DDL)
    con.executescript(FINDING_DDL)
    con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword, "
                "  headword_sort, headword_search) VALUES (1, 'te_aka', '79', 'aho', '', '')")
    con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
                "VALUES (10, 1, 1, 'weft, woof')")
    con.commit()
    return con


def _finding(con, **kw):
    kw.setdefault("session_id", "S1")
    kw.setdefault("cluster_key", "aho")
    kw.setdefault("rubric_version", "v1")
    kw.setdefault("kind", "field_placement")
    kw.setdefault("subject", "te_aka:79#1")
    kw.setdefault("summary", "gloss carries a trailing stop")
    kw.setdefault("detail", "every other source omits it")
    return record_finding(con, **kw)


class Recording(unittest.TestCase):
    def test_a_finding_gets_a_readable_stable_id(self):
        con = _db()
        fid = _finding(con)
        self.assertEqual(fid, "S1:aho:1")

    def test_ids_increment_within_a_cluster(self):
        con = _db()
        self.assertEqual(_finding(con), "S1:aho:1")
        self.assertEqual(_finding(con), "S1:aho:2")

    def test_a_finding_that_changes_nothing_is_still_recorded(self):
        con = _db()
        fid = _finding(con, kind="spurious_etymology", action="none",
                       summary="PPN *aho 'daylight' is homophony here")
        row = findings_for(con, cluster_key="aho")[0]
        self.assertEqual(row["finding_id"], fid)
        self.assertEqual(row["action"], "none")

    def test_a_finding_must_say_what_and_why(self):
        con = _db()
        with self.assertRaises(ValueError):
            _finding(con, summary="")
        with self.assertRaises(ValueError):
            _finding(con, kind="")

    def test_an_unknown_kind_is_refused(self):
        con = _db()
        with self.assertRaises(ValueError):
            _finding(con, kind="vibes")


class LinkedPatches(unittest.TestCase):
    def _with_patch(self, con):
        fid = _finding(con, action="applied")
        record_patch(con, source_id="te_aka", source_entry_id="79", sense_number=1,
                     target_table="sense", field="gloss_en",
                     old_value="weft, woof", new_value="weft, woof.",
                     reason="consistency", finding_id=fid, session_id="S1",
                     cluster_key="aho")
        apply_patches(con)
        return fid

    def test_a_finding_reports_the_patches_it_produced(self):
        con = _db()
        fid = self._with_patch(con)
        self.assertEqual(findings_for(con, cluster_key="aho")[0]["patch_count"], 1)

    def test_reverting_a_finding_reverts_its_patches(self):
        con = _db()
        fid = self._with_patch(con)
        self.assertEqual(
            con.execute("SELECT gloss_en FROM sense WHERE id=10").fetchone()[0],
            "weft, woof.")
        revert_finding(con, fid)
        # the patch no longer replays; a rebuild reprojects the source value
        con.execute("UPDATE sense SET gloss_en='weft, woof' WHERE id=10")
        apply_patches(con)
        self.assertEqual(
            con.execute("SELECT gloss_en FROM sense WHERE id=10").fetchone()[0],
            "weft, woof")

    def test_a_reverted_finding_says_so(self):
        con = _db()
        fid = self._with_patch(con)
        revert_finding(con, fid)
        self.assertIsNotNone(findings_for(con, cluster_key="aho")[0]["reverted_at"])

    def test_reverting_an_observation_only_finding_is_fine(self):
        con = _db()
        fid = _finding(con, action="none")
        self.assertEqual(revert_finding(con, fid), 0)   # no patches to undo


class Reporting(unittest.TestCase):
    def test_the_session_summary_counts_by_kind(self):
        con = _db()
        _finding(con, kind="field_placement")
        _finding(con, kind="field_placement")
        _finding(con, kind="spurious_etymology", action="none")
        s = session_summary(con, "S1")
        self.assertEqual(s["by_kind"]["field_placement"], 2)
        self.assertEqual(s["by_kind"]["spurious_etymology"], 1)
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["clusters"], 1)

    def test_findings_can_be_read_per_session(self):
        con = _db()
        _finding(con, session_id="S1")
        _finding(con, session_id="S2", cluster_key="kai")
        self.assertEqual(len(findings_for(con, session_id="S2")), 1)

    def test_the_log_renders_what_was_judged_and_why(self):
        con = _db()
        _finding(con, summary="gloss carries a trailing stop",
                 detail="every other source omits it")
        text = render_log(con, session_id="S1")
        self.assertIn("aho", text)
        self.assertIn("trailing stop", text)
        self.assertIn("every other source omits it", text)
        self.assertIn("te_aka:79#1", text)

    def test_an_empty_log_renders(self):
        self.assertIsInstance(render_log(_db(), session_id="nope"), str)


if __name__ == "__main__":
    unittest.main()
