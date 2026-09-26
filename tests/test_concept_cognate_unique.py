"""A shared cognate set as evidence, but only where it names one word (D43).

He Pātaka Kupu is monolingual Māori. `concept_evidence`'s gloss axes compare
`gloss_en`, which it has for none of its 24,941 senses, so it joins a
cross-source concept in 5% of its memberships against williams's 70%. The
etymology it does carry — 46,159 links, the second-best coverage in the
corpus — is not an evidence axis.

It cannot simply become one. A cognate set links HEADWORDS and carries no
sense discrimination: measured over the corpus, a stranded hepatakakupu sense
reaches 5.3 distinct words on average through its cognate sets, and 2,391 of
them reach ten or more. That is the shape that once merged ten distinct words
under `hoi`, and it is why `shared_cognate_set` was removed.

What survives is the discipline D32 and D34 already use: act only where
exactly one candidate is left. A cognate set that names ONE word from each
side is a mutual, unambiguous claim, and it is 4,680 pairs corpus-wide.

Measured over the corpus it moves hepatakakupu from 5.4% of memberships
joining a cross-source concept to 8.7% (+832), and leaves `hoi` at seven.

It does NOT settle the case D43 was filed on. That one is blocked by a
second, independent cause, pinned in TheProofCaseIsBlockedElsewhere below.
"""
import importlib
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_evidence import (EVIDENCE_CONFIDENCE, EVIDENCE_WEIGHT, GlossIndex,
                              cognate_unique_pairs, positive_evidence)
from core_schema import core_db


def _sense(**kw):
    """A sense-view with empty defaults, so each test states only what matters."""
    base = {
        "member_key": ("x", "1", 1), "source_id": "x", "entry_id": 1,
        "sense_id": 1, "source_entry_id": "1", "sense_number": 1,
        "headword": "auahituroa", "headword_search": "auahituroa", "pos": None,
        "gloss_en": None, "gloss_mi": None, "lexeme": ("x", "entry", "1"),
        "cognate_sets": frozenset(), "examples": frozenset(),
        "citations": frozenset(), "cites": frozenset(),
    }
    base.update(kw)
    return base


def _hpk(n=1, sets=(7,), **kw):
    return _sense(member_key=("hepatakakupu", str(n), 1), source_id="hepatakakupu",
                  source_entry_id=str(n), entry_id=n, sense_id=n,
                  lexeme=("hepatakakupu", "word", "342"),
                  cognate_sets=frozenset(sets), **kw)


def _other(src, n, sets=(7,), lexeme=None, **kw):
    return _sense(member_key=(src, str(n), 1), source_id=src,
                  source_entry_id=str(n), entry_id=n, sense_id=n,
                  lexeme=lexeme or (src, "entry", str(n)),
                  cognate_sets=frozenset(sets), **kw)


def _pair(a, b):
    return frozenset({a["member_key"], b["member_key"]})


class CognateUniquePairs(unittest.TestCase):
    def test_one_word_on_each_side_qualifies(self):
        # The D43 proof case: hepatakakupu's comet and te Aka's 'Comet',
        # joined by the single cognate set AUAHI-TUROA.
        a = _hpk(4287)
        b = _other("te_aka", 516)
        self.assertEqual(cognate_unique_pairs([a, b]), {_pair(a, b)})

    def test_a_cognate_set_reaching_two_words_qualifies_neither(self):
        # The hoi shape. williams files these as two words, so the set names
        # no one word and the axis must stay silent.
        a = _hpk(4287)
        b = _other("williams", 2671)
        c = _other("williams", 2672)
        self.assertEqual(cognate_unique_pairs([a, b, c]), set())

    def test_two_senses_of_one_word_are_one_word(self):
        # te_aka:41978 glosses kīwei 'loop, handle' and 'shoot, runner'. Two
        # senses of ONE word is not ambiguity about which word is meant.
        a = _hpk(4310)
        b = _other("te_aka", 41978)
        c = _other("te_aka", 41978)
        c["member_key"], c["sense_number"], c["sense_id"] = ("te_aka", "41978", 2), 2, 99
        self.assertEqual(cognate_unique_pairs([a, b, c]),
                         {_pair(a, b), _pair(a, c)})

    def test_uniqueness_must_hold_from_both_sides(self):
        # a sees only b. But b also reaches c, a second word in a third
        # source, so b's own claim is ambiguous and the pair does not qualify.
        a = _hpk(4287)
        b = _other("te_aka", 516)
        c = _other("ngata", 900)
        a["cognate_sets"] = frozenset({7})
        b["cognate_sets"] = frozenset({7, 8})
        c["cognate_sets"] = frozenset({8})
        self.assertEqual(cognate_unique_pairs([a, b, c]), set())

    def test_no_shared_cognate_set_qualifies_nothing(self):
        a = _hpk(4287, sets=(7,))
        b = _other("te_aka", 516, sets=(8,))
        self.assertEqual(cognate_unique_pairs([a, b]), set())

    def test_a_source_is_never_paired_with_itself(self):
        # Seeding already groups a source's own senses; this axis is for
        # cross-source attachment only.
        a = _hpk(4287)
        b = _hpk(9999)
        b["lexeme"] = ("hepatakakupu", "word", "999")
        self.assertEqual(cognate_unique_pairs([a, b]), set())

    def test_a_blocked_candidate_is_not_a_candidate(self):
        # b and c share the set, but c disagrees about vowel length, so it is
        # blocked and cannot make the claim ambiguous. Without this, one
        # misspelling would veto every merge in the bucket.
        a = _hpk(4287, headword="auahitūroa")
        b = _other("te_aka", 516, headword="auahitūroa")
        c = _other("ngata", 900, headword="auahituroa")
        self.assertEqual(cognate_unique_pairs([a, b, c]), {_pair(a, b)})

    def test_a_pair_blocked_against_each_other_never_qualifies(self):
        a = _hpk(4287, pos="Noun")
        b = _other("te_aka", 516, pos="Proper noun")
        self.assertEqual(cognate_unique_pairs([a, b]), set())

    def test_an_empty_bucket_is_handled(self):
        self.assertEqual(cognate_unique_pairs([]), set())


