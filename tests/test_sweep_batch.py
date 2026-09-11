"""The audit sweep's batch assembler.

One cluster, every source's entries for it, their senses, examples, forms,
relations and domains, plus every cognate set linked into it — assembled into
the single view the sweep judges.

Integration test against the built staging DB: the assembler is SQL over the
real schema, and mirroring six tables in memory would test the mirror.

Addresses in a batch are `source_id:source_entry_id` (plus sense_number), never
`entry.id`, which is volatile across rebuilds. A judgement has to name something
a patch can still find after the next projection.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH
from sweep_batch import assemble, render


class Assemble(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)
        cls.con.row_factory = sqlite3.Row
        cls.aho = assemble(cls.con, "aho")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_whole_cluster_is_present(self):
        self.assertEqual(self.aho["cluster_key"], "aho")
        self.assertGreater(self.aho["entry_count"], 30)
        self.assertGreater(self.aho["source_count"], 5)
        self.assertEqual(len(self.aho["entries"]), self.aho["entry_count"])

    def test_every_entry_carries_a_patchable_address(self):
        for e in self.aho["entries"]:
            self.assertEqual(e["address"], f"{e['source_id']}:{e['source_entry_id']}")
            self.assertNotIn("entry_id", e)   # volatile; must not be quotable

    def test_senses_hang_off_their_entry(self):
        self.assertTrue(any(e["senses"] for e in self.aho["entries"]))
        for e in self.aho["entries"]:
            for s in e["senses"]:
                self.assertIn("gloss_en", s)
                self.assertIn("definition_raw", s)

    def test_entries_are_grouped_by_source(self):
        srcs = [e["source_id"] for e in self.aho["entries"]]
        self.assertEqual(srcs, sorted(srcs))

    def test_etymology_is_included_with_its_target(self):
        ety = self.aho["etymology"]
        self.assertTrue(ety)
        for link in ety:
            self.assertIn("protoform", link)
            self.assertIn("gloss", link)
            self.assertIn(":", link["entry_address"])

    def test_competing_cognate_sets_on_one_entry_are_all_shown(self):
        # `aho` is the case the design is built around: 'cord' and 'daylight'
        # both attach to the same entry, and at most one can be right. The
        # sweep cannot judge that unless it sees both.
        per_entry = {}
        for link in self.aho["etymology"]:
            per_entry.setdefault(link["entry_address"], []).append(link)
        self.assertTrue(any(len(v) > 1 for v in per_entry.values()))

    def test_a_single_source_cluster_still_assembles(self):
        key = self.con.execute(
            "SELECT headword_search FROM entry GROUP BY headword_search "
            "HAVING COUNT(DISTINCT source_id) = 1 LIMIT 1").fetchone()[0]
        b = assemble(self.con, key)
        self.assertEqual(b["source_count"], 1)
        self.assertTrue(b["entries"])

    def test_an_unknown_cluster_is_empty_not_an_error(self):
        b = assemble(self.con, "zzzznotacluster")
        self.assertEqual(b["entry_count"], 0)
        self.assertEqual(b["entries"], [])


class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)
        cls.con.row_factory = sqlite3.Row
        cls.text = render(assemble(cls.con, "aho"))

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_the_cluster_key_heads_the_view(self):
        self.assertIn("aho", self.text.splitlines()[0])

    def test_addresses_are_rendered_for_quoting_in_a_finding(self):
        self.assertIn("williams:", self.text)
        self.assertIn("te_aka:", self.text)

    def test_the_etymology_section_is_rendered(self):
        self.assertIn("ETYMOLOGY", self.text)

    def test_an_empty_cluster_renders_without_blowing_up(self):
        self.assertIsInstance(render(assemble(self.con, "zzzznotacluster")), str)


if __name__ == "__main__":
    unittest.main()
