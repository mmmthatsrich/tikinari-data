"""Fields a parser emits must reach the database (D35, D36, D37).

Three consecutive findings were the same defect: the source published a fact,
the parser read it, and it died one step later because nothing downstream had
a place to put it.

  D35  He Pātaka Kupu publishes a master_definition link on 14,379 senses.
       The parser never looked for it.
  D36  The Williams parser recorded `parent_headword` on 3,032 sub-entries
       and williams_entries had no such column.
  D37  Papakupu numbers its senses on 4,003 records and papakupu_entries had
       no such column, so every papakupu sense reached the corpus unnumbered.

These assertions are deliberately about the DATABASE rather than the parsers:
a parser can keep emitting a field correctly while the column that receives it
is dropped in a schema edit, which is exactly how D36 and D37 happened. Each
count is a floor well below the current value, so ordinary drift is quiet and
a field disappearing is loud.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


class ParsedFieldsReachTheDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_hepatakakupu_keeps_its_master_definition_links(self):
        # 14,379 in the raw pages; 14,370 survive to relations.
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM relation WHERE rel_type = 'master_definition'"),
            14000)

    def test_a_master_definition_names_the_sense_it_means(self):
        # The trailing '(N)' is the whole point: without it the link narrows a
        # lemma instead of naming a sense.
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM relation WHERE rel_type = 'master_definition' "
            "  AND target_sense_id IS NOT NULL"), 14000)

    def test_williams_keeps_the_base_a_sub_entry_was_printed_under(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM williams_entries "
            "WHERE parent_headword IS NOT NULL"), 3000)

    def test_williams_records_the_derivations_it_can_support(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM relation WHERE rel_type = 'derived_from'"), 1400)

    def test_papakupu_keeps_its_sense_numbers(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM papakupu_entries WHERE sense_number IS NOT NULL"),
            3900)

    def test_papakupu_sense_numbers_reach_the_unified_core(self):
        # The landing column is only half the journey; D37 was invisible in the
        # unified tables the sweep actually reads.
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id = s.entry_id "
            " WHERE e.source_id = 'papakupu' AND s.sense_number IS NOT NULL"),
            3900)


class AppDbIsNotStale(unittest.TestCase):
    """The derived chain has been got wrong by hand. Assert one slice of it.

    The chain is 52 -> 08b -> 53 -> 54 -> 60. Only 60_export_app_db writes
    entry/sense/relation into the app DB — it copies them straight out of
    staging at export time. So this test catches exactly one failure mode:
    staging moved on (a source was rebuilt by 50_build_unified) and 60 was
    never rerun, leaving the app DB's snapshot behind.

    It does NOT catch a skipped 52, 08b, 53 or 54. Those steps corrupt or
    empty *staging*'s own derived tables (ETY_*, pollex_entry_links,
    derivation, loan_origin, concept, concept_member) without touching
    entry/sense/relation — 60 then faithfully copies the same (broken)
    numbers into the app DB and this comparison finds the two sides in
    perfect agreement. See DerivedTablesArePopulated below for that case.
    """

    APP = Path(__file__).parent.parent / "data" / "maori_dict.db"

    def test_the_app_entry_count_matches_staging(self):
        if not self.APP.exists():
            self.skipTest("app DB not built")
        stg = sqlite3.connect(DB_PATH)
        app = sqlite3.connect(self.APP)
        for table in ("entry", "sense", "relation"):
            with self.subTest(table=table):
                self.assertEqual(
                    app.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    stg.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    f"{table}: app DB is stale — run 59_rebuild_derived.py")
        stg.close()
        app.close()


class DerivedTablesArePopulated(unittest.TestCase):
    """Catch a skipped 52 / 08b / 53 / 54, which AppDbIsNotStale cannot see.

    50_build_unified empties ETY_entry_link, pollex_entry_links, derivation
    and loan_origin whenever it rewrites a source's slice; only the full
    59_rebuild_derived.py chain refills them. Skipping one of those steps
    leaves staging's own derived tables stale or empty, but 60_export_app_db
    then copies that same (broken) state into the app DB, so app and staging
    agree and AppDbIsNotStale passes anyway. This test instead asserts each
    table in staging clears a floor well below its current count, so ordinary
    drift stays quiet and a step-skip that empties or guts a table is loud.

    concept and concept_member are the exception, and their floors are worth
    less than the others: 50_build_unified does NOT empty them — they hold
    sweep judgements, so it only nulls their entry_id/sense_id cache — and a
    skipped 54 therefore sails over a floor on the PREVIOUS build's rows.
    The floors stay because they still catch a genuinely emptied table; the
    entry-cache test below is what actually detects a skipped 54.

    The counts below did NOT move when the gloss-evidence rule changed to
    coverage/distinctiveness (2026-09-13), and that is worth knowing rather
    than surprising: both gloss kinds are evidence, so a pair attaches either
    way and the thresholds move only a concept's confidence TIER, never the
    grouping. Re-tuning them therefore cannot trip any floor here — it shows
    up in the tier split and in what the app receives, not in these totals.
    """

    FLOORS = {
        "ETY_entry_link":     100_000,   # currently 160,712 — needs step 52
        "pollex_entry_links":  40_000,   # currently  57,189 — needs step 08b
        "derivation":           5_000,   # currently   6,778 — needs step 53
        "loan_origin":             50,   # currently     109 — needs step 53
        "concept":              50_000,  # currently  95,116 — needs step 54
        "concept_member":      100_000,  # currently 175,101 — needs step 54
    }

    def test_derived_tables_clear_their_floor(self):
        con = sqlite3.connect(DB_PATH)
        for table, floor in self.FLOORS.items():
            with self.subTest(table=table):
                count = con.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                self.assertGreaterEqual(
                    count, floor,
                    f"{table}: only {count} rows (floor {floor}) — "
                    "staging's derived tables look stale or emptied by "
                    "50_build_unified; run 59_rebuild_derived.py")
        con.close()

    def test_every_concept_member_has_its_entry_cache(self):
        """The assertion that CAN see a skipped 54.

        50_build_unified nulls concept_member.entry_id/sense_id for the
        source it rewrites (the membership is keyed on the stable address;
        entry.id is volatile), and only 54_build_concepts re-resolves it.
        So a populated concept_member holding rows with a NULL entry_id
        means the chain stopped somewhere before 54.
        """
        con = sqlite3.connect(DB_PATH)
        total, orphaned = con.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE entry_id IS NULL) "
            "  FROM concept_member").fetchone()
        con.close()
        self.assertGreater(total, 0, "concept_member is empty — run "
                                     "59_rebuild_derived.py")
        self.assertEqual(
            orphaned, 0,
            f"{orphaned:,} of {total:,} concept_member rows have no entry_id: "
            "50_build_unified released the cache and 54_build_concepts never "
            "re-resolved it — run 59_rebuild_derived.py")


if __name__ == "__main__":
    unittest.main()
