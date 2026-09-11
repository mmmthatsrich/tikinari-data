"""POLLEX marks morpheme boundaries with '/', not alternatives (D33).

    PN.SOI.3  'Interjection expressing exasperation'   maori reflex 'Hoi/hoi'

The reflex is *hoihoi*, one word, segmented for the reader. Splitting on '/'
turned it into the key `hoi`, so all 17 `hoi` entries — ear lobe, earwax,
deaf, distant, the conjunction — acquired an exasperation etymology, while the
9 `hoihoi` entries glossed 'be noisy, deafening, loud' acquired none.

Commas and semicolons DO separate alternatives: 'Aa/ku, oo/ku' is āku and ōku,
two words, each with an internal boundary. So the split set loses '/' and the
character is removed inside each part instead, joining the morphemes back up.

619 of the 639 Māori reflexes containing '/' are of this shape; the rest join
into phrases that match no headword, which fails closed rather than open.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib
_linker = importlib.import_module("08b_pollex_entry_linker")
_reflex_keys = _linker._reflex_keys


class ReflexKeys(unittest.TestCase):
    def test_a_slash_joins_rather_than_splits(self):
        # The case that started it: the word is hoihoi, not hoi.
        self.assertEqual(_reflex_keys("Hoi/hoi"), {"hoihoi"})

    def test_a_suffix_boundary_joins(self):
        # 'Ahu/nga' is ahunga; splitting linked it to both ahu and nga.
        self.assertEqual(_reflex_keys("Ahu/nga"), {"ahunga"})

    def test_a_passive_boundary_joins(self):
        # POLLEX glosses 'Ranga/ia' as "Passive form of ra(ra)nga".
        self.assertEqual(_reflex_keys("Ranga/ia"), {"rangaia"})

    def test_a_comma_still_separates_alternatives(self):
        # 'Aa/ku, oo/ku' is two words, āku and ōku, each internally segmented.
        self.assertEqual(_reflex_keys("Aa/ku, oo/ku"), {"aku", "oku"})

    def test_a_semicolon_still_separates(self):
        self.assertEqual(_reflex_keys("Aho; Aki/aki"), {"aho", "akiaki"})

    def test_a_plain_reflex_is_unchanged(self):
        self.assertEqual(_reflex_keys("Aho"), {"aho"})

    def test_a_leading_or_trailing_slash_is_dropped(self):
        # 'H/ane/' is hane.
        self.assertEqual(_reflex_keys("H/ane/"), {"hane"})

    def test_empty_input(self):
        self.assertEqual(_reflex_keys(""), set())
        self.assertEqual(_reflex_keys(None), set())


class EtymologyBridgeKeys(unittest.TestCase):
    """52_build_etymology_unified mirrors the same keying and had the same bug.

    Its comment says "mirror 08b_pollex_entry_linker", and the two bridges must
    agree or the parity proof between them compares nothing. It also treats '|'
    as a separator, which stays.
    """

    def setUp(self):
        self.keys = importlib.import_module("52_build_etymology_unified")._reflex_keys

    def test_a_slash_joins_rather_than_splits(self):
        self.assertEqual(self.keys("Hoi/hoi"), {"hoihoi"})

    def test_a_suffix_boundary_joins(self):
        self.assertEqual(self.keys("Ahu/nga"), {"ahunga"})

    def test_a_comma_still_separates(self):
        self.assertEqual(self.keys("Aa/ku, oo/ku"), {"aku", "oku"})

    def test_a_pipe_still_separates(self):
        self.assertEqual(self.keys("Aho|Aki/aki"), {"aho", "akiaki"})

    def test_it_agrees_with_the_pollex_linker(self):
        for reflex in ("Hoi/hoi", "Ahu/nga", "Ranga/ia", "Aa/ku, oo/ku",
                       "H/ane/", "Aho", "Angi/angi"):
            self.assertEqual(self.keys(reflex), _reflex_keys(reflex), reflex)


if __name__ == "__main__":
    unittest.main()
