"""Per-source derived-form counts against the built database.

The floors below come from a full extraction simulated against the live
per-source tables before the rebuild ran, less a margin. They are tripwires,
not targets: a source coming in far under has a reader missing a shape, and a
source coming in far over is matching something that is not a suffix.

Simulated totals on 2026-09-18, after every reader fix:
    ngata 4,645 · te_aka 5,358 · paekupu 1,823 · papakupu 212 ·
    williams 35 · kimikupu_hou 18  =  12,091 rows, zero malformed strings.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

# (source, floor) — ~90% of the simulated count, absorbing the small
# difference between a simulation and the real builder's entry minting.
FLOORS = (("ngata", 4100), ("te_aka", 4800), ("paekupu", 1600),
          ("papakupu", 185), ("williams", 31), ("kimikupu_hou", 15))

DERIVED = ("passive", "nominalisation")


def _open():
    # Read-only: this suite must never be able to alter the 568MB working
    # database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class DerivedForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def test_every_source_contributes(self):
        for source, floor in FLOORS:
            with self.subTest(source=source):
                n = self.con.execute(
                    "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
                    "WHERE e.source_id = ? AND f.form_type IN (?, ?)",
                    (source,) + DERIVED).fetchone()[0]
                self.assertGreaterEqual(n, floor)

    def test_both_classes_are_present(self):
        got = dict(self.con.execute(
            "SELECT form_type, COUNT(*) FROM form WHERE form_type IN (?, ?) "
            "GROUP BY 1", DERIVED).fetchall())
        self.assertGreater(got.get("passive", 0), 0)
        self.assertGreater(got.get("nominalisation", 0), 0)

    def test_no_form_row_is_a_bare_fragment(self):
        # The spec stores the complete word, never '-tia'.
        n = self.con.execute(
            "SELECT COUNT(*) FROM form WHERE form LIKE '-%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_no_derived_form_carries_suffix_notation(self):
        # A tilde or a '(-' surviving into a form means a reader composed
        # onto a headword it should have stripped first. Scoped to the
        # derived rows: paekupu's own variant rows legitimately hold
        # parenthetical qualifiers like '(whaka)'. A literal '.' catches the
        # paekupu counting-word headwords ('pūrua ~tia, pūtoru ~tia ...')
        # whose trailing ellipsis composition_bases must now strip — see
        # scripts/suffix_forms.py's composition_bases.
        bad = self.con.execute(
            "SELECT form FROM form WHERE form_type IN (?, ?) AND "
            "(form LIKE '%~%' OR form LIKE '%(-%' OR form LIKE '%,%' OR "
            "form LIKE '%.%')",
            DERIVED).fetchall()
        self.assertEqual(bad, [], f"malformed derived forms: {bad[:5]}")

    def test_there_are_no_duplicate_rows(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM (SELECT entry_id, form, form_type FROM form "
            "GROUP BY 1,2,3 HAVING COUNT(*) > 1)").fetchone()[0]
        self.assertEqual(n, 0)

    def test_every_derived_form_names_its_suffix_and_source(self):
        # note is what makes the per-suffix count cheap; a NULL there would
        # make the row uncountable by suffix.
        n = self.con.execute(
            "SELECT COUNT(*) FROM form WHERE form_type IN (?, ?) AND "
            "(note IS NULL OR note NOT LIKE '-%(%)%')", DERIVED).fetchone()[0]
        self.assertEqual(n, 0)

    def test_the_existing_variant_and_plural_rows_survived(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM form WHERE form_type IN "
            "('variant','plural')").fetchone()[0]
        self.assertGreater(n, 600)
