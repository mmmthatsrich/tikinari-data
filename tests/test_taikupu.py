"""TaiKupu source — import integrity, orthography, and unified projection.

Assumes the source has been imported and unified:
    py scripts/40_taikupu_import.py
    py scripts/50_build_unified.py --source taikupu
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH, normalise_search_key


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


class TaiKupuSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _one(self, sql, *a):
        return self.conn.execute(sql, a).fetchone()[0]

    # ── raw table ──────────────────────────────────────────────────────────────
    def test_rows_present(self):
        self.assertGreater(self._one("SELECT COUNT(*) FROM taikupu_entries"), 2000)

    def test_source_entry_id_unique(self):
        # TaiKupu's API id is the stable key; the device id depends on its uniqueness.
        self.assertEqual(self._one(
            "SELECT COUNT(*) - COUNT(DISTINCT source_entry_id) FROM taikupu_entries"), 0)

    def test_no_dedup_of_homographs(self):
        # Duplicate headwords are distinct senses (e.g. 'ao' = the world / to scoop up),
        # so the same maori word legitimately appears on more than one row.
        dupes = self._one(
            "SELECT COUNT(*) FROM (SELECT headword FROM taikupu_entries "
            "GROUP BY headword HAVING COUNT(*) > 1)")
        self.assertGreater(dupes, 0)

    def test_search_key_normalised(self):
        # Macron-bearing headword must be findable by its macron-stripped search key.
        row = self.conn.execute(
            "SELECT headword, headword_search FROM taikupu_entries "
            "WHERE headword LIKE '%ā%' OR headword LIKE '%ō%' LIMIT 1").fetchone()
        self.assertIsNotNone(row, "expected at least one macron headword")
        self.assertEqual(row["headword_search"], normalise_search_key(row["headword"]))

    def test_macrons_preserved_in_headword(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM taikupu_entries WHERE headword GLOB '*[āēīōūĀĒĪŌŪ]*'"), 100)

    def test_level_in_range(self):
        bad = self._one(
            "SELECT COUNT(*) FROM taikupu_entries WHERE level IS NOT NULL "
            "AND (level < 1 OR level > 100)")
        self.assertEqual(bad, 0)

    def test_usage_examples_are_bilingual_json(self):
        raw = self.conn.execute(
            "SELECT usage_examples FROM taikupu_entries "
            "WHERE usage_examples IS NOT NULL AND usage_examples <> '[]' LIMIT 1").fetchone()[0]
        ex = json.loads(raw)
        self.assertIsInstance(ex, list)
        self.assertIn("text_mi", ex[0])
        self.assertIn("text_en", ex[0])

    def test_fts_in_sync(self):
        base = self._one("SELECT COUNT(*) FROM taikupu_entries")
        fts = self._one("SELECT COUNT(*) FROM taikupu_fts")
        self.assertEqual(base, fts)

    # ── source metadata / app display ───────────────────────────────────────────
    def test_shown_under_papakupu_banner(self):
        # Separate storage, but the app must render TaiKupu under the same source
        # label as Papakupu o Tai Tokerau.
        taikupu = self._one(
            "SELECT display_name FROM source_metadata WHERE source_id='taikupu'")
        papakupu = self._one(
            "SELECT display_name FROM source_metadata WHERE source_id='papakupu'")
        self.assertEqual(taikupu, papakupu)

    def test_default_dialect_is_tai_tokerau(self):
        self.assertEqual(self._one(
            "SELECT default_dialect FROM source_metadata WHERE source_id='taikupu'"),
            "Tai Tokerau")

    # ── unified projection ───────────────────────────────────────────────────────
    def test_projected_into_unified_core(self):
        core = self._one("SELECT COUNT(*) FROM entry WHERE source_id='taikupu'")
        raw = self._one("SELECT COUNT(*) FROM taikupu_entries")
        self.assertEqual(core, raw)

    def test_projected_entries_carry_dialect(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id='taikupu' "
            "AND (dialect IS NULL OR dialect <> 'Tai Tokerau')"), 0)

    def test_projected_gloss_is_english(self):
        # English gloss lands in gloss_en; monolingual gloss_mi stays empty.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='taikupu' AND s.gloss_mi IS NOT NULL"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='taikupu' AND s.gloss_en IS NOT NULL"), 2000)


if __name__ == "__main__":
    unittest.main()
