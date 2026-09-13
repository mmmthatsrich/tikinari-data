"""Evidence rules for concept membership.

Each source groups its own senses into words differently, and that grouping is
STATED structure rather than inference — which is why seeds are trusted and
cross-source attachment is not.
"""
import importlib
import string
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_evidence import (COVERAGE_FLOOR, DISTINCT_CEILING, EVIDENCE_WEIGHT,
                             SEED_CONFIDENCE, GlossIndex, blocks, confidence_for,
                             gloss_coverage, lexeme_key, positive_evidence)


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
    def setUp(self):
        # Task 3 is a pure refactor: the index is accepted but the grading
        # rule still counts shared words, so its contents cannot yet change
        # any outcome. Task 4 is where it starts to matter.
        self.idx = GlossIndex(["ridge of a hill", "the hill ridge",
                               "ridge of a mountain", "of a the"])

    def test_a_citation_of_the_other_entry_is_the_strongest_evidence(self):
        a = _sense(source_id="te_matatiki", entry_id=10, cites=frozenset({99}))
        b = _sense(source_id="williams", entry_id=99)
        kinds = [e["kind"] for e in positive_evidence(a, b, self.idx)]
        self.assertIn("cites_source", kinds)

    def test_a_shared_example_sentence(self):
        s = "kua pau katoa nga kai"
        a = _sense(source_id="ngata", examples=frozenset({s}))
        b = _sense(source_id="williams", examples=frozenset({s}))
        self.assertIn("shared_example",
                      [e["kind"] for e in positive_evidence(a, b, self.idx)])

    def test_a_shared_citation(self):
        a = _sense(source_id="te_aka", citations=frozenset({"w 1971:54"}))
        b = _sense(source_id="williams", citations=frozenset({"w 1971:54"}))
        self.assertIn("attributed_quote",
                      [e["kind"] for e in positive_evidence(a, b, self.idx)])

    def test_a_shared_cognate_set_is_NOT_evidence(self):
        # Every entry-to-cognate link in this corpus is match_method
        # 'headword_exact' — matched on spelling, never on meaning. So two
        # senses share a set BECAUSE they share a headword, and counting it
        # would launder the one thing that is never evidence.
        a = _sense(source_id="te_aka", cognate_sets=frozenset({7}))
        b = _sense(source_id="williams", cognate_sets=frozenset({7, 9}))
        self.assertEqual([], positive_evidence(a, b, self.idx))

    def test_gloss_overlap_on_content_words(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        self.assertIn("gloss_overlap",
                      [e["kind"] for e in positive_evidence(a, b, self.idx)])

    def test_a_pair_weak_on_both_axes_is_weak_evidence(self):
        # A single shared word is NOT automatically weak any more —
        # 'Spoon'/'spoon.' is exactly that and grades ordinary gloss_overlap
        # because coverage is total (see GlossGrading). What is weak is a
        # shared word that is BOTH a small fraction of each gloss AND common
        # across the corpus. self.idx's small four-gloss corpus is too rare
        # on 'ridge' (df 3) to demonstrate that, so this test builds its own.
        #
        # Task 6 grid-searches COVERAGE_FLOOR over 0.3-0.7 and DISTINCT_CEILING
        # over 5-80, so margins have to clear that WHOLE range, not just
        # today's provisional defaults: 'ridge of a hill'/'ridge of a
        # mountain' alone sits at coverage 1/3 (0.333), which a floor of 0.3
        # would rescue. Extra distinct words on each side push coverage down
        # to 1/12 (0.083), and the filler multiplier (x200) keeps
        # distinctiveness at 202, past the top of the ceiling range too.
        idx = GlossIndex(["ridge of a hill, crest, summit, escarpment, headland",
                          "ridge along a valley, slope, foothill, moraine, plateau"]
                         + ["some ridge nearby"] * 200)
        a = _sense(source_id="te_aka",
                  gloss_en="ridge of a hill, crest, summit, escarpment, headland")
        b = _sense(source_id="papakupu",
                  gloss_en="ridge along a valley, slope, foothill, moraine, plateau")
        kinds = [e["kind"] for e in positive_evidence(a, b, idx)]
        self.assertIn("gloss_overlap_weak", kinds)
        self.assertNotIn("gloss_overlap", kinds)

    def test_stopwords_alone_are_not_overlap(self):
        # 'of a the' must never link two senses.
        a = _sense(source_id="te_aka", gloss_en="of a the")
        b = _sense(source_id="papakupu", gloss_en="of a the")
        self.assertEqual([], positive_evidence(a, b, self.idx))

    def test_the_same_headword_alone_is_never_evidence(self):
        a = _sense(source_id="te_aka")
        b = _sense(source_id="williams")
        self.assertEqual([], positive_evidence(a, b, self.idx))

    def test_evidence_within_one_source_is_not_counted(self):
        # Seeding already handles within-source grouping; counting it again
        # would let one source's internal repetition look like corroboration.
        s = "kua pau katoa nga kai"
        a = _sense(source_id="ngata", examples=frozenset({s}))
        b = _sense(source_id="ngata", examples=frozenset({s}))
        self.assertEqual([], positive_evidence(a, b, self.idx))

    def test_every_kind_has_a_weight(self):
        for kind in ("cites_source", "shared_example", "attributed_quote",
                     "gloss_overlap", "gloss_overlap_weak"):
            self.assertIn(kind, EVIDENCE_WEIGHT)

    def test_shared_cognate_set_is_not_a_kind(self):
        # See the comment above EVIDENCE_WEIGHT in concept_evidence.py: every
        # cognate link in this corpus is match_method 'headword_exact', so
        # this kind would only ever launder same-headword into evidence.
        self.assertNotIn("shared_cognate_set", EVIDENCE_WEIGHT)

    def test_detail_says_what_the_evidence_actually_was(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        detail = positive_evidence(a, b, self.idx)[0]["detail"]
        self.assertIn("ridge", detail)


class GlossGrading(unittest.TestCase):
    """Both sides of the boundary, on both axes.

    Asserting only that a strong pair yields 'gloss_overlap' would pass
    against a build with no weak kind at all, which pins nothing. What has to
    hold is that the two cases DIFFER — in kind, in weight, and in the
    confidence a membership earns.
    """

    def _pair(self, ga, gb, corpus):
        idx = GlossIndex(corpus)
        a = _sense(source_id="te_aka", gloss_en=ga)
        b = _sense(source_id="papakupu", gloss_en=gb)
        return positive_evidence(a, b, idx)

    def test_identical_terse_glosses_are_ordinary_evidence(self):
        # The defect: one shared word, but it is the WHOLE of both glosses.
        # 'spoon' is deliberately common in this corpus (df 21 > ceiling), so
        # only coverage can rescue it.
        corpus = ["Spoon", "spoon."] + ["a spoon of sorts"] * 19
        got = self._pair("Spoon", "spoon.", corpus)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])
        self.assertEqual("probable", confidence_for(got, []))

    def test_a_rare_shared_word_is_ordinary_evidence(self):
        # The other axis: coverage is LOW (one word out of six), but the
        # shared word is decisive. Only distinctiveness can rescue this.
        long_gloss = "narcissism, vanity, pride, conceit, self-regard"
        corpus = [long_gloss, "narcissism", "narcissism of a sort"]
        got = self._pair(long_gloss, "narcissism", corpus)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])
        self.assertLess(got[0]["coverage"], 0.5)      # coverage did not save it
        self.assertLessEqual(got[0]["distinctiveness"], 20)

    def test_one_common_word_in_two_long_glosses_is_weak(self):
        # Weak on BOTH axes: the 'a'/'form' noise case. Coverage is 1/6
        # (0.167), safely below the whole 0.3-0.7 COVERAGE_FLOOR grid. The
        # filler multiplier is x200 (not x40) so distinctiveness clears the
        # whole 5-80 DISTINCT_CEILING grid too — at x40 it lands at df 42,
        # which a ceiling of 80 would rescue.
        corpus = (["used to form the passive of a verb",
                   "particle indicating a plural form"]
                  + ["some other form of thing"] * 200)
        got = self._pair("used to form the passive of a verb",
                         "particle indicating a plural form", corpus)
        self.assertEqual(["gloss_overlap_weak"], [e["kind"] for e in got])
        self.assertEqual("uncertain", confidence_for(got, []))

    def test_the_weak_kind_weighs_less_than_the_ordinary_one(self):
        # x200 filler (not x40): at x40 the corpus IS the fixture (df 40
        # exactly), so a ceiling of 40 rescues it and both weights tie.
        strong = self._pair("Spoon", "spoon.", ["Spoon", "spoon."])
        weak = self._pair("used to form the passive of a verb",
                          "particle indicating a plural form",
                          ["form"] * 200)
        self.assertGreater(strong[0]["weight"], weak[0]["weight"])

    def test_no_shared_words_is_no_evidence_at_all(self):
        self.assertEqual([], self._pair("spoon", "battle", ["spoon", "battle"]))

    def test_both_measurements_are_carried_on_the_evidence(self):
        # Task 5 stores these; a later re-tune reads them back. If they are
        # not carried here, re-fitting thresholds means recomputing the corpus.
        got = self._pair("Spoon", "spoon.", ["Spoon", "spoon."])[0]
        self.assertEqual(1.0, got["coverage"])
        self.assertEqual(2, got["distinctiveness"])

    def test_coverage_at_the_floor_is_rescued_even_when_common(self):
        # The spec's own example (§2, 'Give'/'Give forth.') sits at coverage
        # 0.5 — but a FIXED gloss pair only ever sits at 0.5, so it would
        # pin exactly that one value of COVERAGE_FLOOR rather than testing
        # the boundary as a boundary. Build the fixture from the constant
        # instead: gloss B is the p shared words and gloss A is those same
        # words plus q-p extras, where COVERAGE_FLOOR == p/q, so B ⊆ A and
        # coverage = |B|/|A| = p/q exactly, whatever p/q Task 6 lands on.
        #
        # Filler words must differ by LETTERS, not by a numeric suffix:
        # _content_words tokenises on [a-z]+, so 'word1'/'word2' both
        # collapse to 'word' and would silently yield 0.5 no matter what.
        frac = Fraction(COVERAGE_FLOOR).limit_denominator(20)
        p, q = frac.numerator, frac.denominator
        words = [c * 3 for c in string.ascii_lowercase]
        shared, extra = words[:p], words[p:q]
        a_gloss = " ".join(shared + extra)
        b_gloss = " ".join(shared)
        # Distinctiveness pushed well past the ceiling so only the coverage
        # axis's '>=' can rescue this pair.
        corpus = [a_gloss, b_gloss] + [b_gloss] * (DISTINCT_CEILING + 10)
        got = self._pair(a_gloss, b_gloss, corpus)
        self.assertAlmostEqual(COVERAGE_FLOOR, got[0]["coverage"])
        self.assertGreater(got[0]["distinctiveness"], DISTINCT_CEILING)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])

    def test_the_specs_own_half_coverage_example_is_ordinary_evidence(self):
        """COVERAGE_FLOOR may not rise above 0.5 while the design's §2 stands.

        A commitment, not a measurement — and the one assertion in this file
        that constrains a threshold rather than describing the rule. §2 lists
        hoatu 'Give' / 'Give forth.' at coverage 0.50 with df 270 in the real
        corpus, marked CORRECT and cited as one of the two rows the coverage
        axis exists to rescue ('coverage alone ✅, df alone ❌ demoted');
        huripari sits on the same 0.50 there.

        THIS TEST GOES RED AT A FLOOR OF 0.6, and that is deliberate: it is
        why the commitment lives here rather than in a comment nobody reads.
        The answer to that redness is to revisit §2 and change this test on
        purpose, never to loosen the assertion to let a tuning run through.

        df is pushed far past any plausible ceiling so ONLY the coverage
        axis's inclusive '>=' can rescue the pair — which is the whole point
        of the row: a common word that is nonetheless half of both glosses.
        """
        corpus = ["Give", "Give forth."] + ["give it a go"] * 300
        got = self._pair("Give", "Give forth.", corpus)
        self.assertAlmostEqual(0.5, got[0]["coverage"])
        self.assertGreater(got[0]["distinctiveness"], DISTINCT_CEILING)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])
        self.assertEqual("probable", confidence_for(got, []))

    def test_distinctiveness_at_the_ceiling_is_rescued_even_at_low_coverage(self):
        # The mirror boundary: distinctiveness sits exactly at
        # DISTINCT_CEILING (inclusive '<='). Coverage is pushed well below
        # today's COVERAGE_FLOOR (1/20, not just under 0.5) so sweeping the
        # floor down as well as up can't rescue this fixture by accident.
        extras = [c * 3 for c in string.ascii_lowercase if c != "n"][:19]
        long_gloss = "narcissism " + " ".join(extras)
        short_gloss = "narcissism"
        filler_count = DISTINCT_CEILING - 2   # the pair itself supplies 2
        corpus = ([long_gloss, short_gloss]
                  + ["narcissism"] * filler_count)
        got = self._pair(long_gloss, short_gloss, corpus)
        self.assertEqual(DISTINCT_CEILING, got[0]["distinctiveness"])
        self.assertLess(got[0]["coverage"], COVERAGE_FLOOR)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])

    def test_a_non_gloss_kind_carries_no_measurements(self):
        a = _sense(source_id="te_matatiki", entry_id=10, cites=frozenset({99}))
        b = _sense(source_id="williams", entry_id=99)
        got = positive_evidence(a, b, GlossIndex([]))[0]
        self.assertEqual("cites_source", got["kind"])
        self.assertIsNone(got["coverage"])
        self.assertIsNone(got["distinctiveness"])


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


