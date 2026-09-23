"""papakupu's tilde can name a reduplication, not only a suffix.

Its notation says "append this to the headword". Usually the token is a
suffix — '~a' on 'uku' gives the passive 'ukua'. Sometimes it is the
headword again: '~ue' on 'ue' gives 'ueue', attested in five other
dictionaries.

That is not the inference the reduplication spec rejected. There we would
have picked a base out of the lexicon and guessed which word a doubling
came from. Here papakupu names BOTH strings and the relation between them
is arithmetic:

    ue         ~ue         ueue            token equals the headword
    ui         ~uia        uiuia           equals headword + a known suffix
    whakamātau ~tau        whakamātautau   equals the headword's final foot

A token that classifies as a real suffix never reaches these rules.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import Tally, read_tilde_reduplications, redup_kind


class Recognise(unittest.TestCase):
    def test_the_token_repeating_the_headword_is_a_doubling(self):
        self.assertEqual(redup_kind("ue", "ue"), "doubling")

    def test_a_macron_difference_does_not_break_it(self):
        # Comparison folds macrons; the stored form keeps them.
        self.assertEqual(redup_kind("mānu", "manu"), "doubling")

    def test_the_headword_plus_a_suffix_is_a_doubling_with_a_suffix(self):
        # 'uiuia' is 'uiui' with the passive '-a'.
        self.assertEqual(redup_kind("ui", "uia"), "doubling+suffix")

    def test_the_final_foot_counts(self):
        self.assertEqual(redup_kind("whakamātau", "tau"), "final foot")

    def test_an_unrelated_token_is_not_a_reduplication(self):
        for hw, tok in (("mea", "tingia"), ("uku", "i"),
                        ("whakamātau", "tauranga")):
            with self.subTest(token=tok):
                self.assertIsNone(redup_kind(hw, tok))

    def test_a_one_letter_tail_is_not_a_final_foot(self):
        # 'uku' ends in 'u'; '~u' must not read as reduplication.
        self.assertIsNone(redup_kind("uku", "u"))

    def test_a_token_identical_to_the_whole_headword_is_not_a_tail(self):
        # The doubling rule owns that case; the tail rule requires the
        # headword to be longer than the token.
        self.assertEqual(redup_kind("tau", "tau"), "doubling")

    def test_empty_input_is_tolerated(self):
        self.assertIsNone(redup_kind("", "ue"))
        self.assertIsNone(redup_kind("ue", ""))
        self.assertIsNone(redup_kind(None, None))


class Read(unittest.TestCase):
    def test_a_doubling_is_composed_onto_the_headword(self):
        self.assertEqual(
            read_tilde_reduplications("ue", "~ue . * a cry, exclamation"),
            ["ueue"])

    def test_a_real_suffix_is_left_to_the_suffix_reader(self):
        # '~a' on 'uku' is the passive 'ukua' and must not be claimed here.
        self.assertEqual(read_tilde_reduplications("uku", "~a, ~nga wash"), [])

    def test_a_mixed_run_yields_only_the_reduplication(self):
        self.assertEqual(
            read_tilde_reduplications("rou", "~rou, ~roua| [1] pull, poke"),
            ["rourou", "rouroua"])

    def test_the_stored_form_keeps_the_headwords_macrons(self):
        self.assertEqual(
            read_tilde_reduplications("whakamātau", "~tau, ~tauranga to teach"),
            ["whakamātautau"])

    def test_a_definition_with_no_tilde_yields_nothing(self):
        self.assertEqual(read_tilde_reduplications("ahu", "tend, foster"), [])

    def test_a_spaced_tilde_is_prose_and_is_refused(self):
        # The same rule the suffix reader applies: 'Teina ~ Taina' is "or".
        self.assertEqual(
            read_tilde_reduplications("teina", "Tuakana / Teina ~ teina."), [])

    def test_a_hedged_token_asserts_nothing(self):
        self.assertEqual(
            read_tilde_reduplications("ue", "~ue (?) a cry"), [])


class Tallied(unittest.TestCase):
    def test_a_claimed_token_moves_out_of_the_suffix_refusals(self):
        t = Tally()
        t.refuse("-ue")
        read_tilde_reduplications("ue", "~ue a cry", t)
        self.assertEqual(t.refused_of("suffix"), [])
        self.assertEqual(t.seen_of("reduplication"), 1)

    def test_a_token_the_suffix_reader_never_saw_is_not_invented(self):
        t = Tally()
        read_tilde_reduplications("ue", "~ue a cry", t)
        self.assertEqual(t.seen_of("reduplication"), 0)


if __name__ == "__main__":
    unittest.main()