class TheAxisInPositiveEvidence(unittest.TestCase):
    def setUp(self):
        self.idx = GlossIndex([])

    def test_it_is_absent_unless_the_pair_was_supplied(self):
        # Every existing caller passes nothing, and must see no change.
        a = _hpk(4287)
        b = _other("te_aka", 516)
        kinds = [e["kind"] for e in positive_evidence(a, b, self.idx)]
        self.assertNotIn("shared_cognate_set_unique", kinds)

    def test_a_supplied_pair_yields_the_evidence(self):
        a = _hpk(4287)
        b = _other("te_aka", 516)
        found = positive_evidence(a, b, self.idx, cognate_unique_pairs([a, b]))
        self.assertIn("shared_cognate_set_unique", [e["kind"] for e in found])

    def test_a_pair_that_is_not_unique_yields_nothing(self):
        a = _hpk(4287)
        b = _other("williams", 2671)
        c = _other("williams", 2672)
        unique = cognate_unique_pairs([a, b, c])
        found = positive_evidence(a, b, self.idx, unique)
        self.assertEqual([e["kind"] for e in found], [])

    def test_it_is_probable_never_certain(self):
        # A stated etymological link plus a uniqueness proof is strong, but it
        # is still inference: no source says these two entries are one word.
        self.assertEqual(EVIDENCE_CONFIDENCE["shared_cognate_set_unique"], "probable")

    def test_it_outranks_a_gloss_overlap_and_yields_to_a_citation(self):
        self.assertGreater(EVIDENCE_WEIGHT["shared_cognate_set_unique"],
                           EVIDENCE_WEIGHT["gloss_overlap"])
        self.assertLess(EVIDENCE_WEIGHT["shared_cognate_set_unique"],
                        EVIDENCE_WEIGHT["attributed_quote"])

    def test_the_detail_names_the_set_that_did_it(self):
        a = _hpk(4287, sets=(7,))
        b = _other("te_aka", 516, sets=(7,))
        found = positive_evidence(a, b, self.idx, cognate_unique_pairs([a, b]))
        detail = next(e["detail"] for e in found
                      if e["kind"] == "shared_cognate_set_unique")
        self.assertIn("7", detail)


def _bucket_db(extra_entries=(), extra_senses=(), extra_links=()):
    """One headword bucket: the comet, in Māori and in English.

    hepatakakupu carries gloss_mi and no gloss_en, which is the whole of D43 —
    every gloss axis is blind to it — so the only thing that can join these
    two is the cognate set they share.
    """
    con = core_db()
    con.executemany(
        "INSERT INTO entry (id, source_id, source_entry_id, headword, "
        "headword_sort, headword_search, part_of_speech_en, locator) "
        "VALUES (?,?,?,?,?,?,?,?)", [
            (1, "hepatakakupu", "4287", "Auahitūroa", "auahituroa",
             "auahituroa", "Noun", "word_id=342"),
            (2, "te_aka", "516", "Auahitūroa", "auahituroa",
             "auahituroa", "Noun", None),
            *extra_entries,
        ])
    con.executemany(
        "INSERT INTO sense (id, entry_id, sense_number, gloss_en, gloss_mi) "
        "VALUES (?,?,?,?,?)", [
            (10, 1, 1, None, "He ao tuarangi e huri ana i te rā."),
            (11, 2, 1, "Comet.", None),
            *extra_senses,
        ])
    con.executemany(
        "INSERT INTO ETY_entry_link (entry_id, cognateset_id, source) "
        "VALUES (?,?,'tregear')",
        [(1, 7), (2, 7), *extra_links])
    con.commit()
    return con


