"""Williams's '=' marks a variant; it was never extracted.

The parser handles the '‖' marker ("compare") and turns it into see_also and
citation rows, but '=' — which Williams uses for "is the same as" — was left
sitting in the gloss. 680 senses open with it and 611 of those entries carry no
relation at all, so the variant link is invisible:

    Ahine  '= wahine.'
    Ahore  '= kahore, ad. Not.'
    Ahau   '= au, awau, awahau, pron. 1s...'

The shape is '= target[, target...][, POS.] rest', so the POS and the real gloss
are stranded behind the reference as well.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from williams_xref import parse_equals_variants


class ParseEqualsVariants(unittest.TestCase):
    def test_a_bare_reference_yields_one_target_and_no_remainder(self):
        self.assertEqual(parse_equals_variants("= wahine."), (["wahine"], ""))

    def test_a_reference_followed_by_pos_and_gloss_keeps_both(self):
        self.assertEqual(parse_equals_variants("= kahore, ad. Not."),
                         (["kahore"], "ad. Not."))

    def test_several_targets_are_all_captured(self):
        self.assertEqual(
            parse_equals_variants("= au, awau, awahau, pron. 1st pers. sing."),
            (["au", "awau", "awahau"], "pron. 1st pers. sing."))

    def test_a_definition_without_a_leading_equals_is_untouched(self):
        self.assertEqual(parse_equals_variants("Heap up. He mea ahuahu nga puke."),
                         ([], "Heap up. He mea ahuahu nga puke."))

    def test_an_equals_later_in_the_text_is_not_a_headword_reference(self):
        # '... = tuahine.' mid-definition is a gloss equivalence, not the
        # entry-level variant marker, and must not be lifted out.
        text = "Sister of a male. Tahu. = tuahine."
        self.assertEqual(parse_equals_variants(text), ([], text))

    def test_the_marker_may_carry_a_homograph_number(self):
        self.assertEqual(parse_equals_variants("= ara (ii)."), (["ara (ii)"], ""))

    def test_a_target_list_ending_at_a_verb_pos(self):
        self.assertEqual(parse_equals_variants("= ai, v.t. Beget."),
                         (["ai"], "v.t. Beget."))

    def test_empty(self):
        self.assertEqual(parse_equals_variants(""), ([], ""))
        self.assertEqual(parse_equals_variants(None), ([], ""))

    def test_an_equals_with_nothing_after_it_yields_nothing(self):
        self.assertEqual(parse_equals_variants("="), ([], "="))



class HeadTerminatesAtTheFirstStop(unittest.TestCase):
    def test_numbered_senses_after_the_variant_are_not_swallowed(self):
        # `Hakirara`: '= hakurara.' then the entry's own three numbered senses.
        # Splitting on commas first consumed the lot as six targets.
        targets, rest = parse_equals_variants(
            "= hakurara. 1. a. Idling, trifling, lying. 2. v.t. Annoy, insult.")
        self.assertEqual(targets, ["hakurara"])
        self.assertTrue(rest.startswith("1. a. Idling"))

    def test_a_pos_abbreviation_is_returned_to_the_definition(self):
        targets, rest = parse_equals_variants("= kahore, ad. Not.")
        self.assertEqual(targets, ["kahore"])
        self.assertEqual(rest, "ad. Not.")

if __name__ == "__main__":
    unittest.main()
