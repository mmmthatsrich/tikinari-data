"""One row per (entry_id, form, form_type), with provenance accumulating.

A derived form is often recorded by several sources, and by several senses
within one source. Without this, 'kakea' would be written once per sense and
the user's per-suffix counts would report sense frequency dressed up as
vocabulary size.
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


class FormDedupe(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "test", None, {})
        self.eid = self.b.add_entry("e1", "kake", "kake", "kake")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_the_same_form_twice_writes_one_row(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.assertEqual(len(self._rows()), 1)

    def test_a_second_source_accumulates_in_the_note(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (ngata)")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "-a (te_aka, ngata)")

    def test_the_same_source_twice_does_not_repeat_itself_in_the_note(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.assertEqual(self._rows()[0][2], "-a (te_aka)")

    def test_a_different_form_type_is_a_different_row(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakenga", "nominalisation", "-nga (te_aka)")
        self.assertEqual(len(self._rows()), 2)

    def test_the_count_matches_the_rows_written(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (ngata)")
        self.assertEqual(self.b.counts["form"], 1)

    def test_a_form_restating_the_headword_is_still_refused(self):
        # Pre-existing behaviour that must survive this change.
        self.b.add_form(self.eid, "kake", "variant")
        self.assertEqual(self._rows(), [])
