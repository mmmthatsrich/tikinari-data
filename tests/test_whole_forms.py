"""paekupu prints a whole irregular derivation where no fragment could work.

'hau ~hāua' names 'hāua', not 'hau' + '-hāua'. The stem changes — the vowel
lengthens, or a reduplication is undone — so the form cannot be composed and
the source writes it out in full. read_whole_forms recovers those runs;
read_tilde_suffixes continues to own the runs that ARE recognised fragments.

See docs/superpowers/specs/2026-09-19-irregular-whole-forms-design.md §3.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import read_whole_forms, strip_suffix_notation


class ReadWholeForms(unittest.TestCase):
    def test_a_lengthened_vowel_is_read_whole(self):
        # 'hāua' is 'hau' with the vowel lengthened; no suffix fragment
        # could produce it from 'hau'.
        self.assertEqual(read_whole_forms("hau ~hāua ~tanga"),
                         [("hāua", "-a", "passive")])

    def test_a_contracted_stem_is_read_whole(self):
        self.assertEqual(read_whole_forms("kukuti ~nga ~kūtia"),
                         [("kūtia", "-tia", "passive")])

    def test_run_order_does_not_matter(self):
        # paekupu prints this entry twice with the runs in either order.
        self.assertEqual(read_whole_forms("kukuti ~kūtia ~nga"),
                         [("kūtia", "-tia", "passive")])

    def test_one_headword_can_name_both_classes(self):
        # The reduplication in 'momotu' is undone in both derivations.
        self.assertEqual(read_whole_forms("momotu ~motukia ~motuhanga"),
                         [("motukia", "-kia", "passive"),
                          ("motuhanga", "-hanga", "nominalisation")])

    def test_a_multi_word_form_keeps_its_particle(self):
        # 'kawea atu' is 'kawe' + '-a' plus the directional particle. The
        # suffix must be read off the FIRST element: the last characters of
        # the run are 'tu', which is not a suffix.
        self.assertEqual(read_whole_forms("kaweatu ~kawea atu"),
                         [("kawea atu", "-a", "passive")])

    def test_a_hyphenated_form_reads_its_first_element(self):
        self.assertEqual(
            read_whole_forms("tāpiri-atu ~tāpiritia-atu ~tāpiritanga-atu"),
            [("tāpiritia-atu", "-tia", "passive"),
             ("tāpiritanga-atu", "-tanga", "nominalisation")])

    def test_the_longest_matching_suffix_wins(self):
        # 'tākina' ends with '-ina' and with '-kina'; the longer is correct,
        # the same longest-match rule the rest of the module applies.
        self.assertEqual(read_whole_forms("taki ~tākina"),
                         [("tākina", "-kina", "passive")])

    def test_a_recognised_fragment_is_not_a_whole_form(self):
        # read_tilde_suffixes owns these. Returning them here would write the
        # fragment '-nga' into the form column as if it were a word.
        self.assertEqual(read_whole_forms("ahu ~nga"), [])

    def test_a_headword_with_no_tilde_yields_nothing(self):
        self.assertEqual(read_whole_forms("ahu"), [])

    def test_empty_input_is_tolerated(self):
        self.assertEqual(read_whole_forms(""), [])
        self.assertEqual(read_whole_forms(None), [])

    def test_a_parenthesised_fragment_is_still_a_fragment(self):
        # 'heke (~nga) atu' — the closing paren rides along on the token and
        # must not turn a known suffix into an unknown whole form.
        self.assertEqual(read_whole_forms("heke (~nga) atu"), [])
        self.assertEqual(read_whole_forms("rārangi (~tanga) kōrero"), [])

    def test_a_comma_separated_run_stops_at_the_comma(self):
        # papakupu separates with commas and semicolons. Nothing in paekupu
        # needs this today, but a run must never swallow the next word.
        self.assertEqual(read_whole_forms("pūrua ~tia, pūtoru ~tia ..."), [])

    def test_an_unclassifiable_run_writes_nothing(self):
        # The vocabulary is the only thing separating a real derivation from
        # a typo. '~xyzzy' ends in no known suffix and is refused.
        self.assertEqual(read_whole_forms("kupu ~xyzzy"), [])

    def test_a_parenthesised_whole_form_does_not_keep_its_paren(self):
        # Paren-stripping guards the vocabulary lookup, so it must also
        # guard the string that becomes the form. paekupu holds no such
        # headword today, and the corpus guard in test_suffix_extraction.py
        # rejects '(' but not ')' — so a refresh introducing this shape
        # would write 'kūtia) atu' into the form column and no test would
        # notice.
        self.assertEqual(read_whole_forms("kupu (~kūtia) atu"),
                         [("kūtia atu", "-tia", "passive")])

    def test_a_run_that_is_only_a_suffix_is_not_a_word(self):
        # A bare '~ia' is a fragment, not a whole form: there is nothing in
        # front of the suffix for it to be a derivation OF.
        self.assertEqual(read_whole_forms("kupu ~ia"), [])


class StripIsUnchanged(unittest.TestCase):
    """The new reader must not disturb how the search key is built."""

    def test_the_base_is_still_truncated_at_an_irregular_tilde(self):
        self.assertEqual(strip_suffix_notation("hau ~hāua ~tanga"), "hau")

    def test_a_multi_word_base_is_still_kept_whole(self):
        self.assertEqual(strip_suffix_notation("tiki atu ~tīkina atu"),
                         "tiki atu")

    def test_a_recognised_suffix_is_still_stripped(self):
        self.assertEqual(strip_suffix_notation("ahu ~nga"), "ahu")


if __name__ == "__main__":
    unittest.main()
