"""Sessions 56–57: unified etymology layer (ETY_*) — schema, parity, integrity.

Proves scripts/52_build_etymology_unified.py projected every comparative source
into the ETY_* tables without loss: per-source cognateset/reflex counts equal the
raw source tables (S56 POLLEX/LPO/ACD; S57 adds Tregear + ABVD), the cross-source
ETY_link merge (etymology_links + protoform_ancestry + dedup) and the all-source
ETY_entry_link bridge are populated and FK-clean. Walworth gap-fill lands in S58.
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
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_level"),
            self._count("SELECT COUNT(*) FROM reconstruction_levels"))
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_language WHERE source='pollex'"),
            self._count("SELECT COUNT(*) FROM pollex_languages"))

    def test_cognateset_parity(self):
        for src, raw in (("pollex", "pollex_cognatesets"),
                         ("lpo", "lpo_cognatesets"),
                         ("acd", "acd_cognatesets"),
                         ("tregear", "tregear_entries"),
                         ("abvd", "abvd_cognatesets")):
            self.assertEqual(
                self._count("SELECT COUNT(*) FROM ETY_cognateset WHERE source=?", src),
                self._count(f"SELECT COUNT(*) FROM {raw}"),
                f"{src} cognateset count differs from raw {raw}")

    def test_reflex_parity(self):
        # POLLEX + ABVD reflexes equal their raw source tables.
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source='pollex'"),
            self._count("SELECT COUNT(*) FROM pollex_reflexes"))
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source='abvd'"),
            self._count("SELECT COUNT(*) FROM abvd_cognates"))
        # Tregear reflexes = 1 synthetic Māori headword per entry + every cognate.
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source='tregear'"),
            self._count("SELECT COUNT(*) FROM tregear_entries")
            + self._count("SELECT COUNT(*) FROM tregear_cognates"))
        # LPO/ACD carry no reflexes in staging.
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source IN ('lpo','acd')"), 0)

    def test_reflex_fk_integrity(self):
        orphans = self._count(
            "SELECT COUNT(*) FROM ETY_reflex r "
            "LEFT JOIN ETY_cognateset cs ON r.cognateset_id = cs.id "
            "WHERE cs.id IS NULL")
        self.assertEqual(orphans, 0, "ETY_reflex rows reference missing cognatesets")

    def test_provenance_populated(self):
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset "
                        "WHERE source IS NULL OR source_ref IS NULL OR protoform IS NULL"), 0)
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex "
                        "WHERE source IS NULL OR cognateset_id IS NULL"), 0)

    def test_proto_key_populated(self):
        # proto_key drives cross-source dedup. Reconstruction sources always set it
        # (empty only for notation-only protoforms that reduce to nothing, e.g.
        # bare infixes '<in>'). ABVD sets are attested per-concept classes with no
        # reconstructed protoform, so proto_key IS NULL there by design.
        from utils import normalise_proto_key
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset "
                        "WHERE proto_key IS NULL AND source != 'abvd'"), 0)
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset "
                        "WHERE source='abvd' AND proto_key IS NOT NULL"), 0)
        for r in self.conn.execute(
                "SELECT protoform FROM ETY_cognateset WHERE proto_key = ''"):
            self.assertEqual(
                normalise_proto_key(r["protoform"]), "",
                f"empty proto_key for a normalisable protoform: {r['protoform']!r}")

    def test_sampled_set_reflex_count(self):
        row = self.conn.execute(
            "SELECT cs.source_ref, COUNT(r.id) AS n "
            "FROM ETY_cognateset cs JOIN ETY_reflex r ON r.cognateset_id = cs.id "
            "WHERE cs.source='pollex' GROUP BY cs.id ORDER BY n DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        raw_n = self._count(
            "SELECT COUNT(*) FROM pollex_reflexes WHERE cognateset_id=?", row["source_ref"])
        self.assertEqual(raw_n, row["n"])

    # ── S57: ETY_link (cross-source set↔set) ─────────────────────────────────

    def test_link_fk_and_shape(self):
        for col in ("source_set_id", "target_set_id"):
            self.assertEqual(
                self._count(
                    f"SELECT COUNT(*) FROM ETY_link l "
                    f"LEFT JOIN ETY_cognateset c ON l.{col} = c.id WHERE c.id IS NULL"),
                0, f"ETY_link.{col} references a missing cognateset")
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_link WHERE source_set_id = target_set_id"),
            0, "ETY_link must not self-link a set")

    def test_link_origins_present(self):
        origins = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT origin FROM ETY_link")}
        for o in ("etymology_links", "protoform_ancestry", "dedup"):
            self.assertIn(o, origins, f"ETY_link missing rows from origin={o!r}")

    def test_link_ancestry_count_matches_source(self):
        # ancestry links = protoform_ancestry rows NOT already sourced from
        # etymology_links (those are merged via the etymology_links pass instead).
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_link WHERE origin='protoform_ancestry'"),
            self._count("SELECT COUNT(*) FROM protoform_ancestry WHERE source != 'etymology_links'"))

    def test_link_dedup_is_cross_source(self):
        same_src = self._count(
            "SELECT COUNT(*) FROM ETY_link l "
            "JOIN ETY_cognateset a ON l.source_set_id=a.id "
            "JOIN ETY_cognateset b ON l.target_set_id=b.id "
            "WHERE l.origin='dedup' AND a.source = b.source")
        self.assertEqual(same_src, 0, "dedup links must join two DIFFERENT sources")

    # ── S57: ETY_entry_link (reflex → unified entry bridge) ───────────────────

    def test_entry_link_fk_integrity(self):
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_entry_link el "
                        "LEFT JOIN entry e ON el.entry_id = e.id WHERE e.id IS NULL"), 0)
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_entry_link el "
                        "LEFT JOIN ETY_cognateset c ON el.cognateset_id = c.id "
                        "WHERE c.id IS NULL"), 0)
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_entry_link el "
                        "LEFT JOIN ETY_reflex r ON el.reflex_id = r.id WHERE r.id IS NULL"), 0)

    def test_entry_link_pollex_matches_legacy_bridge(self):
        # The POLLEX slice of the all-source bridge must reproduce the standalone
        # pollex_entry_links table exactly (same logic, same Māori reflexes).
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_entry_link WHERE source='pollex'"),
            self._count("SELECT COUNT(*) FROM pollex_entry_links"))

    def test_entry_link_all_maori_sources(self):
        # Every source that carries a Māori reflex should produce bridges.
        sources = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT source FROM ETY_entry_link")}
        for s in ("pollex", "tregear", "abvd"):
            self.assertIn(s, sources, f"no ETY_entry_link rows from {s}")

    def test_entry_link_only_from_maori_reflexes(self):
        # bridge is built strictly from lang_key='maori' reflexes
        bad = self._count(
            "SELECT COUNT(*) FROM ETY_entry_link el "
            "JOIN ETY_reflex r ON el.reflex_id = r.id "
            "WHERE r.lang_key != 'maori' OR r.lang_key IS NULL")
        self.assertEqual(bad, 0, "ETY_entry_link built from a non-Māori reflex")


if __name__ == "__main__":
    unittest.main()
