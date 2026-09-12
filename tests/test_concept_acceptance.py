"""The judged calibration clusters, as acceptance tests.

These are real answers, reasoned one cluster at a time during the sweep, so
they are the best check the machinery has. Each assertion names the finding it
came from.
"""
import importlib
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _concepts_on(self, key):
        return self.con.execute(
            "SELECT DISTINCT cm.concept_id FROM concept_member cm "
            "  JOIN entry e ON e.source_id = cm.source_id "
            "   AND e.source_entry_id = cm.source_entry_id "
            " WHERE e.headword_search = ?", (key,)).fetchall()

    def test_hiwi_is_many_words_not_one(self):
        # 18 entries, eight distinct words plus two loans.
        self.assertGreaterEqual(len(self._concepts_on("hiwi")), 6)

    def test_hia_never_joins_hiia(self):
        # 'hīa' is hī + -a, 'draw a breath'; it shares a key only because
        # headword_search strips macrons.
        rows = self.con.execute(
            "SELECT cm.concept_id, e.headword FROM concept_member cm "
            "  JOIN entry e ON e.source_id = cm.source_id "
            "   AND e.source_entry_id = cm.source_entry_id "
            " WHERE e.headword_search = 'hia'").fetchall()
        by_concept = {}
        for cid, hw in rows:
            by_concept.setdefault(cid, set()).add(hw.lower())
        for cid, hws in by_concept.items():
            self.assertFalse({"hia", "hīa"} <= hws, f"concept {cid}: {hws}")

    def test_himoemoe_unifies_its_sources(self):
        # Six sources, one word, no disagreement anywhere.
        counts = self.con.execute(
            "SELECT cm.concept_id, COUNT(DISTINCT cm.source_id) FROM concept_member cm"
            "  JOIN entry e ON e.source_id = cm.source_id "
            "   AND e.source_entry_id = cm.source_entry_id "
            " WHERE e.headword_search = 'himoemoe' GROUP BY 1").fetchall()
        self.assertTrue(any(n >= 4 for _cid, n in counts), counts)

    def test_paekupu_soy_is_not_an_ear_lobe(self):
        # paekupu:hoi 'soy, soya' is a loan and genuinely its own word.
        cid = self.con.execute(
            "SELECT concept_id FROM concept_member "
            " WHERE source_id='paekupu' AND source_entry_id='hoi'").fetchone()
        self.assertIsNotNone(cid)
        sources = self.con.execute(
            "SELECT COUNT(DISTINCT source_id) FROM concept_member "
            " WHERE concept_id = ?", cid).fetchone()[0]
        self.assertEqual(sources, 1)


class Invariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql):
        return self.con.execute(sql).fetchone()[0]

    def test_no_sense_is_in_two_concepts(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM (SELECT source_id, source_entry_id, "
            " sense_number FROM concept_member GROUP BY 1,2,3 HAVING COUNT(*)>1)"), 0)

    def test_an_elected_headword_was_written_by_a_member(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM concept c WHERE c.headword IS NOT NULL AND "
            " NOT EXISTS (SELECT 1 FROM concept_member cm "
            "   JOIN entry e ON e.source_id=cm.source_id "
            "    AND e.source_entry_id=cm.source_entry_id "
            "  WHERE cm.concept_id=c.id AND e.headword=c.headword)"), 0)

    def test_no_concept_holds_two_senses_from_different_williams_entries(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM (SELECT concept_id FROM concept_member "
            " WHERE source_id='williams' GROUP BY concept_id "
            " HAVING COUNT(DISTINCT source_entry_id) > 1)"), 0)

    def test_ngata_never_supplied_an_english_gloss(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM concept c JOIN concept_member m "
            "  ON m.id = c.gloss_en_from WHERE m.source_id = 'ngata'"), 0)


class AppExport(unittest.TestCase):
    """An uncertain grouping must not reach users, even by accident."""

    APP = Path(__file__).parent.parent / "data" / "maori_dict.db"

    def test_the_app_has_the_concept_tables(self):
        if not self.APP.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(self.APP)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertTrue({"concept", "concept_member"} <= names)

    def test_no_uncertain_concept_reaches_the_app(self):
        if not self.APP.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(self.APP)
        n = con.execute(
            "SELECT COUNT(*) FROM concept "
            " WHERE confidence = 'uncertain' AND status <> 'confirmed'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(n, 0)


class ExportFilter(unittest.TestCase):
    """What 60_export_app_db withholds, on a DB small enough to state outright.

    The real export runs against a 210 MB staging DB, so the rule itself is
    a function and this exercises that function directly.
    """

    def setUp(self):
        self.mod = importlib.import_module("60_export_app_db")
        self.con = sqlite3.connect(":memory:")
        self.con.executescript("""
            CREATE TABLE concept (id INTEGER PRIMARY KEY, status TEXT,
                confidence TEXT);
            CREATE TABLE concept_member (id INTEGER PRIMARY KEY,
                concept_id INTEGER, source_id TEXT, status TEXT);
        """)
        self.con.executemany(
            "INSERT INTO concept (id, status, confidence) VALUES (?,?,?)",
            [(1, "proposed", "certain"),      # ships
             (2, "proposed", "uncertain"),    # withheld
             (3, "confirmed", "uncertain"),   # ships: the sweep judged it
             (4, "proposed", "certain")])     # withheld: every member rejected
        self.con.executemany(
            "INSERT INTO concept_member (id, concept_id, source_id, status) "
            "VALUES (?,?,?,?)",
            [(10, 1, "te_aka", "proposed"),
             (11, 1, "papakupu", "rejected"),   # excluded from concept 1
             (12, 2, "te_aka", "proposed"),
             (13, 3, "te_aka", "confirmed"),
             (14, 4, "te_aka", "rejected")])   # the only member of concept 4
        self.con.commit()
        self.mod.filter_concepts(self.con)

    def _ids(self, table):
        return {r[0] for r in self.con.execute(f"SELECT id FROM {table}")}

    def test_an_uncertain_grouping_is_withheld(self):
        self.assertNotIn(2, self._ids("concept"))

    def test_a_confirmed_grouping_ships_however_thin_its_evidence(self):
        # The dead half of the export rule until the sweep could set this.
        self.assertIn(3, self._ids("concept"))

    def test_a_withheld_concepts_members_go_with_it(self):
        self.assertNotIn(12, self._ids("concept_member"))

    def test_a_concept_left_with_no_members_is_withheld(self):
        # 54_build_concepts keeps a wholly rejected grouping in staging as the
        # anchor its rejections name. Dropping the rejected rows here empties
        # it, and an empty concept is nothing to show a user.
        self.assertNotIn(4, self._ids("concept"))
        self.assertNotIn(14, self._ids("concept_member"))

    def test_a_rejected_membership_never_ships(self):
        # It is a record that the sense does NOT belong; shipping it would
        # show users the one grouping the sweep ruled out.
        self.assertNotIn(11, self._ids("concept_member"))
        self.assertEqual({10, 13}, self._ids("concept_member"))


if __name__ == "__main__":
    unittest.main()
