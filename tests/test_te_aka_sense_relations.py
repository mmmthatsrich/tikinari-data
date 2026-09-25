"""Te Aka states which sense a synonym belongs to; record it (D46).

`04_te_aka_parse.py` reads the dictionary-link anchors **inside each sense's
div** and stores them on that sense. It then also accumulates an entry-level
`all_synonyms`, commented "legacy / FTS / synonym resolution", and
`build_te_aka` iterated that aggregate — so 87,569 relations were asserted of
the WORD when the source had said which SENSE.

`aho` is the case. te_aka:79 has five senses, and the source puts
`{io, kapa, papanga, raina, ripa, rārangi, tawhā}` on sense 1 'fishing line,
cord, string' and `{hikahika, kaha, kāwai, kāwei, takiaho}` on sense 3 'line
of descent, genealogy'. Flattened, twelve relations hang off the entry and the
cord sense and the genealogy sense become mutual synonyms. `aho` is the
rubric's own `spurious_etymology` worked example.

A second, smaller loss: the aggregate dedups (`if syn not in all_synonyms`),
so a synonym serving two senses collapsed to one link — 2,388 attributions.

**Scope.** This records which sense asserted the relation and changes no
consumer. `resolve_within_source_relations`, `resolve_relations_by_domain`,
`resolve_relations_by_gloss`, `53_build_word_origin` and the concept layer's
`cites` index all read `entry_id` and the target columns, and all keep reading
them. Narrowing them to the sense is likely right and is certainly not free —
49,755 relations currently assert more than the source does and those are the
rows those consumers have been reading — so it is a separate change with its
own measurement, not a rider on this one.
"""
import importlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

bu = importlib.import_module("50_build_unified")
init_db = importlib.import_module("00_init_db")

# te_aka:79 'aho', trimmed to the three senses that matter.
AHO_SENSES = [
    {"sense_number": 1, "part_of_speech": "noun",
     "gloss_en": "fishing line, cord, string, line.",
     "definition_raw": "fishing line, cord, string, line.",
     "examples": [],
     "synonyms": [{"text": "io", "word_id": 11},
                  {"text": "kapa", "word_id": 12},
                  {"text": "rārangi", "word_id": 13}]},
    {"sense_number": 2, "part_of_speech": "noun",
     "gloss_en": "weft, woof - cross-threads of weaving.",
     "definition_raw": "weft, woof - cross-threads of weaving.",
     "examples": [], "synonyms": []},
    {"sense_number": 3, "part_of_speech": "noun",
     "gloss_en": "line of descent, genealogy.",
     "definition_raw": "line of descent, genealogy.",
     "examples": [],
     "synonyms": [{"text": "kāwai", "word_id": 21},
                  {"text": "takiaho", "word_id": 22},
                  # also on sense 1 in the real entry; the aggregate deduped
                  # it away and the fact that it serves both was lost.
                  {"text": "io", "word_id": 11}]},
]


def _db(senses=AHO_SENSES):
    """The real schema, not a hand-copied subset.

    An earlier draft wrote its own CREATE TABLEs and drifted from the real
    ones within minutes; a second called part of the init sequence and
    silently lacked `sense.note`. `initialise` is the whole thing, and is what
    the pipeline runs — see tests/test_schema_single_source.py.
    """
    con = sqlite3.connect(":memory:")
    init_db.initialise(con)
    # The entry-level aggregate, exactly as the parser builds it: deduped.
    agg = []
    for s in senses:
        for syn in s.get("synonyms") or []:
            if syn not in agg:
                agg.append(syn)
    con.execute(
        "INSERT INTO te_aka_entries (word_id, headword, headword_sort, "
        " headword_search, part_of_speech, definition, senses, usage_examples,"
        " audio_url, synonyms, filters) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (79, "aho", "aho", "aho", "noun", "fishing line",
         json.dumps(senses), "[]", None, json.dumps(agg), "[]"))
    con.commit()
    return con


