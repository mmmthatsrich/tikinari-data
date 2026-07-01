"""Session 56: unified etymology layer (ETY_*) — schema, parity, integrity.

Proves scripts/52_build_etymology_unified.py projected POLLEX/LPO/ACD into the
ETY_* tables without loss: per-source cognateset/reflex counts equal the raw
source tables, FK integrity holds, and provenance columns are populated. Tregear/
ABVD/Walworth folding and ETY_link/ETY_entry_link population land in S57–S58, so
those two tables are only checked to exist here.
"""

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class TestEtymologyUnified(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _count(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def test_tables_exist(self):
        have = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'ETY_*'")}
        for t in ("ETY_level", "ETY_language", "ETY_cognateset", "ETY_reflex",
                  "ETY_link", "ETY_entry_link"):
            self.assertIn(t, have, f"{t} missing — run 00_init_db.py")

    def test_reference_tables_populated(self):
        # POLLEX-derived refs
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_level"),
            self._count("SELECT COUNT(*) FROM reconstruction_levels"))
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_language WHERE source='pollex'"),
            self._count("SELECT COUNT(*) FROM pollex_languages"))

    def test_cognateset_parity(self):
        for src, raw in (("pollex", "pollex_cognatesets"),
                         ("lpo", "lpo_cognatesets"),
                         ("acd", "acd_cognatesets")):
            self.assertEqual(
                self._count("SELECT COUNT(*) FROM ETY_cognateset WHERE source=?", src),
                self._count(f"SELECT COUNT(*) FROM {raw}"),
                f"{src} cognateset count differs from raw {raw}")

    def test_reflex_parity(self):
        # LPO/ACD carry no reflexes in staging; only POLLEX projects reflexes at S56.
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source='pollex'"),
            self._count("SELECT COUNT(*) FROM pollex_reflexes"))
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source IN ('lpo','acd')"), 0)

    def test_reflex_fk_integrity(self):
        orphans = self._count(
            "SELECT COUNT(*) FROM ETY_reflex r "
            "LEFT JOIN ETY_cognateset cs ON r.cognateset_id = cs.id "
            "WHERE cs.id IS NULL")
        self.assertEqual(orphans, 0, "ETY_reflex rows reference missing cognatesets")

    def test_provenance_populated(self):
        # every set/reflex must be traceable back to its raw row
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset "
                        "WHERE source IS NULL OR source_ref IS NULL OR protoform IS NULL"), 0)
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex "
                        "WHERE source IS NULL OR cognateset_id IS NULL"), 0)

    def test_proto_key_populated(self):
        # proto_key drives the S57 cross-source dedup; the build always sets it
        # (never NULL). Empty is legitimate ONLY for notation-only protoforms that
        # reduce to nothing under normalise_proto_key (e.g. bare infixes '<in>').
        from utils import normalise_proto_key
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset WHERE proto_key IS NULL"), 0)
        for r in self.conn.execute(
                "SELECT protoform FROM ETY_cognateset WHERE proto_key = ''"):
            self.assertEqual(
                normalise_proto_key(r["protoform"]), "",
                f"empty proto_key for a normalisable protoform: {r['protoform']!r}")

    def test_sampled_set_reflex_count(self):
        # a per-set join must agree with the raw reflex table for that set
        row = self.conn.execute(
            "SELECT cs.source_ref, COUNT(r.id) AS n "
            "FROM ETY_cognateset cs JOIN ETY_reflex r ON r.cognateset_id = cs.id "
            "WHERE cs.source='pollex' GROUP BY cs.id ORDER BY n DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        raw_n = self._count(
            "SELECT COUNT(*) FROM pollex_reflexes WHERE cognateset_id=?", row["source_ref"])
        self.assertEqual(raw_n, row["n"])


if __name__ == "__main__":
    unittest.main()
