"""Sessions 56–58: unified etymology layer (ETY_*) — schema, parity, integrity.

Proves scripts/52_build_etymology_unified.py projected every comparative source
into the ETY_* tables without loss: per-source cognateset/reflex counts equal the
raw source tables (S56 POLLEX/LPO/ACD; S57 adds Tregear + ABVD), the cross-source
ETY_link merge (etymology_links + protoform_ancestry + dedup) and the all-source
ETY_entry_link bridge are populated and FK-clean. S58 adds Walworth as a gap-fill
source (novel protoform / novel (proto_key, language) reflex only, stamped gap_fill=1).
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
        for s in ("pollex", "tregear", "abvd", "walworth"):
            self.assertIn(s, sources, f"no ETY_entry_link rows from {s}")

    def test_entry_link_only_from_maori_reflexes(self):
        # bridge is built strictly from lang_key='maori' reflexes
        bad = self._count(
            "SELECT COUNT(*) FROM ETY_entry_link el "
            "JOIN ETY_reflex r ON el.reflex_id = r.id "
            "WHERE r.lang_key != 'maori' OR r.lang_key IS NULL")
        self.assertEqual(bad, 0, "ETY_entry_link built from a non-Māori reflex")


class TestWalworthGapFill(unittest.TestCase):
    """S58: Walworth promoted only where it fills a gap (novel protoform or novel
    (proto_key, language) reflex), and every promoted row is stamped gap_fill=1."""

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _count(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def test_gap_fill_is_a_strict_subset(self):
        promoted = self._count("SELECT COUNT(*) FROM ETY_cognateset WHERE source='walworth'")
        raw = self._count("SELECT COUNT(*) FROM walworth_cognatesets")
        self.assertGreater(promoted, 0, "no Walworth sets promoted")
        self.assertLess(promoted, raw, "gap-fill promoted every set — not gap-fill")

    def test_all_walworth_rows_stamped_gap_fill(self):
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset WHERE source='walworth' AND gap_fill!=1"),
            0, "a Walworth cognateset is not stamped gap_fill=1")
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE source='walworth' AND gap_fill!=1"),
            0, "a Walworth reflex is not stamped gap_fill=1")

    def test_no_other_source_stamped_gap_fill(self):
        # gap_fill is a Walworth-only flag under the current build.
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset WHERE gap_fill=1 AND source!='walworth'"),
            0)
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex WHERE gap_fill=1 AND source!='walworth'"),
            0)

    def test_every_walworth_set_has_a_protoform(self):
        # only protoform-bearing sets are candidates, so every promoted set has a key.
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_cognateset "
                        "WHERE source='walworth' AND (proto_key IS NULL OR proto_key='')"),
            0, "a Walworth gap set has no proto_key")

    def test_every_reflex_is_novel(self):
        # the core gap-fill invariant: no promoted (proto_key, language) reflex may
        # already be covered by a NON-walworth set sharing that proto_key.
        dup = self._count(
            "SELECT COUNT(*) FROM ETY_cognateset wcs "
            "JOIN ETY_reflex wr ON wr.cognateset_id = wcs.id "
            "JOIN ETY_cognateset ocs "
            "  ON ocs.proto_key = wcs.proto_key AND ocs.source != 'walworth' "
            "JOIN ETY_reflex orf "
            "  ON orf.cognateset_id = ocs.id AND orf.lang_key = wr.lang_key "
            "WHERE wcs.source='walworth'")
        self.assertEqual(dup, 0, "a Walworth reflex duplicates an existing (proto_key, language)")

    def test_reflex_fk_and_source_ref(self):
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex r "
                        "LEFT JOIN ETY_cognateset cs ON r.cognateset_id=cs.id "
                        "WHERE r.source='walworth' AND cs.id IS NULL"),
            0, "orphan Walworth reflex")
        self.assertEqual(
            self._count("SELECT COUNT(*) FROM ETY_reflex "
                        "WHERE source='walworth' AND source_ref IS NULL"),
            0, "Walworth reflex missing source_ref traceback")


APP_DB = Path(__file__).parent.parent / "data" / "maori_dict.db"

# The unified layer the app DB ships after the S59 hard cutover.
ETY_TABLES = ("ETY_level", "ETY_language", "ETY_cognateset",
              "ETY_reflex", "ETY_link", "ETY_entry_link")

# Raw per-source etymology tables removed from the app surface (staging-only now).
RAW_ETY_DROPPED = ("pollex_cognatesets", "pollex_reflexes", "pollex_languages",
                   "lpo_cognatesets", "acd_cognatesets", "etymology_links",
                   "protoform_ancestry", "reconstruction_levels",
                   "pollex_entry_links")

# Sources extracted from Wakareo ā-ipurangi (session 66+ / task 7): held in
# staging only, never shipped in the app DB — see scripts/60_export_app_db.py.
# Duplicated here deliberately (not imported): a test that reads the
# exclusion list from the module it is checking cannot catch that module's
# constant being edited out from under it.
WAKAREO_SOURCES = (
    "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
    "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
    "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
)


@unittest.skipUnless(
    APP_DB.exists(),
    "app DB not exported — run scripts/60_export_app_db.py first")
class TestAppDBEtymologyCutover(unittest.TestCase):
    """S59: the exported app DB (maori_dict.db) ships ONLY the unified ETY_*
    layer — every raw per-source etymology table is dropped, ETY_* row counts
    match staging exactly, and the projection is integrity- and FK-clean."""

    @classmethod
    def setUpClass(cls):
        cls.app = sqlite3.connect(APP_DB)
        cls.app.row_factory = sqlite3.Row
        cls.stg = _open()  # staging (source of the projection)
        cls.app_tables = {r[0] for r in cls.app.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

    @classmethod
    def tearDownClass(cls):
        cls.app.close()
        cls.stg.close()

    def test_ety_tables_shipped(self):
        for t in ETY_TABLES:
            self.assertIn(t, self.app_tables, f"app DB missing {t}")

    def test_raw_etymology_tables_dropped(self):
        leaked = [t for t in RAW_ETY_DROPPED if t in self.app_tables]
        self.assertEqual(leaked, [], f"raw etymology tables leaked into app DB: {leaked}")

    def test_no_raw_source_entries_shipped(self):
        # sanity: the raw `*_entries` landing zone must never reach the app DB
        raw = [t for t in self.app_tables if t.endswith("_entries")]
        self.assertEqual(raw, [], f"raw source tables leaked into app DB: {raw}")

    def test_ety_counts_match_staging(self):
        # ETY_entry_link is keyed to `entry`, and entries from Wakareo sources
        # (task 7) are deliberately excluded from the app DB — see
        # scripts/60_export_app_db.py EXCLUDED_SOURCES. So for that one table,
        # "matches staging" means "matches staging once you drop the rows tied
        # to entries that were never shipped", not a literal row-count equality.
        # The other ETY_* tables are not entry-keyed and are unaffected: the
        # hard cutover guarantee for them stays a strict equality.
        placeholders = ",".join("?" * len(WAKAREO_SOURCES))
        for t in ETY_TABLES:
            app_n = self.app.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if t == "ETY_entry_link":
                stg_n = self.stg.execute(
                    "SELECT COUNT(*) FROM ETY_entry_link el "
                    "JOIN entry e ON el.entry_id = e.id "
                    f"WHERE e.source_id NOT IN ({placeholders})",
                    WAKAREO_SOURCES,
                ).fetchone()[0]
            else:
                stg_n = self.stg.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            self.assertEqual(app_n, stg_n, f"{t}: app {app_n} != staging {stg_n}")

    def test_integrity_and_fk_clean(self):
        ok = self.app.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(ok, "ok", f"app DB integrity_check: {ok}")
        fk = self.app.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(list(fk), [], f"app DB has {len(fk)} dangling FK refs")

    def test_ety_entry_link_resolves_in_app(self):
        # every bridge row must resolve against app-shipped entry + cognateset + reflex
        orphans = self.app.execute(
            "SELECT COUNT(*) FROM ETY_entry_link el "
            "LEFT JOIN entry e         ON el.entry_id = e.id "
            "LEFT JOIN ETY_cognateset c ON el.cognateset_id = c.id "
            "LEFT JOIN ETY_reflex r     ON el.reflex_id = r.id "
            "WHERE e.id IS NULL OR c.id IS NULL "
            "  OR (el.reflex_id IS NOT NULL AND r.id IS NULL)").fetchone()[0]
        self.assertEqual(orphans, 0, "ETY_entry_link has unresolved refs in app DB")

    def test_ety_indexes_shipped(self):
        # the FK indexes added in S56 must ride along so app joins stay fast
        idx = {r[0] for r in self.app.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        for expected in ("idx_ety_reflex_set", "idx_ety_link_target",
                         "idx_ety_entry_link_entry"):
            self.assertIn(expected, idx, f"app DB missing index {expected}")


if __name__ == "__main__":
    unittest.main()
