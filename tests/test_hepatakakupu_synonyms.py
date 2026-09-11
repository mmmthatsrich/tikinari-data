"""He Pātaka Kupu marks a synonym it does not define by wrapping it (D30).

The `synonyms` JSON array mixes two kinds of entry:

    ["parewhero", "tārukenga", "whakapiko", "(whārona awatea )"]

The parentheses are a source marker, not part of the term. Measured over the
whole source they separate almost perfectly: of the parenthesised synonyms 728
are NOT headwords in He Pātaka Kupu and 6 are; of the plain ones 13,922 ARE
headwords and 4 are not. The marker means "this word has no entry here".

Passed through verbatim, it produced 734 relations whose target can never
resolve, because no entry is named `(whārona awatea )`.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from hepatakakupu_synonyms import pair_synonyms, parse_synonym


class ParseSynonym(unittest.TestCase):
    def test_a_plain_synonym_is_a_term_with_an_entry(self):
        self.assertEqual(parse_synonym("parewhero"),
                         {"headword": "parewhero", "has_entry": True})

    def test_a_wrapped_synonym_loses_the_parens_and_is_marked(self):
        self.assertEqual(parse_synonym("(whārona awatea )"),
                         {"headword": "whārona awatea", "has_entry": False})

    def test_the_space_before_the_closing_paren_is_dropped(self):
        # Every wrapped value in the source carries it: '(pou tāuru )'.
        self.assertEqual(parse_synonym("(pou tāuru )")["headword"], "pou tāuru")

    def test_an_inner_parenthesis_survives(self):
        # '(tahi (i te) tahua )' is real. Only the outer pair is the marker;
        # '(i te)' belongs to the phrase.
        self.assertEqual(parse_synonym("(tahi (i te) tahua )")["headword"],
                         "tahi (i te) tahua")

    def test_a_multiword_plain_synonym_is_left_alone(self):
        # 'hikuwai o te tau' is unwrapped and IS a headword — length is not
        # what the marker encodes.
        self.assertEqual(parse_synonym("hikuwai o te tau"),
                         {"headword": "hikuwai o te tau", "has_entry": True})

    def test_empty_and_blank_yield_nothing(self):
        for raw in ("", "   ", "()", "(  )", None):
            self.assertIsNone(parse_synonym(raw), raw)

    def test_an_unbalanced_paren_is_not_treated_as_a_marker(self):
        # '(Āe' and '(tū atu' appear in the source. Without a closing paren
        # there is no marker to read, so the text is kept as it stands.
        self.assertEqual(parse_synonym("(tū atu"),
                         {"headword": "(tū atu", "has_entry": True})



class PairSynonyms(unittest.TestCase):
    """A synonym may name a sense of its target: 'hikoki (2)' (D35).

    He Pātaka Kupu splits each sense into its own entry row, so the sense
    pointer identifies the exact entry rather than merely narrowing it — which
    is the difference between a resolvable reference and an ambiguous one.

    The two lists come from JSON written by separate parser runs, so the
    pairing must survive a sense list that is short, absent, or longer.
    """

    def test_pairs_each_synonym_with_its_sense(self):
        self.assertEqual(
            pair_synonyms(["hikoki", "kōkeke"], [2, None]),
            [("hikoki", 2), ("kōkeke", None)])

    def test_a_missing_sense_list_yields_no_senses(self):
        self.assertEqual(pair_synonyms(["hikoki", "kōkeke"], None),
                         [("hikoki", None), ("kōkeke", None)])

    def test_a_short_sense_list_pads_with_none(self):
        self.assertEqual(pair_synonyms(["a", "b", "c"], [1]),
                         [("a", 1), ("b", None), ("c", None)])

    def test_a_longer_sense_list_is_truncated(self):
        self.assertEqual(pair_synonyms(["a"], [1, 2, 3]), [("a", 1)])

    def test_blank_synonyms_are_dropped_with_their_sense(self):
        self.assertEqual(pair_synonyms(["a", "  ", "c"], [1, 2, 3]),
                         [("a", 1), ("c", 3)])

    def test_no_synonyms(self):
        self.assertEqual(pair_synonyms([], [1]), [])
        self.assertEqual(pair_synonyms(None, None), [])


if __name__ == "__main__":
    unittest.main()