class GlossIndexDf(unittest.TestCase):
    """Document frequency of a word SET, not of its individual words."""

    CORPUS = [
        "throw away, reject",
        "Throw away.",
        "throw a spear",
        "cast away from shore",
        "narcissism",
    ]

    def setUp(self):
        self.idx = GlossIndex(self.CORPUS)

    def test_it_counts_the_glosses_it_indexed(self):
        self.assertEqual(5, len(self.idx))

    def test_one_word_is_counted_in_every_gloss_holding_it(self):
        self.assertEqual(3, self.idx.df({"throw"}))
        self.assertEqual(3, self.idx.df({"away"}))

    def test_a_set_is_rarer_than_either_of_its_words(self):
        # The whole point: 'throw' is in 3 and 'away' is in 3, but only 2
        # glosses hold BOTH. A per-word measure cannot see this.
        self.assertEqual(2, self.idx.df({"throw", "away"}))

    def test_a_rare_word_is_rare(self):
        self.assertEqual(1, self.idx.df({"narcissism"}))

    def test_a_word_absent_from_the_corpus_is_in_no_gloss(self):
        self.assertEqual(0, self.idx.df({"supersonic"}))

    def test_a_set_with_an_absent_word_is_in_no_gloss(self):
        self.assertEqual(0, self.idx.df({"throw", "supersonic"}))

    def test_the_empty_set_is_not_evidence_of_anything(self):
        self.assertEqual(0, self.idx.df(set()))

    def test_stopwords_are_not_indexed(self):
        # 'a' is a stopword and 'of' is a stopword; neither may be a key.
        self.assertEqual(0, self.idx.df({"a"}))

    def test_a_none_gloss_is_tolerated(self):
        # sense.gloss_en is nullable; the index is built straight off it.
        idx = GlossIndex(["throw away", None, "throw"])
        self.assertEqual(3, len(idx))
        self.assertEqual(2, idx.df({"throw"}))

    def test_building_the_index_is_cheap_enough_to_do_once_per_run(self):
        # The guard against an accidental rebuild inside the pair loop: 54
        # does ~1.15M pair comparisons, so an index built per pair would be
        # catastrophic rather than merely slow. 2,000 glosses stands in for
        # the corpus's 150,037, which measures at 0.6s.
        import time
        corpus = [f"gloss number {i} of the corpus" for i in range(2000)]
        started = time.time()
        GlossIndex(corpus)
        self.assertLess(time.time() - started, 1.0)


