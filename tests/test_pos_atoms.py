"""Splitting a raw POS string into atomic codes.

Te Matatiki and Kimikupu Hou bracket their POS — '[noun, transitive verb]' — so
splitting on the comma severed the brackets and produced '[noun' and
'transitive verb]', neither of which is in std_pos and neither of which is a
part of speech. 38 atoms covering 5,371 sense-atoms were unmapped; most of them
resolve against the EXISTING std_pos once the brackets come off.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import pos_atoms


class PosAtoms(unittest.TestCase):
    def test_a_bracketed_composite_splits_without_losing_its_brackets(self):
        self.assertEqual(pos_atoms("[noun, transitive verb]"),
                         ["noun", "transitive verb"])

    def test_a_bracketed_single_value_loses_the_brackets(self):
        self.assertEqual(pos_atoms("[noun]"), ["noun"])

    def test_an_unbracketed_composite_is_unaffected(self):
        self.assertEqual(pos_atoms("mahp, ing, āhua"), ["mahp", "ing", "āhua"])

    def test_three_way_bracketed_composite(self):
        self.assertEqual(
            pos_atoms("[transitive verb, intransitive verb, noun]"),
            ["transitive verb", "intransitive verb", "noun"])

    def test_a_trailing_domain_qualifier_is_dropped(self):
        # 'noun (volleyball)', 'noun (justice)' are nouns; the parenthetical is
        # a subject note, not part of the part of speech.
        self.assertEqual(pos_atoms("[noun (volleyball)]"), ["noun"])
        self.assertEqual(pos_atoms("adjective (awake)"), ["adjective"])

    def test_a_bare_parenthesised_code_keeps_its_word(self):
        self.assertEqual(pos_atoms("(prefix)"), ["prefix"])

    def test_a_stray_bracket_inside_the_value_is_tolerated(self):
        # '[noun ](committee)' — the source closed the bracket mid-value.
        self.assertEqual(pos_atoms("[noun ](committee)"), ["noun"])

    def test_case_is_preserved(self):
        # std_pos keys are case-sensitive; 'Phrase' and 'phrase' are separate
        # raw forms and both are mapped there.
        self.assertEqual(pos_atoms("Phrase"), ["Phrase"])

    def test_nothing(self):
        self.assertEqual(pos_atoms(""), [])
        self.assertEqual(pos_atoms(None), [])
        self.assertEqual(pos_atoms("[]"), [])


if __name__ == "__main__":
    unittest.main()
