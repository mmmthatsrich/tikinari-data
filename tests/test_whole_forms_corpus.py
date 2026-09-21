"""The sixteen whole irregular forms, counted against the built database.

paekupu prints these in full because the stem changes and no suffix
fragment could compose them. Measured on 2026-09-19 after the rebuild:

    paekupu derived forms   1,823 -> 1,839
    corpus derived forms   34,978 -> 34,994
    passive                19,743 -> 19,756
    nominalisation         15,235 -> 15,238

Ten of the thirteen affected entries held no derived form before this.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

# (form, suffix, class) — the complete set, spec §3.
EXPECTED = (
    ("hāua", "-a", "passive"),
    ("kawea atu", "-a", "passive"),
    ("kawea mai", "-a", "passive"),
    ("kūtia", "-tia", "passive"),
    ("motukia", "-kia", "passive"),
    ("motuhanga", "-hanga", "nominalisation"),
    ("tākina", "-kina", "passive"),
    ("tāpiritia-atu", "-tia", "passive"),
    ("tāpiritanga-atu", "-tanga", "nominalisation"),
    ("tīkina atu", "-kina", "passive"),
    ("tīkina ake", "-kina", "passive"),
    ("tukuna atu", "-na", "passive"),
    ("utaina anō", "-ina", "passive"),
    ("wetekina", "-kina", "passive"),
    ("wetekanga", "-kanga", "nominalisation"),
)


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class WholeForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_every_expected_form_is_present_with_its_class(self):
        for form, suffix, form_type in EXPECTED:
            with self.subTest(form=form):
                row = self.con.execute(
                    "SELECT f.form_type, f.note FROM form f "
                    "JOIN entry e ON e.id = f.entry_id "
                    "WHERE e.source_id = 'paekupu' AND f.form = ?",
                    (form,)).fetchone()
                self.assertIsNotNone(row, f"{form!r} was not written")
                self.assertEqual(row[0], form_type)
                self.assertEqual(row[1], f"{suffix} (paekupu, whole)")

    def test_there_are_exactly_sixteen_whole_form_rows(self):
        # Sixteen rows from fifteen distinct spellings: 'kūtia' is written
        # for both of paekupu's two 'kukuti' entries.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form WHERE note LIKE '%, whole)'"), 16)

    def test_the_whole_forms_split_thirteen_passive_three_nominalisation(self):
        got = dict(self.con.execute(
            "SELECT form_type, COUNT(*) FROM form "
            "WHERE note LIKE '%, whole)' GROUP BY 1").fetchall())
        self.assertEqual(got, {"passive": 13, "nominalisation": 3})

    def test_paekupu_gained_exactly_sixteen_derived_forms(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'paekupu' "
            "  AND f.form_type IN ('passive', 'nominalisation')"), 1839)

    def test_no_whole_form_was_composed_onto_its_headword(self):
        # The failure this catches: reusing _add_suffix_forms would store
        # 'hauhāua' and 'kukutikūtia', words no source holds.
        for bad in ("hauhāua", "kukutikūtia", "momotumotuhanga",
                    "wewetewetekina", "takitākina"):
            with self.subTest(form=bad):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM form WHERE form = ?", bad), 0)

    def test_the_affected_entries_still_key_on_their_bare_base(self):
        # A whole form leaking into headword_search would sever the entry
        # from the plain word other sources hold.
        for slug, key in (("hau-3", "hau"), ("tiki-atu", "tiki atu"),
                          ("wewete", "wewete")):
            with self.subTest(slug=slug):
                self.assertEqual(self._one(
                    "SELECT headword_search FROM entry "
                    "WHERE source_id = 'paekupu' AND source_entry_id = ?",
                    slug), key)

    def test_the_corpus_totals_moved_by_sixteen(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form "
            "WHERE form_type IN ('passive', 'nominalisation')"), 34994)

    def test_the_existing_composed_rows_survived(self):
        # Three entries carry a composed form AND a whole one; the new writer
        # must not have displaced the old.
        for form, note in (("hautanga", "-tanga (paekupu)"),
                           ("kukutinga", "-nga (paekupu)")):
            with self.subTest(form=form):
                self.assertGreater(self._one(
                    "SELECT COUNT(*) FROM form WHERE form = ? AND note = ?",
                    form, note), 0)


if __name__ == "__main__":
    unittest.main()
