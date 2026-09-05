"""Wakareo sources: provenance integrity in staging, absence from the app DB.

Assumes the pipeline has run:
    py scripts/41_wakareo_import.py
    py scripts/50_build_unified.py --source <each>
    py scripts/60_export_app_db.py
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

APP_DB = Path(__file__).parent.parent / "data" / "maori_dict.db"

WAKAREO_SOURCES = (
    "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
    "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
    "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
)

TAG_FOR_SOURCE = {
    "tregear_exceptions": "TE", "ngata": "HMN", "te_matatiki": "TM",
    "kimikupu_hou": "KKH", "he_kupu_arotake": "HKA", "kupu_rorohiko": "HKR",
    "tai_kupu_variants": "TK", "nga_tini_a_tangaroa": "NT",
    "kupu_mataora": "KM", "maori_law_lexicon": "CL",
}


class Provenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    def test_every_entry_carries_its_own_tag(self):
        for source_id, tag in TAG_FOR_SOURCE.items():
            with self.subTest(source=source_id):
                bad = self.con.execute(
                    "SELECT COUNT(*) FROM entry "
                    "WHERE source_id=? AND source_entry_id NOT LIKE ?",
                    (source_id, f"WR-{tag}.%"),
                ).fetchone()[0]
                self.assertEqual(bad, 0, f"{source_id} has {bad} mistagged entries")

    def test_no_williams_corpus_rows_landed(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM entry WHERE source_entry_id LIKE 'WR-WWC.%'"
        ).fetchone()[0]
        self.assertEqual(n, 0, "Wordstream Williams Corpus rows must never land")

    def test_en_mi_entries_have_maori_headword_and_english_lemma(self):
        for source_id in ("ngata", "kimikupu_hou", "he_kupu_arotake",
                          "kupu_rorohiko", "kupu_mataora"):
            with self.subTest(source=source_id):
                total = self.con.execute(
                    "SELECT COUNT(*) FROM entry WHERE source_id=?", (source_id,)
                ).fetchone()[0]
                if not total:
                    self.skipTest(f"{source_id} not imported yet")
                missing = self.con.execute(
                    "SELECT COUNT(*) FROM entry "
                    "WHERE source_id=? AND (headword_en IS NULL OR headword_en='')",
                    (source_id,),
                ).fetchone()[0]
                self.assertEqual(missing, 0)


class AppDbExclusion(unittest.TestCase):
    def test_no_wakareo_source_reaches_the_app_db(self):
        if not APP_DB.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(APP_DB)
        placeholders = ",".join("?" * len(WAKAREO_SOURCES))
        entries = con.execute(
            f"SELECT COUNT(*) FROM entry WHERE source_id IN ({placeholders})",
            WAKAREO_SOURCES,
        ).fetchone()[0]
        meta = con.execute(
            f"SELECT COUNT(*) FROM source_metadata WHERE source_id IN ({placeholders})",
            WAKAREO_SOURCES,
        ).fetchone()[0]
        con.close()
        self.assertEqual(entries, 0, "Wakareo entries leaked into the app DB")
        self.assertEqual(meta, 0, "Wakareo source_metadata leaked into the app DB")

    def test_app_db_has_no_dangling_relation_targets(self):
        if not APP_DB.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(APP_DB)
        dangling = con.execute(
            "SELECT COUNT(*) FROM relation WHERE target_entry_id IS NOT NULL "
            "AND target_entry_id NOT IN (SELECT id FROM entry)"
        ).fetchone()[0]
        con.close()
        self.assertEqual(dangling, 0)


if __name__ == "__main__":
    unittest.main()
