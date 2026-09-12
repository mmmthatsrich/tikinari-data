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


if __name__ == "__main__":
    unittest.main()
