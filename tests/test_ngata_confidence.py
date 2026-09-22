"""ngata's confidence says which rows an outside source backs.

ngata prints every Māori equivalent of an English lemma in one run —
'Assault' gives 'patu, patua, pātuki, pātukia'. It never says patua is the
passive of patu; we infer that from the spellings, which is why these rows
carry derived = 1. The inference can go wrong: in that same run 'patu' plus
'-kia' also fits 'pātukia', a word that is really 'pātuki' plus '-a'.

A blanket 'probable' over all 4,646 said nothing about WHICH rows to
distrust. Measured, 3,797 of them name a derived form that a different
dictionary independently records as a passive or nominalisation — outside
support for our pairing. The remaining 849 rest on ngata's run alone, and
those are the ones worth a look.

Williams and papakupu are untouched: they STATE their pairings, so they
stay derived = 0 and certain whatever any other source says.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "word_origin",
    Path(__file__).parent.parent / "scripts" / "53_build_word_origin.py")
word_origin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(word_origin)


def _db(corroborating_source=None):
    """ngata pairs ahu/ahutia; optionally another source records ahutia."""
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, headword TEXT,
            loan_marker TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            gloss_en TEXT);
        CREATE TABLE form (
            id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT,
            form_type TEXT, note TEXT);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER, note TEXT);
        INSERT INTO entry VALUES (1, 'ngata', 'ahutia', NULL),
                                 (2, 'ngata', 'ahu',    NULL),
                                 (3, 'williams', 'hopukia', NULL),
                                 (4, 'williams', 'hopu',    NULL),
                                 (5, 'te_aka', 'ahu', NULL);
        INSERT INTO sense VALUES (10,1,1,NULL),(11,2,1,NULL),
                                 (12,3,1,NULL),(13,4,1,NULL),(14,5,1,NULL);
        INSERT INTO relation VALUES
            (100, 1, 'derived_from', 'ahu',  2, NULL),
            (101, 3, 'derived_from', 'hopu', 4, NULL);
    """)
    if corroborating_source:
        con.execute("INSERT INTO entry VALUES (6, ?, 'kake', NULL)",
                    (corroborating_source,))
        con.execute("INSERT INTO form VALUES (1, 6, 'ahutia', 'passive', NULL)")
    return con


class Corroborated(unittest.TestCase):
    def _row(self, con, base):
        return {r["base_form"]: r
                for r in word_origin.collect_derivations(con)}[base]

    def test_an_outside_source_makes_it_certain(self):
        row = self._row(_db("te_aka"), "ahu")
        self.assertEqual(row["confidence"], "certain")

    def test_without_one_it_stays_probable(self):
        row = self._row(_db(), "ahu")
        self.assertEqual(row["confidence"], "probable")

    def test_ngata_corroborating_itself_does_not_count(self):
        # The point is INDEPENDENT support. A second ngata row recording
        # the same form is the same inference twice.
        row = self._row(_db("ngata"), "ahu")
        self.assertEqual(row["confidence"], "probable")

    def test_the_pairing_is_still_ours_either_way(self):
        # Corroboration raises confidence, never attestation: ngata still
        # did not state the relation.
        for src in ("te_aka", None):
            with self.subTest(corroborator=src):
                self.assertEqual(self._row(_db(src), "ahu")["derived"], 1)

    def test_a_stated_pairing_is_unaffected(self):
        # Williams prints its derivative under the base. It is attested and
        # certain whether or not anyone else records the form.
        row = self._row(_db("te_aka"), "hopu")
        self.assertEqual((row["derived"], row["confidence"]), (0, "certain"))


if __name__ == "__main__":
    unittest.main()
