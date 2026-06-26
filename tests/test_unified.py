"""Canonical unified core (SCHEMA_PROPOSAL.md §3) — schema, projection integrity,
language tagging, structured examples, dialect, and FTS.

Assumes the core has been built:  py scripts/50_build_unified.py
"""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

CORE_TABLES = ("entry", "form", "sense", "example", "relation", "entry_domain")
SOURCES = ("williams", "te_aka", "hepatakakupu", "paekupu", "papakupu")


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


class UnifiedCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _one(self, sql, *a):
        return self.conn.execute(sql, a).fetchone()[0]

    # ── schema present ────────────────────────────────────────────────────────
    def test_core_tables_exist(self):
        have = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in CORE_TABLES + ("entry_fts", "sense_fts", "example_fts"):
            self.assertIn(t, have, f"missing core object: {t}")

    def test_entry_has_dialect_and_srcpk_cols(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(entry)")}
        for c in ("source_id", "source_entry_id", "dialect", "headword_search",
                  "content_hash", "first_seen"):
            self.assertIn(c, cols)

    # ── projection completeness ───────────────────────────────────────────────
    def test_every_source_present(self):
        got = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT source_id FROM entry")}
        self.assertEqual(got, set(SOURCES))

    def test_entry_counts_match_source_tables(self):
        pairs = {
            "williams": "williams_entries",
            "te_aka": "te_aka_entries",
            "hepatakakupu": "hepatakakupu_entries",
            "paekupu": "paekupu_entries",
            "papakupu": "papakupu_entries",
        }
        for src, tbl in pairs.items():
            core = self._one("SELECT COUNT(*) FROM entry WHERE source_id=?", src)
            raw = self._one(f"SELECT COUNT(*) FROM {tbl}")
            self.assertEqual(core, raw, f"{src}: entry {core} != {tbl} {raw}")

    def test_every_entry_has_at_least_one_sense(self):
        orphans = self._one(
            "SELECT COUNT(*) FROM entry e "
            "WHERE NOT EXISTS (SELECT 1 FROM sense s WHERE s.entry_id=e.id)")
        self.assertEqual(orphans, 0)

    def test_source_entry_id_unique_per_source(self):
        # device id '{source_id}:{source_entry_id}' must never collide
        dupes = self._one(
            "SELECT COUNT(*) FROM (SELECT source_id, source_entry_id "
            "FROM entry GROUP BY source_id, source_entry_id HAVING COUNT(*) > 1)")
        self.assertEqual(dupes, 0)

    # ── language tagging (the core fix) ───────────────────────────────────────
    def test_hpk_is_monolingual_maori(self):
        # He Pātaka Kupu definitions are Māori -> gloss_mi, never gloss_en
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='hepatakakupu' AND s.gloss_en IS NOT NULL"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='hepatakakupu' AND s.gloss_mi IS NOT NULL"), 20000)

    def test_te_aka_gloss_is_english_only(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='te_aka' AND s.gloss_mi IS NOT NULL"), 0)

    def test_paekupu_bilingual_present(self):
        both = self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='paekupu' AND s.gloss_en IS NOT NULL "
            "AND s.gloss_mi IS NOT NULL")
        self.assertGreater(both, 3000)

    # ── structured examples ───────────────────────────────────────────────────
    def test_te_aka_examples_have_maori_text(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM example x JOIN entry e ON e.id=x.entry_id "
            "WHERE e.source_id='te_aka' AND x.text_mi IS NOT NULL"), 40000)

    def test_example_source_abbrev_joinable(self):
        # the short [SRC] codes should join to source_abbreviations for at least some rows
        self.assertGreater(self._one("SELECT COUNT(*) FROM example "
                                     "WHERE source_abbrev IS NOT NULL"), 5000)

    def test_papakupu_example_slot_holds_text_en(self):
        # text_mi is still NULL (upstream extractor bug) but text_en must be populated
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM example x JOIN entry e ON e.id=x.entry_id "
            "WHERE e.source_id='papakupu' AND x.text_en IS NOT NULL"), 9000)

    # ── dialect ───────────────────────────────────────────────────────────────
    def test_papakupu_dialect_tagged(self):
        non_tt = self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id='papakupu' "
            "AND (dialect IS NULL OR dialect <> 'Tai Tokerau')")
        self.assertEqual(non_tt, 0)

    def test_other_sources_have_no_dialect(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id <> 'papakupu' "
            "AND dialect IS NOT NULL"), 0)

    # ── relation resolution ───────────────────────────────────────────────────
    def test_te_aka_synonyms_mostly_resolved(self):
        total = self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id=r.entry_id "
            "WHERE e.source_id='te_aka' AND r.rel_type='synonym'")
        resolved = self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id=r.entry_id "
            "WHERE e.source_id='te_aka' AND r.rel_type='synonym' "
            "AND r.target_entry_id IS NOT NULL")
        self.assertGreater(resolved / total, 0.95)

    # ── referential + FTS integrity ───────────────────────────────────────────
    def test_no_fk_violations(self):
        self.assertEqual(len(self.conn.execute("PRAGMA foreign_key_check").fetchall()), 0)

    def test_fts_in_sync_with_base(self):
        for base, fts in (("entry", "entry_fts"), ("sense", "sense_fts"),
                          ("example", "example_fts")):
            self.assertEqual(self._one(f"SELECT COUNT(*) FROM {base}"),
                             self._one(f"SELECT COUNT(*) FROM {fts}"),
                             f"{fts} row count out of sync with {base}")

    def test_fts_search_returns_hits(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM entry_fts WHERE entry_fts MATCH 'aroha'"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM example_fts WHERE example_fts MATCH 'whenua'"), 0)


    def test_williams_multisense_split(self):
        rows = self.conn.execute(
            "SELECT s.sense_number, s.part_of_speech FROM entry e JOIN sense s ON s.entry_id=e.id "
            "WHERE e.source_id='williams' AND e.headword_search=? ORDER BY s.sense_number",
            ("pae",)
        ).fetchall()
        nums = [r[0] for r in rows]
        self.assertGreaterEqual(len(nums), 3, f"expected multi-sense, got {nums}")
        self.assertEqual(nums, list(range(1, len(nums) + 1)))   # sequential
        self.assertIsNotNone(rows[0][1])                         # POS populated


if __name__ == "__main__":
    assert DB_PATH.exists(), f"Database not found: {DB_PATH}\nRun: py scripts/00_init_db.py && py scripts/50_build_unified.py"
    unittest.main(verbosity=2)
