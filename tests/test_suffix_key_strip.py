"""headword_search must not carry suffix notation (spec §5).

paekupu writes the suffix into the headword ('ahu ~nga') and te_aka sometimes
does too ('āmine (-tia)'). Keyed that way, 1,407 paekupu entries and 322
te_aka entries can never meet the plain 'ahu' and 'amine' that four other
sources hold.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import strip_suffix_notation
from utils import DB_PATH, normalise_search_key


class TheKeyIsBuiltFromTheBareWord(unittest.TestCase):
    def test_a_paekupu_headword(self):
        self.assertEqual(
            normalise_search_key(strip_suffix_notation("ahu ~nga")), "ahu")

    def test_a_te_aka_headword(self):
        self.assertEqual(
            normalise_search_key(strip_suffix_notation("āmine (-tia)")),
            "amine")


class TheBuiltDatabaseAgrees(unittest.TestCase):
    """Runs against the real staging database after a re-import."""

    @classmethod
    def setUpClass(cls):
        # Read-only: this suite must never be able to alter the working
        # database it measures. See tests/test_suffix_extraction.py.
        cls.con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_no_paekupu_key_carries_a_tilde(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM paekupu_entries "
            "WHERE headword_search LIKE '%~%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_no_te_aka_key_carries_a_suffix_paren(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM te_aka_entries "
            "WHERE headword_search LIKE '%(-%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_the_headwords_themselves_are_untouched(self):
        # The archive keeps what the source wrote.
        n = self.con.execute(
            "SELECT COUNT(*) FROM paekupu_entries "
            "WHERE headword LIKE '%~%'").fetchone()[0]
        self.assertEqual(n, 1407)
