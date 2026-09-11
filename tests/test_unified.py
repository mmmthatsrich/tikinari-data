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
# Sources expected to have at least one projected entry. Task 6 (session 67)
# added ten Wakareo builders, but seven of their landing tables are still
# empty pending the full scrape sweep — their builders run (0 in -> 0 out) but
# have no rows to assert here yet. Add each as its landing table is populated:
# he_kupu_arotake, kupu_rorohiko, tai_kupu_variants, nga_tini_a_tangaroa,
# kupu_mataora, maori_law_lexicon, tregear_exceptions.
# Sources with at least one row in `entry`. The Wakareo components whose landing
# tables are still empty (he_kupu_arotake, kupu_rorohiko, tai_kupu_variants,
# nga_tini_a_tangaroa, kupu_mataora, maori_law_lexicon) project nothing and so do
# not appear here.
SOURCES = ("williams", "te_aka", "hepatakakupu", "paekupu", "papakupu", "taikupu",
           "temarareo", "ngata", "te_matatiki", "kimikupu_hou",
           "tregear_exceptions")


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
            "taikupu": "taikupu_entries",
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

    # ── Wakareo definitions carry no markup ───────────────────────────────────
    WAKAREO_SOURCES = ("ngata", "te_matatiki", "kimikupu_hou", "tregear_exceptions")

    def test_wakareo_definitions_are_markup_free(self):
        # definition_raw is projected from the cleaned body_text, not the
        # body_raw archive, so no source HTML reaches the app surface.
        for src in self.WAKAREO_SOURCES:
            with self.subTest(source=src):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
                    "WHERE e.source_id=? AND s.definition_raw LIKE '%<%'", src), 0)

    def test_wakareo_definition_is_never_just_the_headword(self):
        # Kimikupu Hou bodies are often `<BR><B>{headword}</B><BR><BR>`; stripped
        # they read as a definition that merely repeats the word. Those are NULL.
        for src in self.WAKAREO_SOURCES:
            with self.subTest(source=src):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
                    "WHERE e.source_id=? AND s.definition_raw = e.headword", src), 0)

    def test_te_matatiki_relations_target_words_not_page_codes(self):
        # `W.61` is a Williams page number, not a Māori headword, so it could
        # never resolve. The derivation's source word is the real target.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id=r.entry_id "
            "WHERE e.source_id='te_matatiki' AND r.target_headword LIKE 'W.%'"), 0)

    def test_te_matatiki_derivations_mostly_resolve_to_williams(self):
        # page + word is a high-precision key; most parts should land.
        total = self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id=r.entry_id "
            "WHERE e.source_id='te_matatiki'")
        resolved = self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id=r.entry_id "
            "WHERE e.source_id='te_matatiki' AND r.target_entry_id IS NOT NULL")
        self.assertGreater(total, 5000)
        self.assertGreater(resolved / total, 0.5)

    def test_forms_never_merely_restate_the_headword(self):
        # A form equal to the headword or to its macron-stripped sort key adds
        # nothing — headword_search already normalises both — and inflates the
        # "this word has variants" signal the app reads.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id=f.entry_id "
            "WHERE LOWER(f.form) IN (LOWER(e.headword), LOWER(e.headword_sort))"), 0)

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

    def test_taikupu_dialect_tagged(self):
        # TaiKupu is Ngāpuhi vocab — same Tai Tokerau dialect boost as Papakupu.
        non_tt = self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id='taikupu' "
            "AND (dialect IS NULL OR dialect <> 'Tai Tokerau')")
        self.assertEqual(non_tt, 0)

    def test_other_sources_have_no_dialect(self):
        # The two Tai Tokerau sources tag every entry; Tregear tags per-entry
        # from its own `[Dialect: ...]` prefix (South Island, Moriori).
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id NOT IN "
            "('papakupu', 'taikupu', 'tregear_exceptions') AND dialect IS NOT NULL"), 0)

    def test_tregear_dialect_casing_is_normalised(self):
        # The source writes both 'South Island' and 'South island'.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id='tregear_exceptions' "
            "AND dialect IS NOT NULL AND dialect <> ''"
            "  AND dialect GLOB '*[a-z] [a-z]*'"), 0)

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

    def test_entry_pos_wrapup(self):
        conn = sqlite3.connect(DB_PATH)
        en, mi, raw = conn.execute(
            "SELECT part_of_speech_en, part_of_speech_mi, part_of_speech FROM entry "
            "WHERE source_id='williams' AND headword_search=? LIMIT 1", ("pae",)
        ).fetchone()
        conn.close()
        assert en and "Noun" in en          # canonical english wrap-up
        assert mi and "Tūingoa" in mi        # canonical māori wrap-up (n. -> Tūingoa)
        assert raw and "n." in raw           # raw set retained

    def test_sense_pos_baked(self):
        # per-sense canonical POS is baked onto the sense row (no std_pos join needed)
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT s.part_of_speech, s.part_of_speech_en, s.part_of_speech_mi "
            "FROM entry e JOIN sense s ON s.entry_id=e.id "
            "WHERE e.source_id='williams' AND e.headword_search='pae' "
            "AND s.part_of_speech='n.' LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row, "expected a williams 'pae' sense with raw POS 'n.'")
        self.assertEqual(row[1], "Noun")        # n. -> Noun
        self.assertEqual(row[2], "Tūingoa")      # n. -> Tūingoa


