"""Session 15 verification: PersonalLexicon CRUD, search, export/import, cross-source lookup."""

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from utils import DB_PATH

# Import module with numeric prefix via importlib
_spec = importlib.util.spec_from_file_location(
    "personal_lexicon_crud",
    Path(__file__).parent.parent / "scripts" / "05_personal_lexicon_crud.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PersonalLexicon = _mod.PersonalLexicon


class TestPersonalLexicon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = PersonalLexicon(DB_PATH)
        cls._inserted_ids: list[int] = []

    @classmethod
    def tearDownClass(cls):
        if cls._inserted_ids:
            with sqlite3.connect(DB_PATH) as conn:
                conn.executemany(
                    "DELETE FROM personal_lexicon WHERE id = ?",
                    [(i,) for i in cls._inserted_ids],
                )

    def _add(self, **kwargs) -> int:
        wid = self.lex.add_word(**kwargs)
        self.__class__._inserted_ids.append(wid)
        return wid

    def _remove_id(self, wid: int) -> None:
        try:
            self.__class__._inserted_ids.remove(wid)
        except ValueError:
            pass

    # ── add / get ─────────────────────────────────────────────────────────────

    def test_01_add_and_get(self):
        wid = self._add(
            headword="āho",
            definition="String, line",
            pos="n.",
            tags=["nature"],
            pronunciation="aa-ho",
        )
        entry = self.lex.get_word(wid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["headword"], "āho")
        self.assertEqual(entry["headword_sort"], "aho")
        self.assertEqual(entry["headword_search"], "aho")
        self.assertEqual(entry["definition"], "String, line")
        self.assertEqual(entry["tags"], ["nature"])
        self.assertEqual(entry["pronunciation"], "aa-ho")

    def test_02_get_nonexistent_returns_none(self):
        self.assertIsNone(self.lex.get_word(9_999_999))

    # ── update ────────────────────────────────────────────────────────────────

    def test_03_update_fields(self):
        wid = self._add(headword="aroha", definition="love")
        self.assertTrue(
            self.lex.update_word(wid, definition="love, compassion", tags=["emotion", "core"])
        )
        entry = self.lex.get_word(wid)
        self.assertEqual(entry["definition"], "love, compassion")
        self.assertEqual(entry["tags"], ["core", "emotion"])  # sorted

    def test_04_update_headword_recalculates_keys(self):
        wid = self._add(headword="tane", definition="man")
        self.lex.update_word(wid, headword="Tāne")
        entry = self.lex.get_word(wid)
        self.assertEqual(entry["headword"], "Tāne")
        self.assertEqual(entry["headword_sort"], "tane")
        self.assertEqual(entry["headword_search"], "tane")

    def test_05_update_sets_last_updated(self):
        wid = self._add(headword="wai", definition="water")
        before = self.lex.get_word(wid)["last_updated"]
        self.lex.update_word(wid, definition="water, liquid")
        after = self.lex.get_word(wid)["last_updated"]
        self.assertGreaterEqual(after, before)

    def test_06_update_nonexistent_returns_false(self):
        self.assertFalse(self.lex.update_word(9_999_999, definition="x"))

    def test_07_update_unknown_field_raises(self):
        wid = self._add(headword="motu", definition="island")
        with self.assertRaises(ValueError):
            self.lex.update_word(wid, nonexistent_col="boom")

    # ── delete ────────────────────────────────────────────────────────────────

    def test_08_delete(self):
        wid = self._add(headword="kai", definition="food")
        self.assertTrue(self.lex.delete_word(wid))
        self._remove_id(wid)
        self.assertIsNone(self.lex.get_word(wid))

    def test_09_delete_nonexistent_returns_false(self):
        self.assertFalse(self.lex.delete_word(9_999_999))

    # ── search ────────────────────────────────────────────────────────────────

    def test_10_search_exact(self):
        wid = self._add(headword="whai", definition="to follow")
        results = self.lex.search("whai")
        self.assertTrue(any(r["headword"] == "whai" for r in results))

    def test_11_search_normalisation(self):
        wid = self._add(headword="māra", definition="garden")
        for query in ("mara", "maara"):
            results = self.lex.search(query)
            self.assertTrue(
                any(r["headword"] == "māra" for r in results),
                f"search({query!r}) should return māra",
            )

    def test_12_search_limit(self):
        results = self.lex.search("aho", limit=1)
        self.assertLessEqual(len(results), 1)

    # ── tag helpers ──────────────────────────────────────────────────────────

    def test_13_list_by_tag(self):
        wid = self._add(headword="pō", definition="night", tags=["time", "nature"])
        results = self.lex.list_by_tag("time")
        self.assertTrue(any(r["headword"] == "pō" for r in results))

    def test_14_list_by_tag_no_false_positives(self):
        wid = self._add(headword="ātea", definition="space", tags=["place"])
        results = self.lex.list_by_tag("lace")  # substring of "place" but not a tag
        self.assertFalse(any(r["headword"] == "ātea" for r in results))

    def test_15_list_all_tags(self):
        self._add(headword="rā", definition="sun", tags=["nature", "celestial"])
        self._add(headword="mārama", definition="moon", tags=["nature", "celestial"])
        tags = self.lex.list_all_tags()
        self.assertIn("nature", tags)
        self.assertIn("celestial", tags)
        self.assertEqual(tags, sorted(tags))  # must be sorted

    # ── export / import ───────────────────────────────────────────────────────

    def test_16_export_import_roundtrip(self):
        wid1 = self._add(headword="ika", definition="fish", tags=["fauna"])
        wid2 = self._add(headword="manu", definition="bird", tags=["fauna"])

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = Path(f.name)
        try:
            exported = self.lex.export_json(tmp)
            self.assertGreaterEqual(exported, 2)

            # Verify JSON is valid and contains our entries
            data = json.loads(tmp.read_text(encoding="utf-8"))
            headwords = {e["headword"] for e in data}
            self.assertIn("ika", headwords)
            self.assertIn("manu", headwords)

            # Delete the two entries, then re-import
            self.lex.delete_word(wid1)
            self.lex.delete_word(wid2)
            self._remove_id(wid1)
            self._remove_id(wid2)

            with sqlite3.connect(DB_PATH) as conn:
                before = conn.execute(
                    "SELECT COUNT(*) FROM personal_lexicon"
                ).fetchone()[0]

            imported = self.lex.import_json(tmp)
            self.assertGreaterEqual(imported, 2)

            with sqlite3.connect(DB_PATH) as conn:
                after = conn.execute(
                    "SELECT COUNT(*) FROM personal_lexicon"
                ).fetchone()[0]
                new_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM personal_lexicon ORDER BY id DESC LIMIT ?",
                        (imported,),
                    ).fetchall()
                ]
            self.__class__._inserted_ids.extend(new_ids)

            self.assertEqual(after - before, imported)
        finally:
            tmp.unlink(missing_ok=True)

    # ── cross-source lookup ───────────────────────────────────────────────────

    def test_17_cross_source_lookup_aho(self):
        result = self.lex.cross_source_lookup("aho")
        self.assertIn("williams", result, "williams should have 'āho'")
        self.assertIn("papakupu", result, "papakupu should have 'āho'")
        for source, entries in result.items():
            self.assertIsInstance(entries, list)
            self.assertGreater(len(entries), 0, f"{source} returned empty list")

    def test_18_cross_source_lookup_no_results(self):
        result = self.lex.cross_source_lookup("xyznotaword99999")
        self.assertEqual(result, {})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
