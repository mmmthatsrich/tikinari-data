"""Each source's rows reach the form table with the right type and note.

These drive the readers through Builder against an in-memory database, so no
part of the real pipeline runs. The per-source row counts live in
tests/test_suffix_extraction.py, which needs a built database.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

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


class AddSuffixForms(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "te_aka", None, {})
        self.eid = self.b.add_entry("e1", "kake", "kake", "kake")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_a_passive_and_a_nominalisation_are_typed_apart(self):
        build_unified._add_suffix_forms(self.b, self.eid, "kake",
                                        ["-a", "-nga"], "te_aka")
        self.assertEqual(self._rows(),
                         [("kakea", "passive", "-a (te_aka)"),
                          ("kakenga", "nominalisation", "-nga (te_aka)")])

    def test_an_unknown_suffix_writes_nothing(self):
        build_unified._add_suffix_forms(self.b, self.eid, "kake",
                                        ["-bga"], "te_aka")
        self.assertEqual(self._rows(), [])

    def test_the_headword_macrons_survive_composition(self):
        eid = self.b.add_entry("e2", "tūkino", "tukino", "tukino")
        build_unified._add_suffix_forms(self.b, eid, "tūkino",
                                        ["-tia"], "ngata")
        self.assertIn(("tūkinotia", "passive", "-tia (ngata)"), self._rows())
