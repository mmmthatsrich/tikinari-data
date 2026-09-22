"""ngata's confidence, counted against the built database.

ngata never states which member of a comma-separated run derives from
which, so the pairing is our segmentation and every row stays derived = 1.
What confidence now records is whether a DIFFERENT dictionary independently
recognises the same word as a derived form.

Measured on 2026-09-22:

    ngata certain    3,797   another source records the form   (82%)
    ngata probable     849   rests on ngata's run alone        (18%)

The 849 are the review queue: a blanket 'probable' over all 4,646 pointed
at nothing, and a wrong segmentation would hide in exactly these rows.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class NgataConfidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_the_split_is_exact(self):
        got = dict(self.con.execute(
            "SELECT confidence, COUNT(*) FROM derivation "
            "WHERE evidence LIKE 'ngata%' GROUP BY 1").fetchall())
        self.assertEqual(got, {"certain": 3797, "probable": 849})

    def test_every_ngata_row_is_still_our_segmentation(self):
        # Corroboration raises confidence, never attestation. ngata did not
        # state the pairing whatever anyone else records.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence LIKE 'ngata%' AND derived <> 1"), 0)

    def test_the_stated_sources_are_untouched(self):
        # williams, te_matatiki, paekupu and papakupu pair the words
        # themselves, so they stay attested and certain.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence NOT LIKE 'ngata%' "
            "  AND (derived <> 0 OR confidence <> 'certain')"), 0)

    def test_a_certain_row_really_has_outside_support(self):
        # The claim, asserted over every row rather than a sample: no
        # ngata row is 'certain' unless another source records that exact
        # form as a passive or nominalisation.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation d "
            "JOIN entry e ON e.id = d.entry_id "
            "WHERE d.evidence LIKE 'ngata%' AND d.confidence = 'certain' "
            "  AND NOT EXISTS (SELECT 1 FROM form f "
            "      JOIN entry e2 ON e2.id = f.entry_id "
            "      WHERE e2.source_id <> 'ngata' AND f.form = e.headword "
            "        AND f.form_type IN ('passive','nominalisation'))"), 0)

    def test_a_probable_row_really_has_none(self):
        # And the converse, so the queue is neither padded nor short.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation d "
            "JOIN entry e ON e.id = d.entry_id "
            "WHERE d.evidence LIKE 'ngata%' AND d.confidence = 'probable' "
            "  AND EXISTS (SELECT 1 FROM form f "
            "      JOIN entry e2 ON e2.id = f.entry_id "
            "      WHERE e2.source_id <> 'ngata' AND f.form = e.headword "
            "        AND f.form_type IN ('passive','nominalisation'))"), 0)

    def test_the_table_is_unchanged_in_size(self):
        # Only confidence moved; no row was added, lost or relabelled.
        self.assertEqual(self._one("SELECT COUNT(*) FROM derivation"), 11444)
        self.assertEqual(dict(self.con.execute(
            "SELECT process, COUNT(*) FROM derivation "
            "WHERE process IS NOT NULL GROUP BY 1").fetchall()),
            {"compound": 5271, "suffix": 5170, "prefix": 662,
             "reduplication": 304})


if __name__ == "__main__":
    unittest.main()
