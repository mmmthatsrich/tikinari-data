"""A word tagged several ways makes no exclusive claim — even across rows (D44).

`blocks()` already says so: the part-of-speech block fires only when BOTH sides
are single-valued, because "a source listing several parts of speech is
describing a word that functions several ways; that is not a claim excluding
another source's single tag". `_pos_atoms` splits on `[,/|]`, so one sense
tagged `'Noun, Verb'` is already two atoms and already never blocks.

What it could not see is the same claim spread over sense rows instead of
commas. te_aka:516 files `auahitūroa` as sense 1 `Proper noun (person)` — the
personified being — and sense 2 `Noun`, the comet. That is one word that
functions two ways, stated exactly as clearly as a comma list, and sense 1's
tag was blocking the whole entry out of every concept sense 2 belonged in.

So the fix is scope, not a new rule: when a SEED is weighed against a concept,
the part-of-speech block reads the seed's whole inventory.

The asymmetry is deliberate. A seed is a lexeme — a grouping the source
STATED — so the union of its senses' tags is the source's own claim. A
concept is a grouping this pipeline INFERRED, so its members' tags are not one
word's inventory and get no such treatment.

Measured: 148 attachments over 324 senses were being prevented, and every one
of them was the part-of-speech block. Zero were a macron disagreement and zero
were a source filing two entries apart — so nothing here touches the
anti-chaining rule, whose instrument is the lexeme block.
"""
import importlib
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_evidence import GlossIndex, blocks, seed_blocks


def _sense(**kw):
    base = {
        "member_key": ("x", "1", 1), "source_id": "x", "entry_id": 1,
        "sense_id": 1, "source_entry_id": "1", "sense_number": 1,
        "headword": "auahitūroa", "headword_search": "auahituroa", "pos": None,
        "gloss_en": None, "gloss_mi": None, "lexeme": ("x", "entry", "1"),
        "cognate_sets": frozenset(), "examples": frozenset(),
        "citations": frozenset(), "cites": frozenset(),
    }
    base.update(kw)
    return base


def _te_aka(n, pos, **kw):
    return _sense(member_key=("te_aka", "516", n), source_id="te_aka",
                  source_entry_id="516", sense_number=n, entry_id=516,
                  sense_id=500 + n, pos=pos,
                  lexeme=("te_aka", "entry", "516"), **kw)


def _hpk(pos="Noun", **kw):
    return _sense(member_key=("hepatakakupu", "4287", 1),
                  source_id="hepatakakupu", source_entry_id="4287",
                  entry_id=4287, sense_id=42, pos=pos,
                  lexeme=("hepatakakupu", "word", "342"), **kw)


class SeedScopedPartOfSpeech(unittest.TestCase):
    def test_a_single_sense_seed_still_blocks(self):
        # Nothing about the one-sense case changes: it has one tag, and one
        # tag against an incompatible one is still an exclusive claim.
        seed = [_te_aka(1, "Proper noun (person)")]
        self.assertTrue(seed_blocks(seed, [_hpk("Noun")]))

    def test_a_seed_whose_senses_span_two_tags_does_not_block(self):
        # The auahitūroa case. Sense 1 is a proper noun, sense 2 a noun; the
        # entry is one word that functions both ways.
        seed = [_te_aka(1, "Proper noun (person)"), _te_aka(2, "Noun")]
        self.assertEqual(seed_blocks(seed, [_hpk("Noun")]), [])

    def test_a_multi_sense_seed_agreeing_on_one_tag_still_blocks(self):
        # Three senses all tagged the same way state ONE tag, not an
        # inventory, so the exclusive claim stands.
        seed = [_te_aka(1, "Proper noun (person)"),
                _te_aka(2, "Proper noun (person)"),
                _te_aka(3, "Proper noun (person)")]
        self.assertTrue(seed_blocks(seed, [_hpk("Noun")]))

    def test_a_comma_list_on_one_sense_was_already_exempt(self):
        # Guards the equivalence the fix rests on: rows and commas say the
        # same thing, and _pos_atoms already honoured the comma form.
        self.assertEqual(blocks(_te_aka(1, "Proper noun (person), Noun"),
                                _hpk("Noun")), [])

    def test_the_lexeme_block_is_never_suppressed(self):
        # The anti-chaining rule's own instrument. A source filing two entries
        # apart is a claim about WORDS and outranks any inventory.
        seed = [_hpk("Noun"), _hpk("Verb")]
        for s in seed:
            s["lexeme"] = ("hepatakakupu", "word", "342")
        other = _hpk("Noun")
        other["lexeme"] = ("hepatakakupu", "word", "999")
        other["member_key"] = ("hepatakakupu", "9999", 1)
        reasons = seed_blocks(seed, [other])
        self.assertTrue(any("different words" in r for r in reasons), reasons)

    def test_the_macron_block_is_never_suppressed(self):
        # A macron is a phoneme, not a tag: it is a claim about the spelling
        # and an inventory of parts of speech says nothing about it.
        seed = [_te_aka(1, "Proper noun (person)", headword="auahitūroa"),
                _te_aka(2, "Noun", headword="auahitūroa")]
        other = _hpk("Noun")
        other["headword"] = "auahituroa"
        reasons = seed_blocks(seed, [other])
        self.assertTrue(any("macron" in r for r in reasons), reasons)

    def test_the_concept_side_gets_no_inventory(self):
        # A concept is inferred, not stated. Two members carrying different
        # tags are not one word's inventory, so a single-tag seed still
        # blocks against the member it disagrees with.
        seed = [_hpk("Noun")]
        existing = [_te_aka(1, "Proper noun (person)"), _te_aka(2, "Noun")]
        self.assertTrue(seed_blocks(seed, existing))

    def test_an_empty_seed_or_concept_blocks_nothing(self):
        self.assertEqual(seed_blocks([], [_hpk("Noun")]), [])
        self.assertEqual(seed_blocks([_hpk("Noun")], []), [])

    def test_an_untagged_sense_does_not_create_an_inventory(self):
        # None is an absence, not a second way the word functions.
        seed = [_te_aka(1, "Proper noun (person)"), _te_aka(2, None)]
        self.assertTrue(seed_blocks(seed, [_hpk("Noun")]))


