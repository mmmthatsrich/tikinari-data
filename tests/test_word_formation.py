"""Describing how a derived form relates to its base (D38).

WORD_FORMATION_DESIGN proposes `derivation.process` and `derivation.affix`.
Both are descriptions of the two spellings, not new lexicographic claims: that
`whakaae` is `whaka-` + `ae` is visible in the strings, and Williams's own
layout is what says the pair is a derivation at all.

So the rule is narrow. It reports only what the spellings show, and returns
nothing rather than guessing when they show nothing — an infixed or irregular
form gets a derivation row with a base and no process, which is honest.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from word_formation import (dedupe_components, describe_derivation,
                            parse_component_note)


class DescribeDerivation(unittest.TestCase):
    def test_a_prefix(self):
        self.assertEqual(describe_derivation("whakaae", "ae"),
                         ("prefix", "whaka-"))

    def test_the_causative_is_named_for_what_it_is(self):
        self.assertEqual(describe_derivation("whakapae", "pae"),
                         ("prefix", "whaka-"))

    def test_a_suffix(self):
        self.assertEqual(describe_derivation("itinga", "iti"),
                         ("suffix", "-nga"))

    def test_a_nominaliser(self):
        self.assertEqual(describe_derivation("muanga", "mua"),
                         ("suffix", "-nga"))

    def test_full_reduplication(self):
        self.assertEqual(describe_derivation("kamikami", "kami"),
                         ("reduplication", None))

    def test_partial_reduplication_reads_as_a_suffix_not_a_guess(self):
        # 'korehurehu' from 'korehu' repeats the last two syllables. The string
        # shows a suffix and nothing more, so that is what is reported.
        self.assertEqual(describe_derivation("korehurehu", "korehu"),
                         ("suffix", "-rehu"))

    def test_a_base_that_is_neither_at_the_front_nor_the_back(self):
        # 'tauawhiawhi' contains 'tauawhi' at the front, so that is a suffix;
        # but a base sitting in the middle yields no describable process.
        self.assertEqual(describe_derivation("kaiwhakaako", "whaka"),
                         (None, None))

    def test_identical_strings_are_not_a_derivation(self):
        self.assertEqual(describe_derivation("ae", "ae"), (None, None))

    def test_a_base_absent_from_the_child(self):
        self.assertEqual(describe_derivation("hoatu", "mai"), (None, None))

    def test_empty_input(self):
        self.assertEqual(describe_derivation("", "ae"), (None, None))
        self.assertEqual(describe_derivation("whakaae", ""), (None, None))


class ParseComponentNote(unittest.TestCase):
    """Paekupu writes a component and its meaning into the relation note.

    'wete - to release, set free' is the richest shape in the corpus for this
    purpose: Maori form and English gloss together, per component.
    """

    def test_form_and_gloss(self):
        self.assertEqual(parse_component_note("wete - to release, set free"),
                         ("wete", "to release, set free"))

    def test_a_parenthesised_variant_stays_with_the_form(self):
        self.assertEqual(
            parse_component_note("hāpara (hāparapara) - surgery, operation"),
            ("hāpara (hāparapara)", "surgery, operation"))

    def test_a_hyphenated_headword_is_not_a_separator(self):
        # 'ia-tuku - artery' — the first hyphen is inside the term.
        self.assertEqual(parse_component_note("ia-tuku - artery"),
                         ("ia-tuku", "artery"))

    def test_a_note_with_no_separator_is_a_form_alone(self):
        self.assertEqual(parse_component_note("taukaea"), ("taukaea", None))

    def test_a_loan_marker_note_is_not_a_component(self):
        self.assertIsNone(parse_component_note("He kupu mino."))

    def test_empty(self):
        self.assertIsNone(parse_component_note(""))
        self.assertIsNone(parse_component_note(None))


class DedupeComponents(unittest.TestCase):
    """A component named twice is still one component.

    Paekupu resolves a cross-reference per SENSE, so a term built on a word
    with two senses yields that word twice — 'aeharua' came out as aeha, aeha,
    rua. Position is meaning in a compound ('aho pae' is latitude, 'pae aho' is
    nothing), so a spurious repeat does not merely add a row, it renumbers the
    ones after it.
    """

    def test_a_repeated_base_collapses_and_positions_renumber(self):
        parts = [(11, "aeha", "annoyance"), (11, "aeha", "bogey (golf)"),
                 (22, "rua", "two")]
        self.assertEqual(dedupe_components(parts),
                         [(11, "aeha", "annoyance"), (22, "rua", "two")])

    def test_the_first_gloss_is_kept(self):
        parts = [(11, "aeha", None), (11, "aeha", "bogey (golf)")]
        self.assertEqual(dedupe_components(parts), [(11, "aeha", None)])

    def test_a_genuine_repetition_of_different_bases_is_untouched(self):
        parts = [(11, "aho", "line"), (22, "pae", "ridge")]
        self.assertEqual(dedupe_components(parts), parts)

    def test_order_is_preserved(self):
        parts = [(33, "c", None), (11, "a", None), (33, "c", None), (22, "b", None)]
        self.assertEqual([p[1] for p in dedupe_components(parts)], ["c", "a", "b"])

    def test_empty(self):
        self.assertEqual(dedupe_components([]), [])


if __name__ == "__main__":
    unittest.main()
