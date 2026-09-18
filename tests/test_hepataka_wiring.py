"""hepatakakupu's suffixes reach the form table, one entry per sense.

These drive the shipped helper against an in-memory database, so no part of
the real pipeline runs. Per-source counts live in test_suffix_extraction.py,
which needs a built database.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "build_unified",
    Path(__file__).parent.parent / "scripts" / "50_build_unified.py")
build_unified = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_unified)


def _memory_db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
            headword TEXT, headword_sort TEXT, headword_search TEXT,
            homonym_no INTEGER, headword_en TEXT, part_of_speech TEXT,
            loan_marker TEXT, dialect TEXT, audio_url TEXT, locator TEXT,
            content_hash TEXT, first_seen TEXT, created_at TEXT,
            last_updated TEXT);
        CREATE TABLE form (
            id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT,
            form_search TEXT, form_type TEXT, note TEXT);
    """)
    return con


class HepatakakupuSuffixes(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "hepatakakupu", None, {})

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_a_passive_and_a_nominalisation_are_typed_apart(self):
        eid = self.b.add_entry("1", "kake", "kake", "kake")
        build_unified._add_suffix_forms(self.b, eid, "kake", ["-a", "-nga"],
                                        "hepatakakupu")
        self.assertEqual(self._rows(),
                         [("kakea", "passive", "-a (hepatakakupu)"),
                          ("kakenga", "nominalisation", "-nga (hepatakakupu)")])

    def test_each_sense_is_its_own_entry_and_carries_its_own_forms(self):
        # build_hepatakakupu keys entries on the sense row id, so kake's
        # senses do NOT share an entry and their forms do not collapse.
        first = self.b.add_entry("10281", "kake", "kake", "kake")
        second = self.b.add_entry("25391", "kake", "kake", "kake")
        for eid in (first, second):
            build_unified._add_suffix_forms(self.b, eid, "kake", ["-a"],
                                            "hepatakakupu")
        self.assertEqual(len(self._rows()), 2)

    def test_a_malformed_suffix_writes_nothing_but_is_counted(self):
        # Only build_hepatakakupu's own call site threads b.suffix_tally
        # through in production, but exercising that here is how this test
        # observes the tally at all: without passing it, nothing accumulates
        # (tally defaults to None precisely so the other six sources, which
        # already tally inside their readers, are not double-counted).
        eid = self.b.add_entry("1", "kake", "kake", "kake")
        build_unified._add_suffix_forms(self.b, eid, "kake", ["-bga"],
                                        "hepatakakupu", self.b.suffix_tally)
        self.assertEqual(self._rows(), [])
        self.assertEqual(self.b.suffix_tally.refused, ["-bga"])

    def test_macrons_survive_composition(self):
        eid = self.b.add_entry("1", "tūkino", "tukino", "tukino")
        build_unified._add_suffix_forms(self.b, eid, "tūkino", ["-tia"],
                                        "hepatakakupu")
        self.assertIn(("tūkinotia", "passive", "-tia (hepatakakupu)"),
                      self._rows())


class HepatakaBases(unittest.TestCase):
    """_hepataka_bases: split a multi-spelling headword, refuse a phrase.

    A comma joins alternative spellings ('tīkona, tīkoina'), both real
    bases. A parenthesis is different: composition_bases (paekupu's reader)
    would drop it as a droppable qualifier, but 'hohou (i te) rongo' is the
    phrase "to make peace" — dropping '(i te)' silently ships a different,
    wrong word. So a base still carrying a parenthesis after the comma split
    is refused outright rather than repaired.
    """
    def setUp(self):
        self.tally = build_unified.suffix_forms.Tally()

    def test_a_single_word_is_one_base(self):
        self.assertEqual(build_unified._hepataka_bases("kake", self.tally),
                         ["kake"])
        self.assertEqual(self.tally.refused, [])

    def test_two_comma_joined_spellings_are_two_bases(self):
        self.assertEqual(
            build_unified._hepataka_bases("tīkona, tīkoina", self.tally),
            ["tīkona", "tīkoina"])
        self.assertEqual(self.tally.refused, [])

    def test_a_parenthesised_sibling_is_refused_but_the_clean_one_survives(self):
        self.assertEqual(
            build_unified._hepataka_bases("tautō, tauto(ria)", self.tally),
            ["tautō"])
        self.assertEqual(self.tally.refused, ["tauto(ria)"])

    def test_a_phrase_with_a_parenthetical_is_refused_entirely(self):
        self.assertEqual(
            build_unified._hepataka_bases("hohou (i te) rongo", self.tally), [])
        self.assertEqual(self.tally.refused, ["hohou (i te) rongo"])

    def test_a_short_parenthetical_qualifier_is_also_refused(self):
        self.assertEqual(
            build_unified._hepataka_bases("mataono (rite)", self.tally), [])
        self.assertEqual(self.tally.refused, ["mataono (rite)"])


def _hepataka_entries_db():
    """A minimal hepatakakupu_entries table plus the unified-core tables
    build_hepatakakupu writes through, so build_hepatakakupu itself can be
    driven end to end — not just _add_suffix_forms in isolation.
    """
    con = _memory_db()
    con.executescript("""
        CREATE TABLE hepatakakupu_entries (
            id INTEGER PRIMARY KEY, word_id INTEGER, headword TEXT,
            headword_sort TEXT, headword_search TEXT, part_of_speech TEXT,
            definition TEXT, usage_examples TEXT, sense_number INTEGER,
            synonyms TEXT, synonym_senses TEXT, master_word_id INTEGER,
            master_sense INTEGER, semantic_domain TEXT, suffixes TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            parent_sense_id INTEGER, gloss_en TEXT, gloss_mi TEXT,
            definition_raw TEXT, register TEXT, part_of_speech TEXT,
            note TEXT);
        CREATE TABLE example (
            id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
            text_mi TEXT, text_en TEXT, source_abbrev TEXT, citation TEXT,
            sort_no INTEGER);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER, note TEXT,
            target_sense_id INTEGER);
        CREATE TABLE entry_domain (
            id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
            domain TEXT, domain_lang TEXT);
    """)
    return con


