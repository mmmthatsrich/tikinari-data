"""Williams prints derivatives inside the base entry's paragraph (D36).

    Iti, a. Small ... itinga, n. Childhood, youth.
    Ae ... whakaae, v.t. Consent, agree.
    Akahu ... akahukahu, n. ...

01_williams_parse already splits those out and records `parent_headword` on
each of the 2,956 sub-entries. The import then drops it: williams_entries has
no such column, so the derivation Williams states by layout never reaches the
database.

2,801 of the 2,956 sub-headwords contain the parent's search key outright. The
remainder do not because the parent STRING carries decoration the key does
not: a roman homograph marker ('Hē (i)'), a trailing colon ('Ahuru mowai:'),
an equals clause ('Hāware (i) = huare, hauware') or an OCR slip in the first
of several variants ('Eml, emiemi').

parent_candidates turns that string into the keys worth trying, in order,
each with any roman sense it carried — so pick_target can settle a homograph
exactly as it does for see_also.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from williams_xref import parent_candidates, supported_parents


class ParentCandidates(unittest.TestCase):
    def test_a_plain_parent(self):
        self.assertEqual(parent_candidates("Ae"), [("ae", None)])

    def test_a_macron_is_folded_into_the_key(self):
        self.assertEqual(parent_candidates("Āhua"), [("ahua", None)])

    def test_a_roman_marker_is_kept_as_the_sense(self):
        self.assertEqual(parent_candidates("Hē (i)"), [("he", "i")])

    def test_a_trailing_colon_is_dropped(self):
        self.assertEqual(parent_candidates("Ahuru mowai:"),
                         [("ahuru mowai", None), ("ahuru", None)])

    def test_an_equals_clause_is_not_part_of_the_headword(self):
        # 'Hāware (i) = huare, hauware' — the base is hāware; huare and hauware
        # are what Williams says it equals, not further parents.
        self.assertEqual(parent_candidates("Hāware (i) = huare, hauware"),
                         [("haware", "i")])

    def test_comma_separated_variants_are_all_offered(self):
        # 'Eml, emiemi' — Eml is an OCR slip for Emi, so the second variant is
        # the one that will resolve. Both are offered, in order.
        self.assertEqual(parent_candidates("Eml, emiemi"),
                         [("eml", None), ("emiemi", None)])

    def test_a_multiword_parent_offers_the_first_word_as_a_fallback(self):
        self.assertEqual(parent_candidates("Hanga kino"),
                         [("hanga kino", None), ("hanga", None)])

    def test_a_single_word_offers_no_duplicate_fallback(self):
        self.assertEqual(parent_candidates("Akahu"), [("akahu", None)])

    def test_empty_input(self):
        self.assertEqual(parent_candidates(""), [])
        self.assertEqual(parent_candidates(None), [])


class SupportedParents(unittest.TestCase):
    """Only a parent the child's own spelling attests is a derivation.

    parent_headword is 'the base whose paragraph printed this', and on about
    one row in twenty that is merely the preceding headword on the page:
    williams records `itinga` under `Itaupa`, when its base is plainly `iti`.
    Asserting that would invent a derivation, so the claim is made only where
    the parent's key appears inside the child's — which is what a Maori
    derivative looks like, whether by prefix (whakaae), suffix (itinga) or
    reduplication (akahukahu).
    """

    def test_a_prefix_derivative_is_supported(self):
        self.assertEqual(supported_parents("Ae", "whakaae"), [("ae", None)])

    def test_a_suffix_derivative_is_supported(self):
        self.assertEqual(supported_parents("Iti", "itinga"), [("iti", None)])

    def test_a_reduplication_is_supported(self):
        self.assertEqual(supported_parents("Akahu", "akahukahu"),
                         [("akahu", None)])

    def test_the_page_neighbour_is_not_a_parent(self):
        # The real itinga row: Williams printed it under Itaupa.
        self.assertEqual(supported_parents("Itaupa", "itinga"), [])

    def test_a_variant_that_fits_is_preferred_over_one_that_does_not(self):
        # 'Arohaki, arowhaki' — only the second is inside aroarowhaki.
        self.assertEqual(supported_parents("Arohaki, arowhaki", "aroarowhaki"),
                         [("arowhaki", None)])

    def test_a_parent_identical_to_the_child_is_not_a_derivation(self):
        # 'Eml, emiemi' under emiemi: the OCR slip resolves to nothing and the
        # good variant IS the child, so there is no derivation to record.
        self.assertEqual(supported_parents("Eml, emiemi", "emiemi"), [])

    def test_the_roman_sense_survives_the_filter(self):
        self.assertEqual(supported_parents("Hē (i)", "whakahē"), [("he", "i")])

    def test_empty_input(self):
        self.assertEqual(supported_parents("", "whakaae"), [])
        self.assertEqual(supported_parents("Ae", ""), [])


if __name__ == "__main__":
    unittest.main()