class GlossCoverage(unittest.TestCase):
    """How much of what the two sources said is the same thing."""

    def _cov(self, a, b):
        from concept_evidence import _content_words
        return gloss_coverage(_content_words(a), _content_words(b))

    def test_identical_glosses_are_total_coverage(self):
        # The defect this whole change exists for: a one-word gloss can never
        # share more than one word, so a count calls this the weakest signal.
        self.assertEqual(1.0, self._cov("Spoon", "spoon."))

    def test_punctuation_and_case_do_not_matter(self):
        self.assertEqual(1.0, self._cov("Throw away.", "throw away"))

    def test_a_shared_word_in_two_long_glosses_is_low_coverage(self):
        # 'a' glossed two ways, sharing only 'form' — the noise case.
        cov = self._cov("used to form the passive of a verb",
                        "particle indicating a plural form")
        self.assertLess(cov, 0.3)

    def test_partial_agreement_is_partial(self):
        # {give} shared, {give, forth} union.
        self.assertAlmostEqual(0.5, self._cov("Give", "Give forth."))

    def test_no_shared_words_is_zero(self):
        self.assertEqual(0.0, self._cov("spoon", "battle"))

    def test_an_empty_gloss_is_zero_not_an_error(self):
        self.assertEqual(0.0, self._cov("spoon", ""))
        self.assertEqual(0.0, self._cov("", ""))

    def test_a_gloss_of_only_stopwords_is_zero(self):
        # 'of a the' must never link two senses, at any coverage.
        self.assertEqual(0.0, self._cov("of a the", "of a the"))


