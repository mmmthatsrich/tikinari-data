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

from concept_evidence import EVIDENCE_WEIGHT, SEED_CONFIDENCE, lexeme_key, positive_evidence


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

    def test_a_shared_cognate_set(self):
        a = _sense(source_id="te_aka", cognate_sets=frozenset({7}))
        b = _sense(source_id="williams", cognate_sets=frozenset({7, 9}))
        self.assertIn("shared_cognate_set",
                      [e["kind"] for e in positive_evidence(a, b)])

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
                     "shared_cognate_set", "gloss_overlap"):
            self.assertIn(kind, EVIDENCE_WEIGHT)

    def test_detail_says_what_the_evidence_actually_was(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        detail = positive_evidence(a, b)[0]["detail"]
        self.assertIn("ridge", detail)


if __name__ == "__main__":
    unittest.main()
