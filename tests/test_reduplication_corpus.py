"""Reduplication, counted against the built database.

papakupu states its reduplications in prose; we parse them and infer
nothing. Measured on 2026-09-21 after the rebuild:

    derivation total          11,424 -> 11,442   (+18)
    process='reduplication'      279 ->    302
      279 williams, + 5 relabelled from 'suffix', + 18 papakupu
    process='suffix'           5,175 ->  5,170
    process='prefix'             661 ->    662
    process NULL                  38 ->     37

61 rows on the derived_from path had their affix corrected by the
strict-then-fallback normalisation: 'whaka-' was stored as 'whak-', '-ia'
as '-a'.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

EXPECTED_PROCESS = {
    "compound": 5271,
    "suffix": 5170,
    "prefix": 662,
    "reduplication": 302,
}


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class Reduplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_the_process_distribution_is_exact(self):
        got = dict(self.con.execute(
            "SELECT process, COUNT(*) FROM derivation "
            "WHERE process IS NOT NULL GROUP BY 1").fetchall())
        self.assertEqual(got, EXPECTED_PROCESS)

    def test_papakupu_contributed_eighteen_reduplications(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence = 'papakupu: stated as a reduplicated form'"), 18)

    def test_every_papakupu_reduplication_is_attested_not_segmented(self):
        # The source said so in a sentence.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence LIKE 'papakupu: stated%' "
            "  AND (derived <> 0 OR confidence <> 'certain')"), 0)

    def test_a_stated_reduplication_carries_no_affix(self):
        # process comes from the sentence, not from the spellings; a
        # non-NULL affix here means describe_derivation was consulted.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence LIKE 'papakupu: stated%' AND affix IS NOT NULL"), 0)

    def test_the_named_pairs_are_present(self):
        for child, base in (("ekeeke", "eke"), ("nanao", "nao"),
                            ("roroa", "roa"), ("waruwaru", "waru"),
                            ("whīwhiwhi", "whiwhi"), ("tukutuku", "tuku")):
            with self.subTest(child=child):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM derivation d "
                    "JOIN entry e ON e.id = d.entry_id "
                    "WHERE e.source_id = 'papakupu' AND e.headword = ? "
                    "  AND d.base_form = ?", child, base), 1)

    def test_the_traps_were_not_harvested(self):
        # takapau's entry discusses the cognate momoe; puri's names pupuhi,
        # which comes from puhi. Neither is a reduplication of the entry
        # that mentions it.
        #
        # Named as PAIRS, not as bases. 'puri' is legitimately the base of
        # 'pupuri', one of the eighteen, so banning the base word would fail
        # on real data. And both 'momoe' and 'pupuhi' carry derivation rows
        # of their own from other sources — momoe < Moe in williams, pupuhi
        # as a paekupu compound — which have nothing to do with these traps.
        for child, base in (("momoe", "takapau"), ("pupuhi", "puri")):
            with self.subTest(pair=f"{child} < {base}"):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM derivation d "
                    "JOIN entry c ON c.id = d.entry_id "
                    "JOIN entry t ON t.id = d.base_entry_id "
                    "WHERE c.headword = ? AND t.headword = ?", child, base), 0)

    def test_the_legitimate_pair_from_a_trap_entry_survived(self):
        # The filter rejects puri's statement about pupuhi without touching
        # the true 'pupuri < puri' the same word licenses elsewhere.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation d "
            "JOIN entry c ON c.id = d.entry_id "
            "JOIN entry t ON t.id = d.base_entry_id "
            "WHERE c.headword = 'pupuri' AND t.headword = 'puri' "
            "  AND d.process = 'reduplication'"), 1)

    def test_the_prefix_is_no_longer_truncated(self):
        # 'whaka-' was stored as 'whak-' in 17 rows.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE affix = 'whak-'"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM derivation WHERE affix = 'whaka-'"), 100)

    def test_the_five_relabelled_doublings_are_reduplications(self):
        for word in ("awaawa", "eneene", "eweewe", "ikiiki", "ohooho"):
            with self.subTest(word=word):
                self.assertEqual(self._one(
                    "SELECT d.process FROM derivation d "
                    "JOIN entry e ON e.id = d.entry_id "
                    "WHERE e.headword = ? AND e.source_id = 'williams'",
                    word), "reduplication")

    def test_nothing_is_derived_from_itself(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE entry_id = base_entry_id"), 0)

    def test_the_compound_rows_were_not_touched(self):
        # They never pass through describe_derivation; a change here means
        # the normalisation fix reached further than its path.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE process = 'compound'"), 5271)


if __name__ == "__main__":
    unittest.main()