class ScoreboardConstraints(unittest.TestCase):
    """The hard constraints of the spec, §5, as the tuner evaluates them."""

    def test_a_point_that_merges_hiwi_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        # hiwi is eight words plus two loans; anything under 6 concepts on
        # that key means the thresholds over-merge.
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 3, "hia_joined": False,
             "himoemoe_sources": 6, "hoi_soy_sources": 1}))

    def test_a_point_that_joins_hia_and_hiia_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": True,
             "himoemoe_sources": 6, "hoi_soy_sources": 1}))

    def test_a_point_that_fragments_himoemoe_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": False,
             "himoemoe_sources": 2, "hoi_soy_sources": 1}))

    def test_a_point_that_merges_paekupu_soy_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": False,
             "himoemoe_sources": 6, "hoi_soy_sources": 3}))

    def test_a_point_satisfying_all_four_is_accepted(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertTrue(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": False,
             "himoemoe_sources": 6, "hoi_soy_sources": 1}))


class ScoreboardShipping(unittest.TestCase):
    """The fifth criterion: a recorded-correct grouping must reach users.

    Grouping himoemoe's sources correctly and then tiering the result
    'uncertain' denies the recorded answer in practice — filter_concepts()
    withholds it and nobody ever sees the unification. So the four grouping
    answers of ScoreboardConstraints are necessary but not sufficient, and
    the two checks are kept apart: constraints_hold stays exactly the four
    recorded answers, and point_is_acceptable is what the grid selects on.
    """

    GROUPED_AND_SHIPPED = {"hiwi_concepts": 8, "hia_joined": False,
                           "himoemoe_sources": 6, "hoi_soy_sources": 1,
                           "himoemoe_shipping_sources": 6}
    GROUPED_BUT_WITHHELD = {"hiwi_concepts": 8, "hia_joined": False,
                            "himoemoe_sources": 6, "hoi_soy_sources": 1,
                            "himoemoe_shipping_sources": 0}

    def test_a_point_that_withholds_himoemoe_fails_the_criterion(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.clusters_reach_users(self.GROUPED_BUT_WITHHELD))

    def test_a_point_that_ships_himoemoe_meets_the_criterion(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertTrue(tune.clusters_reach_users(self.GROUPED_AND_SHIPPED))

    def test_shipping_fewer_sources_than_the_recorded_answer_fails(self):
        # The acceptance test records >=4 sources unified. A concept that
        # ships but carries only two of them is not that answer.
        tune = importlib.import_module("tune_gloss_thresholds")
        score = dict(self.GROUPED_AND_SHIPPED, himoemoe_shipping_sources=2)
        self.assertFalse(tune.clusters_reach_users(score))

    def test_grouping_alone_no_longer_accepts_a_point(self):
        # The division of labour, pinned: the four answers still hold on a
        # point that withholds himoemoe, which is exactly why they cannot be
        # the whole rule.
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertTrue(tune.constraints_hold(self.GROUPED_BUT_WITHHELD))
        self.assertFalse(tune.point_is_acceptable(self.GROUPED_BUT_WITHHELD))

    def test_a_point_meeting_every_criterion_is_accepted(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertTrue(tune.point_is_acceptable(self.GROUPED_AND_SHIPPED))

    def test_a_broken_grouping_answer_still_rejects_however_well_it_ships(self):
        # Shipping is an ADDITIONAL criterion, never a substitute: the four
        # recorded answers outrank it and cannot be bought back.
        tune = importlib.import_module("tune_gloss_thresholds")
        score = dict(self.GROUPED_AND_SHIPPED, hia_joined=True)
        self.assertFalse(tune.point_is_acceptable(score))


if __name__ == "__main__":
    unittest.main()
