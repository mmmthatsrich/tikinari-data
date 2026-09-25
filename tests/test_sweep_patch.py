"""The audit sweep's patch layer.

50_build_unified.py is a pure projection: it deletes a source's slice and
rebuilds it from the landing tables. Anything the sweep writes into the unified
core is therefore destroyed by the next rebuild of that source. Patches are
recorded instead and REPLAYED after each build.

Patches are keyed on (source_id, source_entry_id, sense_number) because
`entry.id` is documented as volatile across rebuilds — a patch keyed on it would
silently reattach to a different word.

Staleness is checked per FIELD, not per entry: a patch applies only while the
field still holds the value it was judged against, so a source that corrects
something itself is never overwritten by an older judgement, while an unrelated
edit elsewhere in the entry does not discard a good correction.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

from sweep_patch import PATCH_DDL, apply_patches, record_patch, revert


def _db() -> sqlite3.Connection:
    con = core_db()
    con.executescript(PATCH_DDL)
    con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword, "
                "  headword_sort, headword_search) VALUES (1, 'te_aka', '31760', 'pepa', '', '')")
    con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
                "VALUES (10, 1, 1, 'newspaper.')")
    con.commit()
    return con


def _gloss(con):
    return con.execute("SELECT gloss_en FROM sense WHERE id=10").fetchone()[0]


class ApplyPatches(unittest.TestCase):
    def _patch(self, con, old="newspaper.", new="newspaper"):
        record_patch(con, source_id="te_aka", source_entry_id="31760",
                     sense_number=1, target_table="sense", field="gloss_en",
                     old_value=old, new_value=new, reason="trailing stop",
                     finding_id="F1", session_id="S1", cluster_key="pepa")

    def test_a_patch_applies_when_the_field_is_untouched(self):
        con = _db()
        self._patch(con)
        self.assertEqual(apply_patches(con)["applied"], 1)
        self.assertEqual(_gloss(con), "newspaper")

    def test_replaying_after_a_rebuild_reapplies_the_patch(self):
        con = _db()
        self._patch(con)
        apply_patches(con)
        # a rebuild throws the slice away and reprojects it from source
        con.execute("UPDATE sense SET gloss_en='newspaper.' WHERE id=10")
        self.assertEqual(apply_patches(con)["applied"], 1)
        self.assertEqual(_gloss(con), "newspaper")

    def test_replaying_without_a_rebuild_is_idempotent(self):
        # The field already holds new_value; that is applied, not stale.
        con = _db()
        self._patch(con)
        apply_patches(con)
        out = apply_patches(con)
        self.assertEqual(out["applied"], 0)
        self.assertEqual(out["stale"], 0)
        self.assertEqual(_gloss(con), "newspaper")

    def test_a_source_change_to_that_field_makes_the_patch_stale(self):
        con = _db()
        self._patch(con)
        con.execute("UPDATE sense SET gloss_en='newspaper, periodical.' WHERE id=10")
        out = apply_patches(con)
        self.assertEqual(out["stale"], 1)
        self.assertEqual(out["applied"], 0)
        # upstream wins — the sweep's older judgement does not overwrite it
        self.assertEqual(_gloss(con), "newspaper, periodical.")

    def test_a_change_to_a_different_field_does_not_block_the_patch(self):
        con = _db()
        self._patch(con)
        con.execute("UPDATE sense SET definition_raw='something new' WHERE id=10")
        self.assertEqual(apply_patches(con)["applied"], 1)
        self.assertEqual(_gloss(con), "newspaper")

    def test_a_reverted_patch_is_never_applied(self):
        con = _db()
        self._patch(con)
        revert(con, finding_id="F1")
        self.assertEqual(apply_patches(con)["applied"], 0)
        self.assertEqual(_gloss(con), "newspaper.")

    def test_reverting_a_whole_session(self):
        con = _db()
        self._patch(con)
        revert(con, session_id="S1")
        self.assertEqual(apply_patches(con)["applied"], 0)

    def test_a_patch_whose_row_is_gone_is_reported_missing(self):
        con = _db()
        self._patch(con)
        con.execute("DELETE FROM sense WHERE id=10")
        out = apply_patches(con)
        self.assertEqual(out["missing"], 1)

    def test_an_entry_level_field_needs_no_sense_number(self):
        con = _db()
        record_patch(con, source_id="te_aka", source_entry_id="31760",
                     sense_number=None, target_table="entry", field="headword_en",
                     old_value=None, new_value="newspaper", reason="absent",
                     finding_id="F2", session_id="S1", cluster_key="pepa")
        self.assertEqual(apply_patches(con)["applied"], 1)
        self.assertEqual(
            con.execute("SELECT headword_en FROM entry WHERE id=1").fetchone()[0],
            "newspaper")

    def test_an_unknown_field_is_refused(self):
        con = _db()
        with self.assertRaises(ValueError):
            record_patch(con, source_id="te_aka", source_entry_id="31760",
                         sense_number=1, target_table="sense",
                         field="gloss_en; DROP TABLE sense--",
                         old_value="x", new_value="y", reason="r",
                         finding_id="F3", session_id="S1", cluster_key="pepa")

    def test_an_unknown_table_is_refused(self):
        con = _db()
        with self.assertRaises(ValueError):
            record_patch(con, source_id="te_aka", source_entry_id="31760",
                         sense_number=1, target_table="sqlite_master",
                         field="name", old_value="x", new_value="y", reason="r",
                         finding_id="F4", session_id="S1", cluster_key="pepa")

    def test_the_status_of_each_patch_is_recorded(self):
        con = _db()
        self._patch(con)
        apply_patches(con)
        self.assertEqual(
            con.execute("SELECT last_status FROM sweep_patch").fetchone()[0],
            "applied")


if __name__ == "__main__":
    unittest.main()
