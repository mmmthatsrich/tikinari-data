"""An inflected English gloss must reach its own base form (D45).

`_content_words` splits on `[a-z]+` and compares surface forms, so taikupu's
`'valued'` and te Aka's `'to prize greatly, value, treasure…'` intersect in
nothing at all and no gloss axis can fire — although one cognate set links
them and williams glosses the same word `'Prize greatly, value.'`

Measured over the corpus, 895 memberships sitting in single-source concepts
would gain gloss evidence. 308 grade ordinary `gloss_overlap`
('Deform'/'Deformed', 'sawyers'/'sawyer', 'Cringe'/'cringing') and 587 grade
`gloss_overlap_weak`, which is where the bad ones land: williams's 'A small
fresh-water fish' reaches te Aka's 'breaking of the waters (childbirth)'
through waters→water and is weak on both axes because `water` is common and
covers almost none of either gloss.

Grading those weak is NOT enough on its own. `form_concepts` attaches a seed
on any evidence at all, so a weak row still merges two concepts and only marks
the result uncertain. Allowed through, stemming merged paekupu's 'a ratio
which connects an angle of a right-angled triangle' with williams's 'Open
space' on the single word `connect`.

Three constraints keep this a reading of the sources rather than an invention:

1. **A stem counts only when the corpus itself attests it.** `valued` reaches
   `value` because the sources use `value` as a gloss word. Nothing is
   derived that the sources do not already say, which is what §2 of the
   rubric requires, and it is the same discipline `resolve_relations_by_gloss`
   applied when it demanded exact string identity (D34).
2. **It is strictly additive.** Stems are tried ONLY where the surface forms
   share nothing. A pair that already overlaps is scored exactly as before, on
   exactly the words it always used, so no existing membership can change
   grade.
3. **A stemmed match must grade ordinary to count at all.** A surface match is
   what the sources wrote; a stemmed one is inferred, and an inference that is
   also weak on both axes is two steps from the evidence. This is the
   difference between +324 cross-source memberships and +907, and between
   `aho` staying at fifteen concepts and collapsing to fourteen.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_evidence import (GlossIndex, _content_words, gloss_coverage,
                              positive_evidence)

# 'water' appears in thirteen glosses, over DISTINCT_CEILING, because that is
# what it is in the corpus: a common word. A toy corpus where it is rare would
# make the weak-grading test below pass for the wrong reason.
CORPUS = [
    "value", "to prize greatly, value, treasure, fond of",
    "kidney", "kidneys", "deform", "deformed", "cringe", "sawyer", "ring",
    "a small fresh-water fish", "breaking of the waters",
] + [f"water {noun}" for noun in (
    "gourd", "carrier", "vessel", "spring", "channel", "weed", "fowl",
    "course", "fall", "hole", "trough", "bucket", "drum")]


def _sense(**kw):
    base = {
        "member_key": ("x", "1", 1), "source_id": "x", "entry_id": 1,
        "sense_id": 1, "source_entry_id": "1", "sense_number": 1,
        "headword": "aho", "headword_search": "aho", "pos": None,
        "gloss_en": None, "gloss_mi": None, "lexeme": ("x", "entry", "1"),
        "cognate_sets": frozenset(), "examples": frozenset(),
        "citations": frozenset(), "cites": frozenset(),
    }
    base.update(kw)
    return base


def _pair(gloss_a, gloss_b, corpus=CORPUS):
    a = _sense(source_id="taikupu", gloss_en=gloss_a)
    b = _sense(source_id="te_aka", gloss_en=gloss_b, member_key=("te_aka", "2", 1))
    return a, b, GlossIndex(corpus)


def _kinds(a, b, idx):
    return [e["kind"] for e in positive_evidence(a, b, idx)]


class AttestedStems(unittest.TestCase):
    def test_an_inflected_gloss_reaches_its_base(self):
        # The D45 case, as taikupu and te Aka actually write it.
        a, b, idx = _pair("valued", "to prize greatly, value, treasure, fond of")
        self.assertTrue(_kinds(a, b, idx))

    def test_a_plural_reaches_its_singular(self):
        a, b, idx = _pair("kidneys.", "kidney.")
        self.assertTrue(_kinds(a, b, idx))

    def test_an_ed_form_reaches_its_verb(self):
        a, b, idx = _pair("Deform", "Deformed. Turi haka, bow-legged.")
        self.assertTrue(_kinds(a, b, idx))

    def test_an_ing_form_reaches_a_verb_ending_in_e(self):
        a, b, idx = _pair("Cringe", "shivering from cold, cringing.")
        self.assertTrue(_kinds(a, b, idx))

    def test_a_stem_the_corpus_never_uses_is_not_invented(self):
        # 'sprocketed' would reduce to 'sprocket', but no gloss in this corpus
        # says 'sprocket', so the sources are not asserting it.
        a, b, idx = _pair("sprocketed", "sprocket")
        self.assertEqual(_kinds(a, b, idx), [])

    def test_a_short_word_is_never_cut_to_a_fragment(self):
        # 'ring' must not reach 'r'. The corpus attests 'ring' itself.
        a, b, idx = _pair("ring", "r")
        self.assertEqual(_kinds(a, b, idx), [])

    def test_a_stemmed_match_that_grades_weak_is_not_evidence_at_all(self):
        # waters -> water joins a fish to childbirth. Grading it weak is not
        # enough: form_concepts attaches a seed on ANY evidence, so a weak
        # row still merges the concepts and only marks them uncertain.
        #
        # A surface match is what the sources wrote. A stemmed match is
        # inferred, and one that is ALSO weak on both coverage and
        # distinctiveness is two steps from the evidence. Measured over the
        # corpus, allowing them merged paekupu's 'a ratio which connects an
        # angle of a right-angled triangle' with williams's 'Open space' on
        # the single word 'connect', and cost 583 further merges of that
        # shape for no case anyone could defend.
        a, b, idx = _pair("A small fresh-water fish, said to be young",
                          "breaking of the waters (childbirth).")
        self.assertEqual(_kinds(a, b, idx), [])

    def test_a_surface_match_that_grades_weak_is_untouched(self):
        # The existing weak kind is not what changed. Two glosses that really
        # do share 'water' still produce it, exactly as before.
        a, b, idx = _pair("A small fresh-water fish, said to be young",
                          "water carrier, one who fetches and is sent")
        self.assertEqual(_kinds(a, b, idx), ["gloss_overlap_weak"])

    def test_a_stemmed_match_that_grades_ordinary_is_kept(self):
        a, b, idx = _pair("kidneys.", "kidney.")
        self.assertEqual(_kinds(a, b, idx), ["gloss_overlap"])


class StrictlyAdditive(unittest.TestCase):
    def test_a_pair_that_already_overlaps_is_scored_on_its_own_words(self):
        # The guarantee that no existing membership can move: where surface
        # forms already share a word, coverage is computed on exactly those
        # sets and stems are never consulted.
        a, b, idx = _pair("value, treasure", "value, prize")
        got = positive_evidence(a, b, idx)[0]
        self.assertEqual(
            got["coverage"],
            gloss_coverage(_content_words(a["gloss_en"]),
                           _content_words(b["gloss_en"])))

    def test_stemming_introduces_no_new_evidence_kind(self):
        a, b, idx = _pair("kidneys.", "kidney.")
        for kind in _kinds(a, b, idx):
            self.assertIn(kind, ("gloss_overlap", "gloss_overlap_weak"))

    def test_an_empty_index_attests_nothing_and_changes_nothing(self):
        # GlossIndex([]) has no vocabulary, so no stem is attested and the
        # tokeniser behaves exactly as it did before this change.
        a, b, idx = _pair("valued", "value", corpus=[])
        self.assertEqual(_kinds(a, b, idx), [])

    def test_a_gloss_with_no_content_words_is_still_silent(self):
        a, b, idx = _pair("of the", "to a")
        self.assertEqual(_kinds(a, b, idx), [])


class TheIndexExposesItsVocabulary(unittest.TestCase):
    def test_it_attests_a_word_it_indexed(self):
        idx = GlossIndex(["kidney", "value"])
        self.assertEqual(idx.expand(frozenset({"kidneys"})),
                         frozenset({"kidneys", "kidney"}))

    def test_it_leaves_a_word_it_cannot_reduce(self):
        idx = GlossIndex(["kidney"])
        self.assertEqual(idx.expand(frozenset({"value"})), frozenset({"value"}))

    def test_expansion_keeps_the_surface_form(self):
        # The surface form must survive, or a pair sharing 'kidneys' outright
        # would stop matching on it.
        idx = GlossIndex(["kidney"])
        self.assertIn("kidneys", idx.expand(frozenset({"kidneys"})))


if __name__ == "__main__":
    unittest.main()
