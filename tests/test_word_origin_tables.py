"""`derivation` and `loan_origin` hold only what a source stated (D38).

Step 1 of both design notes: attested rows only, `derived = 0`. The value of
these tables is that every row can be traced to a source that said so, so the
assertions here are about that discipline rather than about volume.

  derivation   6,778 rows — Williams sub-entries (D36), Te Matatiki bracketed
               components, Paekupu component notes
  loan_origin  109 rows — only where the source names a language or the word
               borrowed from. A marker saying merely 'borrowed' earns no row;
               entry.loan_marker already records that for 22,832 entries.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


class WordOriginTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_every_derivation_row_is_attested(self):
        # Step 1 asserts nothing of its own. When step 2 adds the segmented
        # whaka-/reduplication/-tanga rows they will carry derived = 1, and
        # this becomes the count of the attested half.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE derived <> 0"), 0)

    def test_every_derivation_row_names_its_evidence(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence IS NULL OR TRIM(evidence) = ''"), 0)

    def test_derivations_resolve_to_a_base_entry(self):
        # A derivation whose base is only a string is not usable by the app or
        # the concept layer; the whole point is that these already resolve.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE base_entry_id IS NULL"), 0)

    def test_a_compound_never_names_the_same_base_twice(self):
        # Position is meaning, so a repeat renumbers the components after it.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM (SELECT entry_id, base_entry_id FROM derivation "
            " WHERE process = 'compound' GROUP BY entry_id, base_entry_id "
            " HAVING COUNT(*) > 1)"), 0)

    def test_nothing_is_derived_from_itself(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE entry_id = base_entry_id"), 0)

    def test_the_attested_derivations_are_all_there(self):
        self.assertGreater(self._one("SELECT COUNT(*) FROM derivation"), 6500)

    def test_every_loan_origin_row_carries_an_origin(self):
        # The fact of borrowing lives on entry.loan_marker. This table is for
        # where the word came FROM, and a row with neither is noise.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM loan_origin "
            "WHERE source_lang IS NULL AND source_word IS NULL"), 0)

    def test_loan_origins_are_attested(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM loan_origin WHERE derived <> 0"), 0)

    def test_papakupu_supplies_the_english_borrowings(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM loan_origin WHERE source_lang = 'English'"), 80)

    def test_paekupu_names_languages_other_than_english(self):
        # The only place in 153,543 entries where a non-English origin is data.
        self.assertGreater(self._one(
            "SELECT COUNT(DISTINCT source_lang) FROM loan_origin "
            "WHERE source_lang LIKE 'reo %'"), 5)


if __name__ == "__main__":
    unittest.main()
