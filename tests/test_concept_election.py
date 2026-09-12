"""Electing a concept's canonical form from its witnesses.

The elected value is always a string some member actually wrote. Never
composed — that is what lets the corpus state a canonical form without
inventing lexicographic content.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_election import (GLOSS_EN_PRECEDENCE, elect_gloss, elect_headword)


def _m(source_id, headword, gloss_en=None, gloss_mi=None, key=None):
    return {"member_key": key or (source_id, "1", 1), "source_id": source_id,
            "headword": headword, "gloss_en": gloss_en, "gloss_mi": gloss_mi}


class ElectHeadword(unittest.TestCase):
    def test_morphology_settles_it(self):
        # hoomai is long because it is hoo + mai. Beats any vote.
        members = [_m("williams", "Homai"), _m("te_aka", "homai"),
                   _m("paekupu", "hōmai")]
        value, key, reason = elect_headword(members, derived_long=True)
        self.assertEqual(value, "hōmai")
        self.assertIn("derivation", reason)

    def test_a_macronised_spelling_is_preferred_over_a_bare_one(self):
        # A source marking length makes a claim; one omitting it may simply
        # not mark length. Williams 1957 is the case in point.
        members = [_m("williams", "Hurori"), _m("ngata", "hūrori")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertEqual(value, "hūrori")

    def test_source_precedence_breaks_a_tie(self):
        members = [_m("ngata", "hīmoemoe"), _m("te_aka", "hīmoemoe")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertEqual(key[0], "te_aka")

    def test_no_macron_anywhere_elects_no_macron(self):
        # A Williams-only concept keeps its unmacronised spelling and the gap
        # stays visible. This is D18's 2,297, reported rather than guessed.
        members = [_m("williams", "Aho")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertEqual(value, "Aho")

    def test_the_elected_value_is_always_a_string_a_member_wrote(self):
        members = [_m("williams", "Hurori"), _m("ngata", "hūrori")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertIn(value, [m["headword"] for m in members])

    def test_no_members_elects_nothing(self):
        self.assertEqual(elect_headword([], derived_long=False),
                         (None, None, None))


class ElectGloss(unittest.TestCase):
    def test_english_follows_source_precedence(self):
        members = [_m("papakupu", "hiwi", gloss_en="ridge of a hill"),
                   _m("te_aka", "hiwi", gloss_en="ridge (of a hill).")]
        value, key = elect_gloss(members, "en")
        self.assertEqual(key[0], "te_aka")

    def test_ngata_never_supplies_the_english_gloss(self):
        # Ngata's gloss is the English LEMMA the word was listed under, not a
        # definition: huripari, a hurricane, is glossed 'Wind'.
        members = [_m("ngata", "huripari", gloss_en="Wind"),
                   _m("papakupu", "huripari", gloss_en="fierce wind, tornado")]
        value, key = elect_gloss(members, "en")
        self.assertEqual(value, "fierce wind, tornado")

    def test_ngata_alone_supplies_no_english_gloss_at_all(self):
        members = [_m("ngata", "huripari", gloss_en="Wind")]
        self.assertEqual(elect_gloss(members, "en"), (None, None))

    def test_maori_comes_from_hepatakakupu(self):
        members = [_m("te_aka", "hiwi"),
                   _m("hepatakakupu", "hiwi", gloss_mi="Te pae o ētahi puke.")]
        value, key = elect_gloss(members, "mi")
        self.assertEqual(key[0], "hepatakakupu")

    def test_ngata_is_last_in_the_precedence_list(self):
        self.assertEqual(GLOSS_EN_PRECEDENCE[-1], "ngata")


if __name__ == "__main__":
    unittest.main()
