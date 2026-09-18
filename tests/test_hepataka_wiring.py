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