def _db():
    """te_aka's two-sense comet against hepatakakupu's one-sense comet."""
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (id INTEGER PRIMARY KEY, source_id TEXT,
            source_entry_id TEXT, headword TEXT, headword_search TEXT,
            part_of_speech TEXT, part_of_speech_en TEXT, locator TEXT);
        CREATE TABLE sense (id INTEGER PRIMARY KEY, entry_id INTEGER,
            sense_number INTEGER, gloss_en TEXT, gloss_mi TEXT,
            part_of_speech TEXT, part_of_speech_en TEXT);
        CREATE TABLE example (id INTEGER PRIMARY KEY, sense_id INTEGER,
            text_mi TEXT, citation TEXT);
        CREATE TABLE relation (id INTEGER PRIMARY KEY, entry_id INTEGER,
            target_entry_id INTEGER);
        CREATE TABLE ETY_entry_link (id INTEGER PRIMARY KEY, entry_id INTEGER,
            cognateset_id INTEGER, sense_id INTEGER);
    """)
    con.executemany(
        "INSERT INTO entry (id, source_id, source_entry_id, headword, "
        "headword_search, part_of_speech_en, locator) VALUES (?,?,?,?,?,?,?)", [
            (1, "hepatakakupu", "4287", "Auahitūroa", "auahituroa", "Noun",
             "word_id=342"),
            (2, "te_aka", "516", "Auahitūroa", "auahituroa", None, None),
        ])
    con.executemany(
        "INSERT INTO sense (id, entry_id, sense_number, gloss_en, gloss_mi, "
        "part_of_speech_en) VALUES (?,?,?,?,?,?)", [
            (10, 1, 1, None, "He ao tuarangi e huri ana i te rā.", "Noun"),
            (11, 2, 1, "Comet - sometimes personified.", None,
             "Proper noun (person)"),
            (12, 2, 2, "comet.", None, "Noun"),
        ])
    con.executemany(
        "INSERT INTO ETY_entry_link (entry_id, cognateset_id) VALUES (?,?)",
        [(1, 7), (2, 7)])
    con.commit()
    return con


class TheProofCaseCloses(unittest.TestCase):
    """D43's proof case, which D43's own axis named but could not merge."""

    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def test_the_comet_becomes_one_concept(self):
        con = _db()
        views = self.mod.load_senses(con)["auahituroa"]
        index = GlossIndex(g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
        concepts = self.mod.form_concepts(views, index)
        self.assertEqual(len(concepts), 1)
        self.assertEqual(
            {m["view"]["member_key"] for m in concepts[0]["members"]},
            {("hepatakakupu", "4287", 1), ("te_aka", "516", 1),
             ("te_aka", "516", 2)})

    def test_the_seed_is_not_split_across_concepts(self):
        # Both te_aka senses move together. A lexeme is the source's own
        # grouping and this fix must not start dividing one.
        con = _db()
        views = self.mod.load_senses(con)["auahituroa"]
        index = GlossIndex(g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
        for c in self.mod.form_concepts(views, index):
            keys = {m["view"]["member_key"] for m in c["members"]}
            te_aka = {k for k in keys if k[0] == "te_aka"}
            self.assertIn(len(te_aka), (0, 2), keys)


if __name__ == "__main__":
    unittest.main()
