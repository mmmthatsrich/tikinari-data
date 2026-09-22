"""No sense defines a word as itself and its synonyms.

Wakareo's English->Māori components print the equivalents in the body, and
_body_text refuses a body that only restates them. It compared the whole
body against each lemma individually, so a comma-joined run slipped past:
183 source rows kept one, and they reached the unified senses as prose.

    Ngahuru mātahi   gloss_en 'April'
                     definition_raw 'Ēperira, Ngahuru mātahi, Paenga whāwhā'

Measured on 2026-09-22 after the re-parse and rebuild:

    ngata_entries.body_text        21,337 -> 21,162   (-175)
    kimikupu_hou_entries.body_text      8 ->      0
    te_matatiki 5,097 and tregear 321   unchanged — real definitions

Affected senses keep gloss_en; only the false definition_raw became NULL.
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class BodyText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _filled(self, table):
        return self.con.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE body_text IS NOT NULL AND TRIM(body_text) <> ''"
        ).fetchone()[0]

    def test_kimikupu_hou_keeps_no_body_text_at_all(self):
        # Every one of its bodies is the equivalents restated; it is an
        # English->Māori word list with no definitions to extract.
        self.assertEqual(self._filled("kimikupu_hou_entries"), 0)

    def test_ngata_kept_the_rest_of_its_bodies(self):
        # A floor, not a target: only the 175 restatements should have gone.
        self.assertEqual(self._filled("ngata_entries"), 21162)

    def test_the_definitional_sources_are_untouched(self):
        # The guard that matters most: _body_text is shared, and these two
        # carry real prose. Either losing rows means the rule over-reached.
        self.assertEqual(self._filled("te_matatiki_entries"), 5097)
        self.assertEqual(self._filled("tregear_exceptions_entries"), 321)

    def test_no_surviving_body_text_is_only_its_own_equivalents(self):
        # The defect itself, asserted over every wakareo row that still has
        # a body, not just the ones that were fixed.
        offenders = []
        for table in ("ngata_entries", "kimikupu_hou_entries"):
            for hw, bt, qual, eq in self.con.execute(
                    f"SELECT headword, body_text, qualifier, equivalents "
                    f"FROM {table} WHERE body_text IS NOT NULL "
                    f"AND TRIM(body_text) <> ''"):
                stem = bt.strip()
                if qual and stem.casefold().startswith(qual.casefold()):
                    stem = stem[len(qual):].strip()
                lemmas = {(hw or "").casefold()}
                lemmas.update(e.casefold() for e in json.loads(eq or "[]"))
                parts = [p.strip().casefold()
                         for p in stem.split(",") if p.strip()]
                if parts and all(p in lemmas for p in parts):
                    offenders.append((table, hw, bt))
        self.assertEqual(offenders, [], f"restatements left: {offenders[:5]}")

    def test_the_named_senses_lost_their_false_definition(self):
        for mi, bad in (("Ngahuru mātahi",
                         "Ēperira, Ngahuru mātahi, Paenga whāwhā"),
                        ("hauata", "hauata, ohorere"),
                        ("aramona", "aramona, amana")):
            with self.subTest(form=mi):
                self.assertEqual(self.con.execute(
                    "SELECT COUNT(*) FROM sense WHERE definition_raw = ?",
                    (bad,)).fetchone()[0], 0)

    def test_those_senses_kept_their_english_gloss(self):
        # Removing a false definition must not cost a true gloss.
        for mi, gloss in (("Ngahuru mātahi", "April"), ("hauata",
                          "Accident and emergency"), ("aramona", "Almond")):
            with self.subTest(form=mi):
                self.assertGreater(self.con.execute(
                    "SELECT COUNT(*) FROM sense s JOIN entry e "
                    "ON e.id = s.entry_id WHERE e.headword = ? "
                    "AND s.gloss_en = ?", (mi, gloss)).fetchone()[0], 0)

    def test_no_entry_or_sense_was_lost(self):
        # body_text feeds definition_raw only; the rows themselves stay.
        for source, want in (("ngata", 33775), ("kimikupu_hou", 2839)):
            with self.subTest(source=source):
                self.assertEqual(self.con.execute(
                    "SELECT COUNT(*) FROM entry WHERE source_id = ?",
                    (source,)).fetchone()[0], want)


if __name__ == "__main__":
    unittest.main()
