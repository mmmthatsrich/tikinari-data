"""`derivation` and `loan_origin` hold only what a source printed (D38).

Every row traces to a source, so the assertions here are about that discipline
rather than about volume. What each row does NOT share is how the source
supported it, and `derived` is the column that keeps the two apart:

  derivation   11,424 rows
               attested, derived = 0 (6,778) — Williams sub-entries (D36),
               Te Matatiki bracketed components, Paekupu component notes.
               The source itself paired the two words.
               segmented, derived = 1 (4,646) — ngata printed a word and its
               own passive in one comma-separated run ('ahu, ahutia, ahuna')
               and 50_build_unified's suffix rules matched the spellings. The
               run is the source's; the pairing within it is ours, so these
               carry 'probable' where the attested rows carry 'certain'.
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

    def test_only_ngata_supplies_segmented_derivations(self):
        # derived = 1 means the pairing is our segmentation, not the source's
        # statement. ngata is the only source that earns it; a second source
        # appearing here has skipped the warrant table in 53_build_word_origin.
        self.assertEqual(self.con.execute(
            "SELECT DISTINCT evidence FROM derivation WHERE derived <> 0"
        ).fetchall(), [("ngata: printed in one run with its base",)])

    def test_the_attested_rows_stay_attested(self):
        # The three sources that pair the words themselves must never drift
        # into derived = 1; that would erase the distinction the column exists
        # to record.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE derived <> 0 AND evidence NOT LIKE 'ngata%'"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM derivation WHERE derived = 0"), 6500)

    def test_a_segmented_row_is_certain_only_with_outside_support(self):
        # This test used to assert that NO segmented row was ever certain.
        # That was right while confidence was a blanket hedge over all of
        # ngata's 4,646, and it is wrong now: 3,797 of them name a derived
        # form that a different dictionary independently records, and a
        # hedge covering those pointed at nothing. The rule it was
        # protecting survives in sharper form — certainty still needs
        # evidence, it just no longer has to be the source's own statement.
        #
        # derived = 1 is untouched by any of this: ngata did not state the
        # pairing, whatever anyone else records.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation d "
            "JOIN entry e ON e.id = d.entry_id "
            "WHERE d.derived <> 0 AND d.confidence = 'certain' "
            "  AND NOT EXISTS (SELECT 1 FROM form f "
            "      JOIN entry e2 ON e2.id = f.entry_id "
            "      WHERE e2.source_id <> e.source_id AND f.form = e.headword "
            "        AND f.form_type IN ('passive','nominalisation'))"), 0)

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

    def test_the_derivations_are_all_there(self):
        # Floor, not a target: 6,778 attested + 4,646 segmented = 11,424.
        self.assertGreater(self._one("SELECT COUNT(*) FROM derivation"), 11000)

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