class FormConceptsUsesTheAxis(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _concepts(self, con):
        views = self.mod.load_senses(con)["auahituroa"]
        index = GlossIndex(g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
        return self.mod.form_concepts(views, index)

    def test_the_comet_becomes_one_concept(self):
        concepts = self._concepts(_bucket_db())
        self.assertEqual(len(concepts), 1)
        self.assertEqual({m["view"]["source_id"] for m in concepts[0]["members"]},
                         {"hepatakakupu", "te_aka"})

    def test_the_membership_records_the_axis_that_earned_it(self):
        concepts = self._concepts(_bucket_db())
        kinds = {e["kind"] for m in concepts[0]["members"] for e in m["evidence"]}
        self.assertIn("shared_cognate_set_unique", kinds)

    def test_the_member_that_attached_on_it_is_probable_not_certain(self):
        # te_aka joins on this axis alone, and inference is never certain.
        # hepatakakupu founds the concept — seeds are processed in sorted
        # order — so it keeps its own seed confidence, having attached to
        # nothing; re-scoring may only raise a membership, never lower it.
        concepts = self._concepts(_bucket_db())
        by_source = {m["view"]["source_id"]: m for m in concepts[0]["members"]}
        self.assertEqual(by_source["te_aka"]["confidence"], "probable")

    def test_a_third_word_on_the_same_set_stops_the_merge(self):
        # The hoi shape, end to end: williams files 2671 and 2672 as two
        # words and both carry the set, so it names no one word and nothing
        # may join on it. Every sense here is its own concept.
        con = _bucket_db(
            extra_entries=[
                (3, "williams", "2671", "Auahitūroa", "auahituroa",
                 "auahituroa", "Noun", None),
                (4, "williams", "2672", "Auahitūroa", "auahituroa",
                 "auahituroa", "Noun", None)],
            extra_senses=[(12, 3, 1, None, None), (13, 4, 1, None, None)],
            extra_links=[(3, 7), (4, 7)])
        concepts = self._concepts(con)
        for c in concepts:
            self.assertEqual(len({m["view"]["source_id"] for m in c["members"]}), 1,
                             [m["view"]["member_key"] for m in c["members"]])


class TheProofCaseNeededBothFixes(unittest.TestCase):
    """The real auahitūroa data, which this axis alone could not settle.

    D43 recorded that 'both are canonically Noun, so no part-of-speech block
    applies'. That is true entry-to-entry and false sense-to-sense. te_aka:516
    has TWO senses: #1 'Proper noun (person)' — Auahitūroa the personage — and
    #2 'Noun', the comet. `proper noun` is deliberately outside OPEN_POS (the
    'Hene' rule), so #1 blocks against hepatakakupu's Noun.

    The axis does its part: it names (hepatakakupu:4287#1, te_aka:516#2) as a
    mutually unique pair. But a seed is a whole lexeme, and form_concepts
    rules a concept out if a block holds against ANY member — so sense 1
    vetoes attachment to sense 2. That is the anti-chaining rule working as
    designed, and it is a separate finding from D43, not something this axis
    may quietly override.

    That second cause was filed as D44, measured at 148 attachments — every
    one of them the part-of-speech block — and fixed by `seed_blocks`, which
    weighs that block against the seed's whole inventory. The pair this axis
    names is therefore now merged, and it took both fixes: without the axis
    there is no evidence, and without D44 the evidence is vetoed.

    This class kept a characterisation test while the second cause was open.
    It went red the moment `seed_blocks` landed, which is exactly what it was
    written to do; it now asserts the merge instead.
    """

    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _real_shape(self):
        return _bucket_db(
            extra_senses=[(12, 2, 2, "Comet.", None)],
            extra_entries=(), extra_links=())

    def test_the_axis_still_names_the_pair(self):
        con = self._real_shape()
        con.execute("UPDATE sense SET part_of_speech_en='Proper noun (person)' "
                    " WHERE id=11")
        con.execute("UPDATE sense SET part_of_speech_en='Noun' WHERE id=12")
        con.commit()
        views = self.mod.load_senses(con)["auahituroa"]
        pairs = cognate_unique_pairs(views)
        self.assertIn(frozenset({("hepatakakupu", "4287", 1), ("te_aka", "516", 2)}),
                      pairs)

    def test_and_with_D44_fixed_the_entry_now_merges(self):
        con = self._real_shape()
        con.execute("UPDATE sense SET part_of_speech_en='Proper noun (person)' "
                    " WHERE id=11")
        con.execute("UPDATE sense SET part_of_speech_en='Noun' WHERE id=12")
        con.commit()
        views = self.mod.load_senses(con)["auahituroa"]
        index = GlossIndex(g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
        concepts = self.mod.form_concepts(views, index)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(
            {m["view"]["member_key"] for m in concepts[0]["members"]},
            {("hepatakakupu", "4287", 1), ("te_aka", "516", 1),
             ("te_aka", "516", 2)})


if __name__ == "__main__":
    unittest.main()
