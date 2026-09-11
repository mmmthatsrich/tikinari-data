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

    def test_paekupu_has_no_empty_senses(self):
        # 79% of Paekupu entries carry no definition at all — the English gloss
        # is the entry's own headword_en, which the sense must project (D1).
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='paekupu' AND COALESCE(s.gloss_en,'')='' "
            "AND COALESCE(s.gloss_mi,'')='' "
            "AND COALESCE(s.definition_raw,'')=''"), 0)

    def test_paekupu_definitionless_gloss_is_the_english_headword(self):
        # Projected, not invented: where there is no definition the gloss must be
        # headword_en verbatim, never a paraphrase.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='paekupu' AND s.definition_raw IS NULL "
            "AND s.gloss_en IS NOT e.headword_en"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='paekupu' AND s.definition_raw IS NULL "
            "AND s.gloss_en = e.headword_en"), 13000)

    def test_no_source_stores_an_empty_string_for_absent_text(self):
        # '' reads as present-but-blank everywhere downstream; absence is NULL.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense WHERE gloss_en = '' OR gloss_mi = '' "
            "OR definition_raw = ''"), 0)

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

    def test_bracketed_pos_resolves_to_a_canonical_label(self):
        # Te Matatiki writes '[noun]' and '[noun, transitive verb]'. Splitting on
        # the comma severed the brackets into '[noun' and 'transitive verb]',
        # so 5,371 sense-atoms went unmapped — though 'noun' and 'transitive
        # verb' were in std_pos all along.
        for src in ("te_matatiki", "kimikupu_hou", "tregear_exceptions"):
            with self.subTest(source=src):
                unmapped = self._one(
                    "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
                    "WHERE e.source_id=? AND s.part_of_speech IS NOT NULL "
                    "AND s.part_of_speech_en IS NULL", src)
                self.assertEqual(unmapped, 0)

    def test_no_canonical_pos_label_is_a_bracket_fragment(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense WHERE part_of_speech_en LIKE '%[%' "
            "OR part_of_speech_en LIKE '%]%'"), 0)

    def test_no_domain_is_a_url_slug(self):
        # Paekupu's domains came from `subject_areas`, a JSON list of URL slugs
        # ('te-reo-matatini', 'ngā-toi'), while the same table holds the display
        # forms in subject_area / subject_area_en.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry_domain WHERE domain LIKE '%-%' "
            "AND domain NOT LIKE '% %'"), 0)

    def test_paekupu_domains_are_tagged_in_both_languages(self):
        # Every one of Paekupu's 16,486 domain rows was Māori text tagged 'en'.
        # domain_lang is the only thing telling the app how to render them.
        mi = self._one(
            "SELECT COUNT(*) FROM entry_domain d JOIN entry e ON e.id=d.entry_id "
            "WHERE e.source_id='paekupu' AND d.domain_lang='mi'")
        en = self._one(
            "SELECT COUNT(*) FROM entry_domain d JOIN entry e ON e.id=d.entry_id "
            "WHERE e.source_id='paekupu' AND d.domain_lang='en'")
        self.assertGreater(mi, 16000)
        self.assertGreater(en, 16000)

    def test_paekupu_maori_domain_is_never_tagged_english(self):
        # 'Pūtaiao' is Māori; 'Science' is its English counterpart.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry_domain d JOIN entry e ON e.id=d.entry_id "
            "WHERE e.source_id='paekupu' AND d.domain_lang='en' "
            "AND d.domain IN ('Pūtaiao','Ngā Toi','Hauora','Hangarau','Pāngarau',"
            "'Tikanga ā-Iwi','Te Reo Matatini','Mātauranga Whānui')"), 0)

    def test_te_aka_loan_marker_is_not_a_semantic_domain(self):
        # 'Historical Loan Word' was the single most common value in
        # entry_domain (18,439 rows). It is a register marker; entry.loan_marker
        # is the column for it, and was NULL on every entry in the database.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry_domain d JOIN entry e ON e.id=d.entry_id "
            "WHERE e.source_id='te_aka' AND d.domain LIKE '%Loan%'"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM entry WHERE source_id='te_aka' "
            "AND loan_marker IS NOT NULL"), 18000)

    def test_temarareo_proto_levels_are_not_semantic_domains(self):
        # 'P. Polynesian', 'P. Oceanic' etc. are reconstruction levels. They
        # belong to the etymology layer (ETY_cognateset.level already carries
        # them for these entries), not to entry_domain, which is subject areas.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM entry_domain d JOIN entry e ON e.id=d.entry_id "
            "WHERE e.source_id='temarareo'"), 0)

    def test_temarareo_definition_does_not_repeat_its_own_species(self):
        # `aruhe`: the definition already reads 'Pteridium esculentum
        # (Dennstaedtiaceae)' and had '[Pteridium esculentum]' appended.
        raw = self._one(
            "SELECT s.definition_raw FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='temarareo' AND e.headword='aruhe'")
        self.assertEqual(raw, "Pteridium esculentum (Dennstaedtiaceae)")

    def test_temarareo_species_only_records_are_not_wrapped_in_a_bracket(self):
        # `nonokia`: gloss 'Pomaderris apetala' but definition_raw
        # '[Pomaderris apetala]' — a bracket around the entire content.
        # (Entries whose SOURCE text is bracketed, like `Hapuku`, keep theirs.)
        raw = self._one(
            "SELECT s.definition_raw FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='temarareo' AND e.headword='nonokia'")
        self.assertEqual(raw, "Pomaderris apetala")

    def test_temarareo_note_only_records_still_get_a_gloss(self):
        # 16 entries carry their content in `note` alone ('"stalk, stem" [a word
        # once associated with the coconut]'), leaving gloss_en NULL.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='temarareo' AND s.gloss_en IS NULL"), 0)

    def test_temarareo_gloss_is_never_just_a_protoform(self):
        # `kauere` and `Pūriri` both had gloss_en '*Kauere'.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='temarareo' AND s.gloss_en GLOB '[*]*' "
            "AND s.gloss_en NOT GLOB '[*]* *'"), 0)

    def test_williams_examples_extracted_from_the_definitions(self):
        # Williams prints examples inline after the gloss; before extraction
        # only 61 of 14,942 entries had an example row.
        self.assertGreater(self._one(
            "SELECT COUNT(DISTINCT x.entry_id) FROM example x "
            "JOIN entry e ON e.id=x.entry_id WHERE e.source_id='williams'"), 7000)

    def test_williams_gloss_is_no_longer_the_whole_definition(self):
        # 18,792 senses had gloss_en byte-identical to definition_raw, which is
        # the definition, its examples and its citations in one field.
        same = self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='williams' AND s.gloss_en = s.definition_raw")
        self.assertLess(same, 13000)

    def test_williams_citations_land_in_the_citation_column(self):
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM example x JOIN entry e ON e.id=x.entry_id "
            "WHERE e.source_id='williams' AND x.citation IS NOT NULL"), 5000)

    def test_williams_senses_are_not_truncated_mid_citation(self):
        # The sense-marker separator used to eat the ')' closing the previous
        # sense's citation ('...(Ngā Mōteatea 124'), truncating 148 senses.
        # That signature is an UNCLOSED '(' — strictly more opens than closes.
        #
        # The mirror signature (more closes than opens) is a different, still
        # open defect: `Tūāahu (less correctly tūāhu), n.` loses 'Tūāahu (' to
        # the headword-prefix strip in 01_williams_parse.py, orphaning the rest.
        # 44 senses; tracked separately so this test stays about the splitter.
        # 7 survive and are NOT ours: the 1957 source itself omits the paren.
        # Verified in the Wayback HTML — `Atiti ke ana (<i>It glances off</i>.`
        # has no closing bracket in the original typesetting.
        self.assertLessEqual(self._one(
            "SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
            "WHERE e.source_id='williams' AND "
            "(LENGTH(s.definition_raw)-LENGTH(REPLACE(s.definition_raw,'(',''))) > "
            "(LENGTH(s.definition_raw)-LENGTH(REPLACE(s.definition_raw,')','')))"), 7)

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