import importlib
_bu = importlib.import_module("50_build_unified")


class ResolvePos(unittest.TestCase):
    """Pure unit tests for resolve_pos (whole-string-first, atomic comma-split fallback)."""

    def test_whole_string_mapped(self):
        std = {"noun": ("Noun", "Tūingoa")}
        self.assertEqual(_bu.resolve_pos("noun", std), [("Noun", "Tūingoa")])

    def test_whole_string_wins_over_atomic(self):
        std = {"loan, noun": ("Noun", "Tūingoa"), "loan": ("Loan", None), "noun": ("Noun", "Tūingoa")}
        self.assertEqual(_bu.resolve_pos("loan, noun", std), [("Noun", "Tūingoa")])

    def test_atomic_fallback_for_combo(self):
        std = {"ing": ("Verb", "Tūmahi"), "āhua": ("Stative", "Tūāhua")}
        self.assertEqual(
            _bu.resolve_pos("mahp, ing, āhua", std),
            [("Verb", "Tūmahi"), ("Stative", "Tūāhua")],  # 'mahp' unmapped -> skipped
        )

    def test_unmapped_returns_empty(self):
        self.assertEqual(_bu.resolve_pos("xyz", {}), [])

    def test_mi_only_mapping_flows(self):
        # a code with Māori but no English must still resolve (mi-only)
        std = {"thu": (None, "Tūhau")}
        self.assertEqual(_bu.resolve_pos("thu", std), [(None, "Tūhau")])


class WakareoQualifierFold(unittest.TestCase):
    """_fold_qualifier composes 'lemma (qualifier)' without double-parenthesising.

    qualifier is the fidelity layer and is stored exactly as the source gave it
    (Kimikupu qualifiers already carry their own parens); the BUG this pins was
    _wakareo_en_mi always wrapping in a fresh pair of parens regardless, so an
    already-parenthesised qualifier came out doubled: 'Absorbed ((become
    absorbed))'. This test must fail against that old `f"{lemma_en} ({qual})"`
    composition — verified by hand before the fix landed.
    """

    def test_already_parenthesised_qualifier_is_not_doubled(self):
        self.assertEqual(
            _bu._fold_qualifier("Absorbed", "(become absorbed)"),
            "Absorbed (become absorbed)")

    def test_bare_qualifier_still_gets_wrapped(self):
        self.assertEqual(
            _bu._fold_qualifier("View, argument", "balanced"),
            "View, argument (balanced)")

    def test_no_qualifier_leaves_lemma_untouched(self):
        self.assertEqual(_bu._fold_qualifier("Almost", None), "Almost")
        self.assertEqual(_bu._fold_qualifier("Almost", ""), "Almost")

    def test_kimikupu_glosses_have_single_parens(self):
        # end-to-end: the real landing rows that exposed the bug must read
        # correctly post-unify, not just at the unit level.
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT s.gloss_en FROM entry e JOIN sense s ON s.entry_id=e.id "
            "WHERE e.source_id='kimikupu_hou' AND s.gloss_en LIKE '%(%'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0, "expected at least one qualified kimikupu_hou gloss")
        for (gloss,) in rows:
            self.assertNotIn("((", gloss, f"double-parenthesised gloss: {gloss!r}")
            self.assertNotIn("))", gloss, f"double-parenthesised gloss: {gloss!r}")


if __name__ == "__main__":
    assert DB_PATH.exists(), f"Database not found: {DB_PATH}\nRun: py scripts/00_init_db.py && py scripts/50_build_unified.py"
    unittest.main(verbosity=2)
