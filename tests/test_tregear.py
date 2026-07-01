"""Session 53: Tregear (NZETC TEI) staging import — schema, integrity, content.

Light staging-layer checks only; full ETY_* coverage lands in S59. Verifies the
scrape+parse produced structurally sane rows: tables exist, FK integrity holds,
headword_norm is populated (the S57 entry bridge depends on it), the language
normalisation collapsed OCR variants, and a known root cluster (HA / Whaka-HA)
carries the expected pronunciation + comparative cognates.
"""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH, normalise_search_key


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class TestTregear(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _count(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def test_tables_populated(self):
        self.assertGreater(self._count("SELECT COUNT(*) FROM tregear_entries"), 9000)
        self.assertGreater(self._count("SELECT COUNT(*) FROM tregear_cognates"), 12000)

    def test_cognate_fk_integrity(self):
        orphans = self._count(
            "SELECT COUNT(*) FROM tregear_cognates c "
            "LEFT JOIN tregear_entries e ON c.tregear_entry_id = e.id "
            "WHERE e.id IS NULL")
        self.assertEqual(orphans, 0, "orphan cognate rows reference missing entries")

    def test_headword_norm_populated(self):
        missing = self._count(
            "SELECT COUNT(*) FROM tregear_entries WHERE headword_norm IS NULL OR headword_norm = ''")
        self.assertEqual(missing, 0)
        # 'Whaka-HA' must fold to the macron/space/hyphen-neutral bridge key.
        row = self.conn.execute(
            "SELECT headword_norm FROM tregear_entries WHERE headword = 'Whaka-HA'").fetchone()
        self.assertEqual(row["headword_norm"], normalise_search_key("whakaha"))

    def test_source_metadata(self):
        row = self.conn.execute(
            "SELECT licence, entry_count FROM source_metadata WHERE source_id = 'tregear'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["licence"], "CC BY-SA 3.0 NZ")
        self.assertEqual(row["entry_count"],
                         self._count("SELECT COUNT(*) FROM tregear_entries"))

    def test_language_normalisation(self):
        # OCR/spelling variants must be folded away, not present as raw languages.
        for bad in ("Paumoutan", "Mangrevan", "Mangaiian", "Fiji"):
            self.assertEqual(
                self._count("SELECT COUNT(*) FROM tregear_cognates WHERE language = ?", bad),
                0, f"un-normalised language {bad!r} leaked into tregear_cognates")
        # canonical forms are present
        for good in ("Hawaiian", "Samoan", "Fijian"):
            self.assertGreater(
                self._count("SELECT COUNT(*) FROM tregear_cognates WHERE language = ?", good), 0)

    def test_known_root_cluster(self):
        ha = self.conn.execute(
            "SELECT pronunciation, gloss_en FROM tregear_entries "
            "WHERE headword = 'HA' AND homonym_index = 1").fetchone()
        self.assertEqual(ha["pronunciation"], "hà")
        self.assertIn("breath", ha["gloss_en"].lower())
        # The root cluster's comparative block carries multiple Polynesian witnesses.
        langs = {r["language"] for r in self.conn.execute(
            "SELECT DISTINCT language FROM tregear_cognates c "
            "JOIN tregear_entries e ON c.tregear_entry_id = e.id "
            "WHERE e.headword = 'Whaka-HA'")}
        self.assertTrue({"Samoan", "Hawaiian", "Tongan"} <= langs)

    def test_extra_polynesian_flag(self):
        # Malay / Malagasy are Extra-Polynesian witnesses.
        ext = self._count(
            "SELECT COUNT(*) FROM tregear_cognates WHERE language IN ('Malay', 'Malagasy') "
            "AND extra_polynesian = 1")
        self.assertGreater(ext, 0)
        # Core Polynesian languages are never flagged extra-Polynesian.
        bad = self._count(
            "SELECT COUNT(*) FROM tregear_cognates "
            "WHERE language IN ('Samoan', 'Hawaiian', 'Tongan') AND extra_polynesian = 1")
        self.assertEqual(bad, 0)


if __name__ == "__main__":
    unittest.main()
