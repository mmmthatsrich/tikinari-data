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
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "build_unified",
    Path(__file__).parent.parent / "scripts" / "50_build_unified.py")
build_unified = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_unified)


def _memory_db():
    con = core_db()
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


class AddDerivedForms(unittest.TestCase):
    """_add_derived_forms has a different contract from _add_suffix_forms:
    it stores the (base, derived, suffix) triple's DERIVED spelling whole,
    rather than composing headword + suffix — williams's irregular
    reduplicated passives ('amuamu' -> 'amuamutia') are not headword+suffix
    concatenations, so composing here would silently corrupt them."""

    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "williams", None, {})
        self.eid = self.b.add_entry("e1", "Amu", "amu", "amu")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_the_derived_spelling_is_stored_whole_not_composed(self):
        # compose("Amu", "-tia") would be 'Amutia'; the real passive is the
        # reduplicated 'amuamutia', which only survives if it is stored as
        # given rather than rebuilt from the headword.
        build_unified._add_derived_forms(
            self.b, self.eid, [("amu", "amuamutia", "-tia")], "williams")
        self.assertEqual(self._rows(),
                         [("amuamutia", "passive", "-tia (williams)")])

    def test_an_unknown_suffix_writes_nothing(self):
        build_unified._add_derived_forms(
            self.b, self.eid, [("amu", "amubga", "-bga")], "williams")
        self.assertEqual(self._rows(), [])
