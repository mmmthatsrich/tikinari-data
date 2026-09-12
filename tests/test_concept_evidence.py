"""Evidence rules for concept membership.

Each source groups its own senses into words differently, and that grouping is
STATED structure rather than inference — which is why seeds are trusted and
cross-source attachment is not.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_evidence import (EVIDENCE_WEIGHT, SEED_CONFIDENCE, blocks, confidence_for,
                             lexeme_key, positive_evidence)


class LexemeKey(unittest.TestCase):
    def test_williams_groups_by_entry(self):
        # Williams files Hiwi as 1250, 1251, 1252 — three words, three lexemes.
        a = lexeme_key("williams", "1251", "hiwi", None)
        b = lexeme_key("williams", "1250", "hiwi", None)
        self.assertNotEqual(a, b)

    def test_te_aka_groups_by_entry(self):
        self.assertNotEqual(lexeme_key("te_aka", "1331", "hoi", None),
                            lexeme_key("te_aka", "1332", "hoi", None))

    def test_hepatakakupu_groups_by_word_id_in_the_locator(self):
        # Five entries, one lemma: the source says so via word_id.
        a = lexeme_key("hepatakakupu", "19969", "hiwi", "word_id=930")
        b = lexeme_key("hepatakakupu", "20526", "hiwi", "word_id=930")
        self.assertEqual(a, b)

    def test_hepatakakupu_separates_different_word_ids(self):
        self.assertNotEqual(
            lexeme_key("hepatakakupu", "300", "hurori", "word_id=1226"),
            lexeme_key("hepatakakupu", "303", "turori", "word_id=9889"))

    def test_ngata_groups_by_headword_within_the_source(self):
        # 14 'hoatu' rows are one word seen from 13 English lemmas.
        self.assertEqual(lexeme_key("ngata", "WR-HMN.5013#32977~1", "hoatu", None),
                         lexeme_key("ngata", "WR-HMN.3136#30213~1", "hoatu", None))

    def test_papakupu_groups_by_headword(self):
        self.assertEqual(lexeme_key("papakupu", "2", "a", None),
                         lexeme_key("papakupu", "3", "a", None))

    def test_a_missing_locator_falls_back_to_the_entry(self):
        self.assertNotEqual(lexeme_key("hepatakakupu", "1", "x", None),
                            lexeme_key("hepatakakupu", "2", "x", None))

    def test_ngata_seeds_are_probable_not_certain(self):
        # Grouping by headword would merge two genuine Ngata homographs and
        # nothing in Ngata's structure would say otherwise.
        self.assertEqual(SEED_CONFIDENCE["ngata"], "probable")
        self.assertEqual(SEED_CONFIDENCE.get("williams", "certain"), "certain")


def _sense(**kw):
    """A sense-view with empty defaults, so each test states only what matters."""
    base = {
        "member_key": ("x", "1", 1), "source_id": "x", "entry_id": 1,
        "sense_id": 1, "source_entry_id": "1", "sense_number": 1,
        "headword": "hiwi", "headword_search": "hiwi", "pos": None,
        "gloss_en": None, "gloss_mi": None, "lexeme": ("x", "entry", "1"),
        "cognate_sets": frozenset(), "examples": frozenset(),
        "citations": frozenset(), "cites": frozenset(),
    }
    base.update(kw)
    return base


class PositiveEvidence(unittest.TestCase):
    def test_a_citation_of_the_other_entry_is_the_strongest_evidence(self):
        a = _sense(source_id="te_matatiki", entry_id=10, cites=frozenset({99}))
        b = _sense(source_id="williams", entry_id=99)
        kinds = [e["kind"] for e in positive_evidence(a, b)]
        self.assertIn("cites_source", kinds)

    def test_a_shared_example_sentence(self):
        s = "kua pau katoa nga kai"
        a = _sense(source_id="ngata", examples=frozenset({s}))
        b = _sense(source_id="williams", examples=frozenset({s}))
        self.assertIn("shared_example",
                      [e["kind"] for e in positive_evidence(a, b)])

    def test_a_shared_citation(self):
        a = _sense(source_id="te_aka", citations=frozenset({"w 1971:54"}))
        b = _sense(source_id="williams", citations=frozenset({"w 1971:54"}))
        self.assertIn("attributed_quote",
                      [e["kind"] for e in positive_evidence(a, b)])

    def test_a_shared_cognate_set_is_NOT_evidence(self):
        # Every entry-to-cognate link in this corpus is match_method
        # 'headword_exact' — matched on spelling, never on meaning. So two
        # senses share a set BECAUSE they share a headword, and counting it
        # would launder the one thing that is never evidence.
        a = _sense(source_id="te_aka", cognate_sets=frozenset({7}))
        b = _sense(source_id="williams", cognate_sets=frozenset({7, 9}))
        self.assertEqual([], positive_evidence(a, b))

    def test_gloss_overlap_on_content_words(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        self.assertIn("gloss_overlap",
                      [e["kind"] for e in positive_evidence(a, b)])

    def test_stopwords_alone_are_not_overlap(self):
        # 'of a the' must never link two senses.
        a = _sense(source_id="te_aka", gloss_en="of a the")
        b = _sense(source_id="papakupu", gloss_en="of a the")
        self.assertEqual([], positive_evidence(a, b))

    def test_the_same_headword_alone_is_never_evidence(self):
        a = _sense(source_id="te_aka")
        b = _sense(source_id="williams")
        self.assertEqual([], positive_evidence(a, b))

    def test_evidence_within_one_source_is_not_counted(self):
        # Seeding already handles within-source grouping; counting it again
        # would let one source's internal repetition look like corroboration.
        s = "kua pau katoa nga kai"
        a = _sense(source_id="ngata", examples=frozenset({s}))
        b = _sense(source_id="ngata", examples=frozenset({s}))
        self.assertEqual([], positive_evidence(a, b))

    def test_every_kind_has_a_weight(self):
        for kind in ("cites_source", "shared_example", "attributed_quote",
                     "gloss_overlap"):
            self.assertIn(kind, EVIDENCE_WEIGHT)

    def test_shared_cognate_set_is_not_a_kind(self):
        # See the comment above EVIDENCE_WEIGHT in concept_evidence.py: every
        # cognate link in this corpus is match_method 'headword_exact', so
        # this kind would only ever launder same-headword into evidence.
        self.assertNotIn("shared_cognate_set", EVIDENCE_WEIGHT)

    def test_detail_says_what_the_evidence_actually_was(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        detail = positive_evidence(a, b)[0]["detail"]
        self.assertIn("ridge", detail)


class Blocks(unittest.TestCase):
    def test_a_sources_own_homograph_numbering_blocks(self):
        # Williams files Hiwi as 1250 and 1251: that IS Williams saying these
        # are different words.
        a = _sense(source_id="williams", lexeme=("williams", "entry", "1250"))
        b = _sense(source_id="williams", lexeme=("williams", "entry", "1251"))
        self.assertTrue(blocks(a, b))

    def test_the_same_lexeme_in_one_source_does_not_block(self):
        a = _sense(source_id="williams", lexeme=("williams", "entry", "1251"))
        b = _sense(source_id="williams", lexeme=("williams", "entry", "1251"))
        self.assertEqual([], blocks(a, b))

    def test_macron_disagreement_blocks(self):
        # hia and hiia share a key only because headword_search strips macrons.
        a = _sense(source_id="te_aka", headword="hia")
        b = _sense(source_id="ngata", headword="hīa")
        self.assertTrue(blocks(a, b))

    def test_identical_spelling_does_not_block(self):
        a = _sense(source_id="te_aka", headword="hīmoemoe")
        b = _sense(source_id="ngata", headword="hīmoemoe")
        self.assertEqual([], blocks(a, b))

    def test_capitalisation_alone_does_not_block(self):
        # Williams capitalises its main headwords.
        a = _sense(source_id="williams", headword="Hīmoemoe")
        b = _sense(source_id="paekupu", headword="hīmoemoe")
        self.assertEqual([], blocks(a, b))

    def test_incompatible_part_of_speech_blocks(self):
        a = _sense(source_id="te_aka", pos="Noun")
        b = _sense(source_id="williams", pos="Verb (transitive)")
        self.assertTrue(blocks(a, b))

    def test_a_missing_part_of_speech_never_blocks(self):
        a = _sense(source_id="te_aka", pos=None)
        b = _sense(source_id="williams", pos="Noun")
        self.assertEqual([], blocks(a, b))

    def test_a_shared_pos_atom_does_not_block(self):
        a = _sense(source_id="te_aka", pos="Noun, Modifier")
        b = _sense(source_id="williams", pos="Modifier")
        self.assertEqual([], blocks(a, b))

    def test_a_block_says_why(self):
        a = _sense(source_id="te_aka", headword="hia")
        b = _sense(source_id="ngata", headword="hīa")
        self.assertIn("macron", blocks(a, b)[0].lower())

    def test_a_multi_valued_pos_never_blocks(self):
        # hepatakakupu tags himoemoe 'Stative, Noun, Verb (intransitive)' and
        # paekupu tags it 'Modifier'. Both are right: a word that functions
        # several ways is not a claim excluding another source's single tag.
        a = _sense(source_id="hepatakakupu", pos="Stative, Noun, Verb (intransitive)")
        b = _sense(source_id="paekupu", pos="Modifier")
        self.assertEqual([], blocks(a, b))

    def test_transitivity_alone_does_not_block(self):
        # One source calls a verb transitive, another intransitive. Same verb.
        a = _sense(source_id="te_aka", pos="Verb (transitive)")
        b = _sense(source_id="williams", pos="Verb (intransitive)")
        self.assertEqual([], blocks(a, b))


class Confidence(unittest.TestCase):
    def test_the_strongest_kind_wins(self):
        ev = [{"kind": "gloss_overlap"}, {"kind": "shared_example"}]
        self.assertEqual(confidence_for(ev, []), "certain")

    def test_a_block_downgrades_to_uncertain(self):
        ev = [{"kind": "shared_example"}]
        self.assertEqual(confidence_for(ev, ["macron disagreement"]), "uncertain")

    def test_no_evidence_is_uncertain(self):
        self.assertEqual(confidence_for([], []), "uncertain")


if __name__ == "__main__":
    unittest.main()