def _build(con):
    b = bu.Builder(con, "te_aka", "standard", {})
    bu.build_te_aka(con, b)
    con.commit()
    return b


def _relations(con):
    return con.execute(
        "SELECT r.target_headword, s.sense_number FROM relation r "
        "  LEFT JOIN sense s ON s.id = r.sense_id ORDER BY 1, 2").fetchall()


class TheSenseThatAssertedIt(unittest.TestCase):
    def test_each_synonym_lands_on_the_sense_that_carries_it(self):
        con = _db()
        _build(con)
        got = {(hw, sn) for hw, sn in _relations(con)}
        self.assertIn(("kapa", 1), got)
        self.assertIn(("kāwai", 3), got)
        self.assertNotIn(("kāwai", 1), got)
        self.assertNotIn(("kapa", 3), got)

    def test_a_synonym_serving_two_senses_is_recorded_twice(self):
        # The aggregate deduped 'io' to a single entry-level row and the fact
        # that it serves both senses was discarded — 2,388 attributions.
        con = _db()
        _build(con)
        io = sorted(sn for hw, sn in _relations(con) if hw == "io")
        self.assertEqual(io, [1, 3])

    def test_the_cord_sense_and_the_genealogy_sense_share_no_synonym_row(self):
        con = _db()
        _build(con)
        by_sense = {}
        for hw, sn in _relations(con):
            by_sense.setdefault(sn, set()).add(hw)
        self.assertEqual(by_sense[1], {"io", "kapa", "rārangi"})
        self.assertEqual(by_sense[3], {"io", "kāwai", "takiaho"})

    def test_a_sense_with_no_synonyms_gets_none(self):
        con = _db()
        _build(con)
        self.assertNotIn(2, {sn for _hw, sn in _relations(con)})

    def test_the_word_id_note_still_rides_along(self):
        # It is what resolve_te_aka_synonyms uses to fill target_entry_id.
        con = _db()
        _build(con)
        notes = dict(con.execute(
            "SELECT target_headword, note FROM relation"))
        self.assertEqual(notes["kapa"], "te_aka_word_id=12")

    def test_every_relation_names_a_sense(self):
        con = _db()
        _build(con)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM relation WHERE sense_id IS NULL")
               .fetchone()[0], 0)

    def test_an_entry_parsed_before_senses_existed_still_builds(self):
        # The fallback branch synthesises one sense from the packed
        # definition; its synonyms come from the entry-level aggregate and
        # belong to that synthesised sense.
        con = _db(senses=[])
        con.execute("UPDATE te_aka_entries SET senses='[]', "
                    " synonyms=? WHERE word_id=79",
                    (json.dumps([{"text": "io", "word_id": 11}]),))
        con.commit()
        _build(con)
        self.assertEqual(_relations(con), [("io", 1)])


class TheColumnMigration(unittest.TestCase):
    def test_it_is_idempotent(self):
        con = _db()
        init_db._add_column(con, "relation", "sense_id",
                            "INTEGER REFERENCES sense(id)")
        init_db._add_column(con, "relation", "sense_id",
                            "INTEGER REFERENCES sense(id)")
        cols = {r[1] for r in con.execute("PRAGMA table_info(relation)")}
        self.assertIn("sense_id", cols)

    def test_add_relation_defaults_to_no_sense(self):
        # Every other source's relations are entry-level and stay that way;
        # only te Aka states a sense today.
        con = _db()
        b = bu.Builder(con, "williams", "standard", {})
        con.execute("INSERT INTO entry (id, source_id, headword, headword_sort, "
                    " headword_search) VALUES (900, 'williams', 'apa', 'apa', 'apa')")
        b.add_relation(900, "see_also", "apa")
        con.commit()
        self.assertIsNone(con.execute(
            "SELECT sense_id FROM relation WHERE entry_id=900").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
