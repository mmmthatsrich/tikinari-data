"""A suffix joins the word it belongs to, not always the last one.

compose() appends to the end of the base, which is right for a single word
and for a fixed compound whose tail takes the suffix ('tangata whenua' ->
'tangata whenuatia'). Two shapes break it.

The source sometimes marks WHICH element takes the suffix, by putting the
notation after it — paekupu's 'heke (~nga) atu' means 'hekenga atu', and
papakupu's 'tau [-ria] mai' means 'tauria mai'. Composing onto the tail
gave 'heke atunga' and 'tau mairia', neither of which is a word.

And a phrase can end in a directional or manner particle, which cannot
carry a suffix at all. 'mahi anō' glosses as 'redo'; its passive is
'mahia anō', not 'mahi anōtia'.

Measured: 5 source-marked rows and 6 particle-tailed rows. The other 67
multi-word derived forms compose onto the tail correctly and must not move.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import compose, compose_phrase


class SingleWord(unittest.TestCase):
    """99% of the corpus. Nothing here may change."""

    def test_a_plain_word_is_unchanged(self):
        self.assertEqual(compose_phrase("kake", "-a"), "kakea")

    def test_it_matches_compose_for_one_word(self):
        self.assertEqual(compose_phrase("kake", "-a"), compose("kake", "-a"))

    def test_a_macron_survives(self):
        self.assertEqual(compose_phrase("kōrero", "-tia"), "kōrerotia")


class TailIsCorrect(unittest.TestCase):
    """A fixed compound really does take the suffix on its last word."""

    def test_a_compound_noun_composes_on_the_tail(self):
        self.assertEqual(compose_phrase("tangata whenua", "-tia"),
                         "tangata whenuatia")

    def test_a_three_word_compound_composes_on_the_tail(self):
        self.assertEqual(compose_phrase("hanga ngātahi", "-tanga"),
                         "hanga ngātahitanga")

    def test_a_hyphenated_tail_composes_on_the_tail(self):
        self.assertEqual(compose_phrase("kutētē ā-ringa", "-tia"),
                         "kutētē ā-ringatia")


class SourceMarksThePosition(unittest.TestCase):
    """The notation sits after the element that takes the suffix."""

    def test_a_parenthesised_tilde_marks_the_first_word(self):
        self.assertEqual(
            compose_phrase("heke atu", "-nga", "heke (~nga) atu"),
            "hekenga atu")

    def test_the_same_with_a_different_particle(self):
        self.assertEqual(
            compose_phrase("heke mai", "-nga", "heke (~nga) mai"),
            "hekenga mai")

    def test_it_works_for_a_content_word_tail(self):
        # 'kauawhi' is not a particle, so only the source's mark tells us.
        self.assertEqual(
            compose_phrase("hautū kauawhi", "-tanga",
                           "hautū (~tanga) kauawhi"),
            "hautūtanga kauawhi")

    def test_and_for_the_other_content_word_case(self):
        self.assertEqual(
            compose_phrase("rārangi kōrero", "-tanga",
                           "rārangi (~tanga) kōrero"),
            "rārangitanga kōrero")

    def test_a_bracketed_mark_works_the_same_way(self):
        # papakupu writes '[-ria]' where paekupu writes '(~nga)'.
        self.assertEqual(
            compose_phrase("tau mai", "-ria", "tau [-ria] mai"),
            "tauria mai")

    def test_a_mark_at_the_end_still_composes_on_the_tail(self):
        # 'hanga ngātahi ~tia' marks the last word, which is where the
        # suffix already went.
        self.assertEqual(
            compose_phrase("hanga ngātahi", "-tia", "hanga ngātahi ~tia"),
            "hanga ngātahitia")


class ParticleTail(unittest.TestCase):
    """A directional or manner particle cannot carry a suffix."""

    def test_ano_does_not_take_the_suffix(self):
        # The suffix is the one paekupu wrote, '-tia', not the '-a' a
        # reader might expect for 'mahi'. Where the suffix lands is ours
        # to work out; which suffix it is remains the source's to say.
        self.assertEqual(compose_phrase("mahi anō", "-tia"), "mahitia anō")

    def test_ake_does_not_take_the_suffix(self):
        self.assertEqual(compose_phrase("tatau ake", "-ria"), "tatauria ake")

    def test_a_longer_verb_still_works(self):
        self.assertEqual(compose_phrase("whakamahana anō", "-tia"),
                         "whakamahanatia anō")

    def test_a_run_of_two_particles_is_stepped_over(self):
        self.assertEqual(compose_phrase("haere atu anō", "-tia"),
                         "haeretia atu anō")

    def test_kau_is_not_treated_as_a_particle(self):
        # 'hopu kau' glosses as 'dry record (audio)' and 'whana kau' as
        # 'punt kick': here kau modifies the verb rather than following it,
        # so the tail rule must not claim these.
        self.assertEqual(compose_phrase("hopu kau", "-tia"), "hopu kautia")
        self.assertEqual(compose_phrase("whana kau", "-tia"), "whana kautia")

    def test_the_sources_own_suffix_is_never_substituted(self):
        # 'tatau' commonly passivises with '-ngia', but paekupu wrote
        # '~ria'. Moving the attachment point must not become an excuse to
        # correct the source's choice of suffix.
        self.assertEqual(compose_phrase("tatau ake", "-ria"), "tatauria ake")
        self.assertNotIn("ngia", compose_phrase("tatau ake", "-ria"))

    def test_a_base_that_is_only_a_particle_is_left_alone(self):
        # Nothing in front of it to attach to; refusing to compose beats
        # producing a word from a grammatical marker.
        self.assertEqual(compose_phrase("anō", "-tia"), "anōtia")


class MarkLandingOnAParticle(unittest.TestCase):
    """A mark cannot mean 'inflect this particle'."""

    def test_a_trailing_mark_on_a_particle_defers_to_the_verb(self):
        # paekupu writes 'mahi anō ~tia' with the notation at the end of
        # the whole phrase, which points at 'anō'. A particle cannot carry
        # a suffix, so the mark is positional sloppiness, not a claim, and
        # the suffix goes on 'mahi'.
        self.assertEqual(
            compose_phrase("mahi anō", "-tia", "mahi anō ~tia"),
            "mahitia anō")

    def test_a_trailing_mark_on_a_real_word_is_still_obeyed(self):
        # 'ngātahi' is not a particle, so the end mark means what it says.
        self.assertEqual(
            compose_phrase("hanga ngātahi", "-tia", "hanga ngātahi ~tia"),
            "hanga ngātahitia")


class MarkBeatsParticle(unittest.TestCase):
    def test_the_sources_mark_wins_over_the_particle_rule(self):
        # 'heke (~nga) atu' is both: the mark says 'heke' and the particle
        # rule would also say 'heke'. They agree here, but the mark is
        # consulted first and must not be overridden.
        self.assertEqual(
            compose_phrase("heke atu", "-nga", "heke (~nga) atu"),
            "hekenga atu")


if __name__ == "__main__":
    unittest.main()
