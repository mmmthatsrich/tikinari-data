"""The last four papakupu tokens: three by rule, one by ruling.

After the suffix reader and the reduplication reader have taken theirs,
four tilde tokens were still refused. Three of them compose into a word
that ENDS in a vocabulary suffix, which is the same test _classify_whole
already applies to paekupu's whole irregular forms:

    mea        ~tingia     meatingia           ends -ngia   passive
    mea        ~tinga      meatinga            ends -inga   nominalisation
    whakamātau ~tauranga   whakamātautauranga  ends -ranga  nominalisation

The note records the suffix the ENDING shows, not the token papakupu
wrote, because that is what makes the per-suffix counts answerable — and
', by ending' marks that the class was read off the composed form rather
than printed by the source.

The fourth, 'uku ~i' giving 'ukui', ends in no suffix at all. It is a
variant form of 'uku' — the passives are 'ukua' and 'ukuia' — which is the
project owner's judgement, not a rule, and it is hardcoded as such.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import read_tilde_by_ending


class ByEnding(unittest.TestCase):
    def test_a_composed_passive_is_claimed(self):
        self.assertEqual(
            read_tilde_by_ending("mea", "~tingia, ~tanga this word stands"),
            [("meatingia", "passive", "-ngia")])

    def test_a_composed_nominalisation_is_claimed(self):
        self.assertEqual(
            read_tilde_by_ending("whakamātau", "~tauranga to teach"),
            [("whakamātautauranga", "nominalisation", "-ranga")])

    def test_the_longest_ending_wins(self):
        # 'meatinga' ends in '-nga' and in '-inga'; the longer is right,
        # the same longest-match rule the rest of the module applies.
        self.assertEqual(
            read_tilde_by_ending("mea", "~tinga"),
            [("meatinga", "nominalisation", "-inga")])

    def test_a_token_that_is_already_a_suffix_is_left_alone(self):
        # '~tia' is a real suffix; the suffix reader owns it.
        self.assertEqual(read_tilde_by_ending("uku", "~a, ~nga wash"), [])

    def test_a_composition_ending_in_no_suffix_is_refused(self):
        # 'ukui' ends in 'i', which is not in the vocabulary.
        self.assertEqual(read_tilde_by_ending("uku", "~i wash"), [])

    def test_a_spaced_tilde_is_prose_and_is_refused(self):
        self.assertEqual(
            read_tilde_by_ending("teina", "Tuakana / Teina ~ taina."), [])

    def test_a_hedged_token_asserts_nothing(self):
        self.assertEqual(read_tilde_by_ending("mānu", "~iatia (?) drift"), [])

    def test_a_definition_with_no_tilde_yields_nothing(self):
        self.assertEqual(read_tilde_by_ending("ahu", "tend, foster"), [])


class DoesNotStealFromTheReduplications(unittest.TestCase):
    """The two readers are disjoint by construction, not by call order."""

    def test_a_doubling_with_a_suffix_is_left_to_the_other_reader(self):
        # 'hokohokoa' ends in '-a', so this reader would happily take it.
        # Running second was not enough: both readers saw the token and the
        # row landed twice, once 'reduplication' and once 'passive',
        # because add_form dedups on (entry, form, TYPE).
        self.assertEqual(read_tilde_by_ending("hoko", "~hokoa buy, sell"), [])

    def test_the_plain_doublings_are_left_alone_too(self):
        for hw, tok in (("ue", "ue"), ("rou", "roua"), ("ui", "uia")):
            with self.subTest(token=tok):
                self.assertEqual(
                    read_tilde_by_ending(hw, f"~{tok} gloss"), [])


if __name__ == "__main__":
    unittest.main()