class BuildHepatakakupuEndToEnd(unittest.TestCase):
    """Drives build_hepatakakupu itself, end to end, against an in-memory
    hepatakakupu_entries table — not just _add_suffix_forms in isolation.

    Every other test in this file calls _add_suffix_forms directly, so none
    of them would notice a reordered SELECT, a suffixes column landing in
    the wrong tuple position, a dropped b.suffix_tally at the call site, or
    hw accidentally routed through strip_suffix_notation. This is the one
    test where build_hepatakakupu's own code runs.
    """
    def setUp(self):
        self.con = _hepataka_entries_db()
        self.con.executemany(
            "INSERT INTO hepatakakupu_entries "
            "(id, word_id, headword, headword_sort, headword_search, "
            "part_of_speech, definition, usage_examples, sense_number, "
            "synonyms, synonym_senses, master_word_id, master_sense, "
            "semantic_domain, suffixes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(10281, 500, "kake", "kake", "kake", None, "to climb", "[]",
              1, "[]", "[]", None, None, None, '["-a", "-nga"]'),
             (25391, 500, "kake", "kake", "kake", None, "to ascend by", "[]",
              2, "[]", "[]", None, None, None, "[]")])
        self.b = build_unified.Builder(self.con, "hepatakakupu", None, {})

    def test_suffixes_reach_the_form_table_through_the_real_builder(self):
        build_unified.build_hepatakakupu(self.con, self.b)
        rows = self.con.execute(
            "SELECT e.source_entry_id, f.form, f.form_type, f.note "
            "FROM form f JOIN entry e ON e.id = f.entry_id ORDER BY 1, 2"
        ).fetchall()
        self.assertEqual(rows, [
            ("10281", "kakea", "passive", "-a (hepatakakupu)"),
            ("10281", "kakenga", "nominalisation", "-nga (hepatakakupu)"),
        ])

    def test_the_second_sense_carries_no_forms_of_its_own(self):
        build_unified.build_hepatakakupu(self.con, self.b)
        n = self.con.execute(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_entry_id = ?", ("25391",)).fetchone()[0]
        self.assertEqual(n, 0)

    def test_the_tally_is_threaded_through_not_dropped(self):
        # This is the assertion the brief's own broken test could not make:
        # it is the one thing a missing b.suffix_tally at the call site
        # would break while every other assertion in this file stayed green.
        build_unified.build_hepatakakupu(self.con, self.b)
        self.assertEqual(self.b.suffix_tally.seen, 2)
        self.assertEqual(self.b.suffix_tally.refused, [])


class BuildHepatakakupuMultiBaseHeadwords(unittest.TestCase):
    """Regression coverage for the malformed rows a multi-base or
    parenthetical headword used to ship before _hepataka_bases: a comma or
    a phrase's parenthesis composing straight into the stored form
    ('tīkona, tīkoinanga', 'hohou (i te) rongohia').
    """
    def setUp(self):
        self.con = _hepataka_entries_db()
        self.con.executemany(
            "INSERT INTO hepatakakupu_entries "
            "(id, word_id, headword, headword_sort, headword_search, "
            "part_of_speech, definition, usage_examples, sense_number, "
            "synonyms, synonym_senses, master_word_id, master_sense, "
            "semantic_domain, suffixes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(99001, 600, "tīkona, tīkoina", "tikona, tikoina",
              "tikona, tikoina", None, "to totter", "[]", 1, "[]", "[]",
              None, None, None, '["-nga"]'),
             (99002, 601, "hohou (i te) rongo", "hohou (i te) rongo",
              "hohou i te rongo", None, "to make peace", "[]", 1, "[]", "[]",
              None, None, None, '["-hia"]')])
        self.b = build_unified.Builder(self.con, "hepatakakupu", None, {})
        build_unified.build_hepatakakupu(self.con, self.b)

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_the_comma_joined_headword_composes_onto_each_spelling_cleanly(self):
        self.assertEqual(self._rows(), [
            ("tīkoinanga", "nominalisation", "-nga (hepatakakupu)"),
            ("tīkonanga", "nominalisation", "-nga (hepatakakupu)"),
        ])

    def test_no_stored_form_carries_a_comma_or_a_parenthesis(self):
        bad = [r for r in self._rows() if "," in r[0] or "(" in r[0]]
        self.assertEqual(bad, [])

    def test_the_phrase_headword_writes_nothing_and_is_refused(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_entry_id = ?", ("99002",)).fetchone()[0]
        self.assertEqual(n, 0)
        self.assertIn("hohou (i te) rongo", self.b.suffix_tally.refused)

    def test_the_multi_base_entry_tallies_its_suffix_tokens_once(self):
        # build_hepatakakupu passes b.suffix_tally only on the first base
        # (`b.suffix_tally if i == 0 else None`) so a multi-base entry does
        # not double-count: 'tīkona, tīkoina' contributes exactly one kept
        # token for its single '-nga' suffix, and 'hohou (i te) rongo'
        # contributes one refused base (its '-hia' token never reaches the
        # tally at all, since the phrase headword leaves zero bases). A
        # bare `b.suffix_tally` on every base would tally '-nga' twice and
        # push this to 3.
        self.assertEqual(self.b.suffix_tally.seen, 2)
