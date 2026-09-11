"""A borrowed word cannot descend from Proto-Polynesian.

Te Aka marks 18,439 entries `Historical Loan Word` — transliterations of English
and biblical names and nouns. 8,314 etymology links attached Proto-Polynesian
cognate sets to 2,457 of them, purely because the Māori spelling of the loan
coincides with a Māori word:

    Aki    'Jack.'    <- PN.-QAKI.1  'Formative suffix to verbs'
    Ahua   'Asshur.'  <- NP.AAFUA    'Form, appearance, likeness'
    āka    'ark.'     <- a cognate set for the homophonous Māori word
    āmene  'amen.'

This is not a heuristic about likelihood: inheritance and borrowing are
mutually exclusive by definition, so the link is wrong wherever the marker is
right. Where the Māori word genuinely exists — `ama` is both 'yam' (borrowed)
and an outrigger float (inherited) — Te Aka carries separate entries, and the
set belongs on the one that is not marked.

Filtered at build time rather than deleted: ETY_entry_link is rewritten in full
on every run of 52_build_etymology_unified, so removing the filter restores the
links.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


class LoanwordsHaveNoProtoAncestry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)
        cls.con.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_no_loan_marked_entry_carries_a_cognate_set(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM ETY_entry_link l JOIN entry e ON e.id = l.entry_id "
            "WHERE e.loan_marker IS NOT NULL"), 0)

    def test_the_unmarked_homophone_keeps_its_etymology(self):
        # Removing the loan entry's link must not strip the real word's. 'ama'
        # is a borrowed 'yam' in one entry and an inherited word in another.
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM ETY_entry_link l JOIN entry e ON e.id = l.entry_id "
            "WHERE e.headword_search = 'ama' AND e.loan_marker IS NULL"), 0)

    def test_the_corpus_still_has_most_of_its_links(self):
        # A filter that removed far more than the 8,314 measured would mean the
        # marker is matching something it should not.
        self.assertGreater(self._one("SELECT COUNT(*) FROM ETY_entry_link"), 170000)


if __name__ == "__main__":
    unittest.main()
