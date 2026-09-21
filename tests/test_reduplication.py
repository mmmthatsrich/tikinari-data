"""papakupu states its reduplications in prose; we parse, never infer.

Two shapes. Forward, where the entry IS the reduplication and names its
base — 'ekeeke: (Reduplicated form of eke [2])'. Inverse, where the entry is
the base and names its reduplication — 'hoko: In the reduplicated forms
hohoko and hokohoko...'.

The spelling test is a FILTER on those statements, never a generator: the
source has already asserted the derivation, and the test only rejects a
sentence that turns out to be about a different word.

See docs/superpowers/specs/2026-09-21-reduplication-design.md.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from reduplication import fold, is_plausible, read_reduplications


class Fold(unittest.TestCase):
    def test_macrons_are_stripped(self):
        self.assertEqual(fold("kōrero"), "korero")

    def test_a_doubled_vowel_survives(self):
        # The whole point. normalise_search_key folds 'ekeeke' to 'ekeke',
        # which destroys the seam that makes the reduplication visible.
        self.assertEqual(fold("ekeeke"), "ekeeke")

    def test_empty_input_is_tolerated(self):
        self.assertEqual(fold(None), "")


class Filter(unittest.TestCase):
    def test_a_full_reduplication_passes(self):
        self.assertTrue(is_plausible("ekeeke", "eke"))

    def test_an_initial_syllable_reduplication_passes(self):
        self.assertTrue(is_plausible("nunui", "nui"))

    def test_a_final_foot_reduplication_passes(self):
        self.assertTrue(is_plausible("kōrerorero", "kōrero"))

    def test_a_reduplication_inside_a_compound_passes(self):
        self.assertTrue(is_plausible("pāwerawera", "pāwera"))

    def test_a_two_mora_reduplication_passes(self):
        self.assertTrue(is_plausible("ariariā", "ariā"))

    def test_a_macron_mismatch_still_passes(self):
        # papakupu writes 'pūhakehake' against the base 'puhake'.
        self.assertTrue(is_plausible("pūhakehake", "puhake"))

    def test_an_unrelated_word_is_rejected(self):
        # takapau's entry discusses momoe, a Proto-Polynesian cognate.
        self.assertFalse(is_plausible("momoe", "takapau"))

    def test_a_source_slip_is_rejected(self):
        # puri's entry names pupuhi, which is really from puhi.
        self.assertFalse(is_plausible("pupuhi", "puri"))

    def test_prose_caught_by_the_regex_is_rejected(self):
        for word in ("includes", "embraces", "can", "listed"):
            with self.subTest(word=word):
                self.assertFalse(is_plausible(word, "take"))

    def test_a_word_is_not_a_reduplication_of_itself(self):
        self.assertFalse(is_plausible("eke", "eke"))


class ReadForward(unittest.TestCase):
    def test_a_parenthetical_statement_with_a_sense_number(self):
        self.assertEqual(
            read_reduplications(
                "ekeeke", "sexual movement (Reduplicated form of eke [2])"),
            [("ekeeke", "eke", 2)])

    def test_a_statement_without_a_sense_number(self):
        self.assertEqual(
            read_reduplications(
                "ariariā", "resemble, look like. (Reduplicated form of ariā)."),
            [("ariariā", "ariā", None)])

    def test_a_trailing_full_stop_is_not_part_of_the_base(self):
        self.assertEqual(
            read_reduplications(
                "kōrerorero", "chat (Reduplicated form of kōrero.)"),
            [("kōrerorero", "kōrero", None)])


    def test_the_shorter_wording_is_also_a_statement(self):
        # papakupu writes 'Reduplication of' as well as 'reduplicated form
        # of'. Matching only the longer wording silently dropped karokaro
        # and kakanga, two clean stated pairs.
        self.assertEqual(
            read_reduplications(
                "karokaro", "clear away. [WMS S. 10]. (Reduplication of karo [2])."),
            [("karokaro", "karo", 2)])

    def test_a_reduplication_that_is_only_part_of_the_formation_is_skipped(self):
        # 'kaitātaki' is the prefix kai- PLUS the reduplication of taki, so
        # it is not a reduplication OF taki — filing it as one would skip a
        # step and name the wrong base.
        self.assertEqual(
            read_reduplications(
                "kaitātaki",
                "speechmaker, from the agentive prefix kai-, plus "
                "reduplication of taki [2], make speeches."),
            [])

    def test_a_non_maori_token_is_not_a_base(self):
        # The base capture is Māori letters only, so a statement whose next
        # token is a digit yields nothing rather than reaching past it for
        # a word the source did not put there.
        self.assertEqual(
            read_reduplications(
                "matemate", "sickly (reduplicated form of 3 mate)"),
            [])

    def test_a_function_word_is_not_silently_accepted_as_a_base(self):
        # The live hazard. papakupu holds 'te' as an entry and 'te' is
        # inside 'matemate', so containment alone would accept it and ship
        # 'matemate < te' at confidence 'certain'. The base must be the
        # token the statement actually names.
        got = read_reduplications(
            "matemate", "sickly (reduplicated form of te kupu mate)")
        self.assertNotIn("te", [base for _, base, _ in got])


class ReadInverse(unittest.TestCase):
    def test_two_reduplications_named_with_and(self):
        self.assertEqual(
            read_reduplications(
                "hoko",
                "goods for sale. In the reduplicated forms hohoko and "
                "hokohoko, the focus is on the process."),
            [("hohoko", "hoko", None), ("hokohoko", "hoko", None)])

    def test_one_reduplication_named_in_prose(self):
        self.assertEqual(
            read_reduplications(
                "roa", "long. The reduplicated form roroa is often used."),
            [("roroa", "roa", None)])

    def test_a_comparative_note_about_another_word_is_rejected(self):
        # The trap: takapau's entry discusses momoe, which is no
        # reduplication of takapau.
        self.assertEqual(
            read_reduplications(
                "takapau",
                "mat. The reduplicated form momoe “sleep together” is "
                "inherited from a Proto Nuclear Polynesian term."),
            [])

    def test_the_word_of_is_never_taken_as_a_reduplication(self):
        # 'reduplicated form of X' is the FORWARD shape; the inverse reader
        # must not read 'of' as the named word.
        self.assertEqual(
            read_reduplications("emiemi", "gather. Reduplicated form of emi [1]"),
            [("emiemi", "emi", 1)])


class ReadNothing(unittest.TestCase):
    def test_a_definition_with_no_statement_yields_nothing(self):
        self.assertEqual(read_reduplications("ahu", "tend, foster, fashion"), [])

    def test_empty_input_is_tolerated(self):
        self.assertEqual(read_reduplications("ahu", None), [])
        self.assertEqual(read_reduplications(None, None), [])

    def test_the_same_pair_is_not_returned_twice(self):
        self.assertEqual(
            read_reduplications(
                "roa",
                "long. The reduplicated form roroa is used. "
                "See also the reduplicated form roroa."),
            [("roroa", "roa", None)])


if __name__ == "__main__":
    unittest.main()
