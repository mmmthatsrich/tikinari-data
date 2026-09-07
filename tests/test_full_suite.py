"""Session 17: Full test suite — schema, data quality, FTS, search normalisation,
metadata integrity, etymology tables, source abbreviations, and performance."""

import json
import sqlite3
import sys
import time
import unicodedata
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import (
    DB_PATH,
    compute_content_hash,
    expand_citations,
    load_source_abbrevs,
    normalise_proto_key,
    normalise_search_key,
    normalise_sort_key,
)


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','shadow')"
    ).fetchall()
    return {r[0] for r in rows}


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _has_macron(text: str) -> bool:
    nfd = unicodedata.normalize("NFD", text)
    return any(unicodedata.category(c) == "Mn" for c in nfd)


# ── 1. Utils / normalisation ──────────────────────────────────────────────────

class TestNormalisation(unittest.TestCase):

    def test_sort_key_strips_macrons(self):
        self.assertEqual(normalise_sort_key("āho"), "aho")
        self.assertEqual(normalise_sort_key("Āho"), "aho")
        self.assertEqual(normalise_sort_key("whānau"), "whanau")

    def test_sort_key_preserves_double_vowels(self):
        self.assertEqual(normalise_sort_key("aaho"), "aaho")

    def test_search_key_strips_macrons(self):
        self.assertEqual(normalise_search_key("āho"), "aho")
        self.assertEqual(normalise_search_key("whānau"), "whanau")

    def test_search_key_collapses_double_vowels(self):
        self.assertEqual(normalise_search_key("aaho"), "aho")
        self.assertEqual(normalise_search_key("whaanau"), "whanau")
        self.assertEqual(normalise_search_key("aapiha"), "apiha")

    def test_search_key_plain_unchanged(self):
        self.assertEqual(normalise_search_key("aho"), "aho")
        self.assertEqual(normalise_search_key("whanau"), "whanau")

    def test_search_key_ao_not_collapsed(self):
        self.assertEqual(normalise_search_key("kaokao"), "kaokao")

    def test_search_key_three_forms_equivalent(self):
        for word in ("āho", "aaho", "aho"):
            self.assertEqual(normalise_search_key(word), "aho", f"failed for {word!r}")
        for word in ("whānau", "whaanau", "whanau"):
            self.assertEqual(normalise_search_key(word), "whanau", f"failed for {word!r}")

    def test_compute_content_hash_stable(self):
        fields = {"headword": "āho", "definition": "String, line.", "tags": ["nature", "core"]}
        h1 = compute_content_hash(fields)
        h2 = compute_content_hash(fields)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_compute_content_hash_list_order_invariant(self):
        h1 = compute_content_hash({"tags": ["b", "a"]})
        h2 = compute_content_hash({"tags": ["a", "b"]})
        self.assertEqual(h1, h2)

    def test_normalise_proto_key_strips_asterisk(self):
        self.assertEqual(normalise_proto_key("*afo"), "afo")
        self.assertEqual(normalise_proto_key("*AHO"), "aho")

    def test_normalise_proto_key_strips_notation(self):
        self.assertEqual(normalise_proto_key("*afo(afo)"), "afo")
        self.assertEqual(normalise_proto_key("*t<um>agis"), "tagis")

    def test_normalise_proto_key_unicode_angle_brackets(self):
        # LPO uses U+27E8/U+27E9 mathematical angle brackets for infix notation
        self.assertEqual(normalise_proto_key("*t⟨um⟩agis"), "tagis")
        self.assertEqual(normalise_proto_key("p⟨in⟩inum"), "pinum")

    def test_expand_citations(self):
        abbrevs = {"TTR": {"full_name": "Ngā Tāngata Taumata Rau", "pub_type": "book",
                            "year_range": None, "notes": None}}
        result = expand_citations("Ko te aho (TTR 1996:46).", abbrevs)
        self.assertIn("Ngā Tāngata Taumata Rau", result)
        self.assertNotIn("TTR", result)

    def test_expand_citations_unknown_abbrev_unchanged(self):
        result = expand_citations("Ko te aho (ZZZ 1999).", {})
        self.assertIn("ZZZ", result)


# ── 2. Schema integrity ───────────────────────────────────────────────────────

class TestSchema(unittest.TestCase):

    CONTENT_TABLES = [
        "williams_entries", "papakupu_entries", "pollex_entries",
        "te_aka_entries", "hepatakakupu_entries", "paekupu_entries",
        "personal_lexicon",
    ]
    FTS_TABLES = [
        "williams_fts", "papakupu_fts", "pollex_fts",
        "te_aka_fts", "hepatakakupu_fts", "paekupu_fts", "personal_fts",
    ]
    ETYMOLOGY_TABLES = [
        "pollex_cognatesets", "pollex_reflexes",
        "lpo_cognatesets", "acd_cognatesets", "etymology_links",
        "pollex_entry_links",
    ]
    AUX_TABLES = [
        "source_metadata", "source_abbreviations",
        "data_refresh_runs", "data_refresh_log",
    ]

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()
        cls.existing = _tables(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_content_tables_exist(self):
        for t in self.CONTENT_TABLES:
            self.assertIn(t, self.existing, f"Missing table: {t}")

    def test_fts_tables_exist(self):
        for t in self.FTS_TABLES:
            self.assertIn(t, self.existing, f"Missing FTS table: {t}")

    def test_etymology_tables_exist(self):
        for t in self.ETYMOLOGY_TABLES:
            self.assertIn(t, self.existing, f"Missing etymology table: {t}")

    def test_aux_tables_exist(self):
        for t in self.AUX_TABLES:
            self.assertIn(t, self.existing, f"Missing auxiliary table: {t}")

    def _assert_cols(self, table, required):
        actual = _cols(self.conn, table)
        for col in required:
            self.assertIn(col, actual, f"{table} missing column: {col}")

    def test_williams_columns(self):
        self._assert_cols("williams_entries", [
            "id", "headword", "headword_sort", "headword_search",
            "part_of_speech", "definition", "usage_examples",
            "sense_number", "cross_refs", "page_number", "source_section",
        ])

    def test_papakupu_columns(self):
        self._assert_cols("papakupu_entries", [
            "id", "headword", "headword_sort", "headword_search",
            "variant_forms", "variant_search_keys", "source_code",
            "loan_marker", "see_also", "pdf_page",
        ])

    def test_pollex_columns(self):
        self._assert_cols("pollex_entries", [
            "id", "headword", "headword_sort", "headword_search",
            "protoform", "protoform_desc", "maori_reflex", "maori_gloss",
            "source_citation", "source_author", "cognateset_id", "pollex_url",
        ])

    def test_te_aka_columns(self):
        self._assert_cols("te_aka_entries", [
            "id", "word_id", "headword", "headword_sort", "headword_search",
            "part_of_speech", "definition", "usage_examples",
            "audio_url", "synonyms", "source_citations", "filters",
            "content_hash", "first_seen",
        ])

    def test_hepatakakupu_columns(self):
        self._assert_cols("hepatakakupu_entries", [
            "id", "word_id", "headword", "headword_sort", "headword_search",
            "part_of_speech", "definition", "usage_examples",
            "sense_number", "synonyms", "semantic_domain", "definition_mi",
        ])

    def test_paekupu_columns(self):
        self._assert_cols("paekupu_entries", [
            "id", "slug", "headword", "headword_sort", "headword_search",
            "headword_en", "part_of_speech", "pos_mi",
            "subject_area", "subject_areas", "audio_url",
            "definition_mi", "definition", "alternative_words", "usage_examples",
            "content_hash", "first_seen",
        ])

    def test_pollex_cognatesets_columns(self):
        self._assert_cols("pollex_cognatesets", [
            "id", "protoform_name", "level", "level_name",
            "description", "reconstruction", "notes", "pollex_url",
        ])

    def test_pollex_reflexes_columns(self):
        self._assert_cols("pollex_reflexes", [
            "id", "cognateset_id", "language", "language_slug",
            "reflex", "gloss", "source_code", "source_author", "flags",
        ])

    def test_lpo_cognatesets_columns(self):
        self._assert_cols("lpo_cognatesets", [
            "id", "name", "name_key", "description", "level",
            "chapter_id", "chapter_title",
        ])

    def test_acd_cognatesets_columns(self):
        self._assert_cols("acd_cognatesets", [
            "id", "name", "name_key", "description", "level", "etymon_id",
        ])

    def test_etymology_links_columns(self):
        self._assert_cols("etymology_links", [
            "id", "pollex_cognateset_id", "lpo_cognateset_id", "acd_cognateset_id",
            "match_confidence", "match_method", "lpo_citation", "notes",
        ])

    def test_pollex_entry_links_columns(self):
        self._assert_cols("pollex_entry_links", [
            "id", "cognateset_id", "reflex_id", "entry_id",
            "match_key", "match_method", "match_confidence",
        ])

    def test_source_abbreviations_columns(self):
        self._assert_cols("source_abbreviations", [
            "abbrev", "source_dict", "full_name", "pub_type", "year_range", "notes",
        ])

    def test_data_refresh_runs_columns(self):
        self._assert_cols("data_refresh_runs", [
            "id", "source_dict", "run_at",
            "new_count", "modified_count", "deleted_count", "unchanged_count",
        ])

    def test_data_refresh_log_columns(self):
        self._assert_cols("data_refresh_log", [
            "id", "run_id", "source_dict", "entry_key", "headword",
            "change_type", "changed_fields", "old_values", "new_values", "logged_at",
        ])


# ── 3. Row counts ─────────────────────────────────────────────────────────────

class TestRowCounts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _check(self, table, minimum):
        n = _count(self.conn, table)
        self.assertGreaterEqual(n, minimum, f"{table}: {n} rows < expected {minimum}")

    def test_williams_count(self):      self._check("williams_entries", 11_000)
    def test_papakupu_count(self):      self._check("papakupu_entries", 4_600)
    def test_pollex_count(self):        self._check("pollex_entries", 3_000)
    def test_te_aka_count(self):        self._check("te_aka_entries", 40_000)
    def test_hepatakakupu_count(self):  self._check("hepatakakupu_entries", 20_000)
    def test_paekupu_count(self):       self._check("paekupu_entries", 15_000)
    def test_pollex_cognatesets(self):  self._check("pollex_cognatesets", 2_900)
    def test_pollex_reflexes(self):     self._check("pollex_reflexes", 40_000)
    def test_lpo_cognatesets(self):     self._check("lpo_cognatesets", 2_800)
    def test_acd_cognatesets(self):     self._check("acd_cognatesets", 10_000)
    def test_source_abbreviations(self): self._check("source_abbreviations", 145)


# ── 4. Data quality ───────────────────────────────────────────────────────────

class TestDataQuality(unittest.TestCase):

    CONTENT_TABLES = [
        "williams_entries", "papakupu_entries", "pollex_entries",
        "te_aka_entries", "hepatakakupu_entries", "paekupu_entries",
    ]

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_no_null_headwords(self):
        for t in self.CONTENT_TABLES:
            n = self.conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE headword IS NULL OR trim(headword) = ''"
            ).fetchone()[0]
            self.assertEqual(n, 0, f"{t} has {n} NULL/empty headwords")

    def test_headword_sort_no_macrons(self):
        for t in self.CONTENT_TABLES:
            rows = self.conn.execute(f"SELECT headword_sort FROM {t}").fetchall()
            flagged = [r[0] for r in rows if _has_macron(r[0])]
            self.assertEqual(flagged, [], f"{t} headword_sort has macrons: {flagged[:3]}")

    def test_headword_search_no_macrons(self):
        for t in self.CONTENT_TABLES:
            rows = self.conn.execute(f"SELECT headword_search FROM {t}").fetchall()
            flagged = [r[0] for r in rows if _has_macron(r[0])]
            self.assertEqual(flagged, [], f"{t} headword_search has macrons: {flagged[:3]}")

    def test_headword_sort_mostly_ascii(self):
        # Williams has ~11 entries with special punctuation (em-dash, ‖) after macron strip.
        # Allow up to 20 non-ASCII headword_sort per table.
        for t in self.CONTENT_TABLES:
            rows = self.conn.execute(f"SELECT headword_sort FROM {t}").fetchall()
            non_ascii = [r[0] for r in rows if not r[0].isascii()]
            self.assertLessEqual(
                len(non_ascii), 20,
                f"{t}: {len(non_ascii)} non-ASCII headword_sort values: {non_ascii[:3]}",
            )

    def test_williams_all_sections_covered(self):
        sections = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT source_section FROM williams_entries"
        ).fetchall()}
        expected = {"A", "E", "H", "I", "K", "M", "N", "Ng", "O", "P", "R", "T", "U", "W"}
        self.assertEqual(sections, expected)

    def test_json_columns_parseable(self):
        checks = [
            ("williams_entries",       "usage_examples"),
            ("williams_entries",       "cross_refs"),
            ("papakupu_entries",       "variant_forms"),
            ("papakupu_entries",       "variant_search_keys"),
            ("papakupu_entries",       "see_also"),
            ("te_aka_entries",         "usage_examples"),
            ("te_aka_entries",         "synonyms"),
            ("te_aka_entries",         "filters"),
            ("hepatakakupu_entries",   "usage_examples"),
            ("hepatakakupu_entries",   "synonyms"),
            ("paekupu_entries",        "subject_areas"),
            ("paekupu_entries",        "alternative_words"),
            ("paekupu_entries",        "usage_examples"),
        ]
        for table, col in checks:
            rows = self.conn.execute(
                f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL LIMIT 200"
            ).fetchall()
            for row in rows:
                try:
                    json.loads(row[0])
                except json.JSONDecodeError as e:
                    self.fail(f"{table}.{col} contains invalid JSON: {row[0][:80]} — {e}")

    def test_papakupu_macrons_in_headwords(self):
        # Papakupu uses macrons throughout — expect many macron headwords
        n = self.conn.execute(
            "SELECT COUNT(*) FROM papakupu_entries WHERE headword LIKE '%ā%'"
            " OR headword LIKE '%ē%' OR headword LIKE '%ī%'"
            " OR headword LIKE '%ō%' OR headword LIKE '%ū%'"
        ).fetchone()[0]
        self.assertGreater(n, 500, f"Too few macron headwords in papakupu: {n}")

    def test_pollex_cognatesets_level_names_complete(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_cognatesets"
            " WHERE level_name IS NULL OR level_name = '' OR level_name LIKE '% - %'"
        ).fetchone()[0]
        self.assertEqual(n, 0, f"{n} pollex_cognatesets have missing/placeholder level_name")

    def test_te_aka_content_hash_populated(self):
        total = _count(self.conn, "te_aka_entries")
        hashed = self.conn.execute(
            "SELECT COUNT(*) FROM te_aka_entries WHERE content_hash IS NOT NULL"
        ).fetchone()[0]
        self.assertGreaterEqual(hashed / total, 0.99, "te_aka content_hash < 99% populated")

    def test_paekupu_content_hash_populated(self):
        total = _count(self.conn, "paekupu_entries")
        hashed = self.conn.execute(
            "SELECT COUNT(*) FROM paekupu_entries WHERE content_hash IS NOT NULL"
        ).fetchone()[0]
        self.assertGreaterEqual(hashed / total, 0.99, "paekupu content_hash < 99% populated")

    def test_paekupu_slug_unique(self):
        total = _count(self.conn, "paekupu_entries")
        unique = self.conn.execute(
            "SELECT COUNT(DISTINCT slug) FROM paekupu_entries"
        ).fetchone()[0]
        self.assertEqual(total, unique, "paekupu_entries.slug has duplicates")

    def test_te_aka_word_id_indexed_entry(self):
        row = self.conn.execute(
            "SELECT headword FROM te_aka_entries WHERE word_id = 79"
        ).fetchone()
        self.assertIsNotNone(row, "te_aka word_id=79 not found")
        self.assertIn("aho", row[0].lower())

    def test_papakupu_variant_search_keys_format(self):
        row = self.conn.execute(
            "SELECT variant_search_keys FROM papakupu_entries"
            " WHERE headword_search = 'apiha'"
        ).fetchone()
        self.assertIsNotNone(row, "papakupu has no entry with headword_search='apiha'")
        keys = json.loads(row[0])
        self.assertIn("apiha", keys)


# ── 5. FTS correctness ────────────────────────────────────────────────────────

class TestFTS(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _match(self, fts_table, query, min_results=1):
        rows = self.conn.execute(
            f"SELECT headword FROM {fts_table} WHERE {fts_table} MATCH ?", (query,)
        ).fetchall()
        self.assertGreaterEqual(
            len(rows), min_results,
            f"{fts_table} MATCH {query!r} returned {len(rows)} rows",
        )
        return [r[0] for r in rows]

    def test_williams_fts_aroha(self):
        headwords = self._match("williams_fts", "aroha", min_results=1)
        self.assertTrue(
            any("aroha" in h.lower() for h in headwords),
            f"'Aroha' not among FTS results for 'aroha': {headwords[:5]}",
        )

    def test_williams_fts_rope_via_definition(self):
        # 'rope' should appear in Williams definitions even if not a headword
        self._match("williams_fts", "rope", min_results=1)

    def test_williams_fts_prefix(self):
        # prefix search: ahor* → Ahorangi, Ahore, Ahoroa
        self._match("williams_fts", "ahor*", min_results=2)

    def test_papakupu_fts(self):
        self._match("papakupu_fts", "aroha", min_results=1)

    def test_te_aka_fts(self):
        self._match("te_aka_fts", "aroha", min_results=1)

    def test_hepatakakupu_fts(self):
        self._match("hepatakakupu_fts", "manu", min_results=1)

    def test_paekupu_fts(self):
        self._match("paekupu_fts", "health", min_results=1)

    def test_pollex_fts(self):
        self._match("pollex_fts", "rope", min_results=1)


# ── 6. Search normalisation against DB ───────────────────────────────────────

class TestSearchNormalisation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_williams_aho_exact(self):
        row = self.conn.execute(
            "SELECT headword FROM williams_entries WHERE headword_search = 'aho'"
        ).fetchone()
        self.assertIsNotNone(row, "williams: no entry with headword_search='aho'")

    def test_williams_aho_via_macron_query(self):
        key = normalise_search_key("āho")
        row = self.conn.execute(
            "SELECT headword FROM williams_entries WHERE headword_search = ?", (key,)
        ).fetchone()
        self.assertIsNotNone(row, "williams: normalise('āho') did not find aho entry")

    def test_williams_aho_via_double_vowel_query(self):
        key = normalise_search_key("aaho")
        row = self.conn.execute(
            "SELECT headword FROM williams_entries WHERE headword_search = ?", (key,)
        ).fetchone()
        self.assertIsNotNone(row, "williams: normalise('aaho') did not find aho entry")

    def test_papakupu_apiha_exact(self):
        row = self.conn.execute(
            "SELECT headword FROM papakupu_entries WHERE headword_search = 'apiha'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "āpiha")

    def test_papakupu_variant_search_keys(self):
        row = self.conn.execute(
            "SELECT headword FROM papakupu_entries"
            " WHERE variant_search_keys LIKE '%\"apiha\"%'"
        ).fetchone()
        self.assertIsNotNone(row, "papakupu variant_search_keys does not contain 'apiha'")
        self.assertEqual(row[0], "āpiha")

    def test_papakupu_aho_via_double_vowel(self):
        key = normalise_search_key("aaho")
        rows = self.conn.execute(
            "SELECT headword FROM papakupu_entries WHERE headword_search = ?", (key,)
        ).fetchall()
        self.assertTrue(len(rows) > 0, "papakupu: normalise('aaho') found no entries")

    def test_te_aka_aroha(self):
        row = self.conn.execute(
            "SELECT headword FROM te_aka_entries WHERE headword_search = 'aroha' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row, "te_aka: no entry with headword_search='aroha'")

    def test_hepatakakupu_whare(self):
        key = normalise_search_key("whare")
        row = self.conn.execute(
            "SELECT headword FROM hepatakakupu_entries WHERE headword_search = ? LIMIT 1",
            (key,),
        ).fetchone()
        self.assertIsNotNone(row, "hepatakakupu: no entry with headword_search='whare'")

    def test_paekupu_hauora(self):
        key = normalise_search_key("hauora")
        row = self.conn.execute(
            "SELECT headword FROM paekupu_entries WHERE headword_search = ? LIMIT 1",
            (key,),
        ).fetchone()
        self.assertIsNotNone(row, "paekupu: no entry with headword_search='hauora'")


# ── 7. Source metadata integrity ─────────────────────────────────────────────

class TestSourceMetadata(unittest.TestCase):

    EXPECTED_SOURCES = {
        "williams", "papakupu", "pollex", "te_aka",
        "hepatakakupu", "paekupu", "personal", "taikupu",
        "pollex_cognatesets", "lpo", "acd", "abvd", "walworth", "tregear",
        "temarareo",
        # Wakareo ā-ipurangi components (session 67, Task 4 landing tables):
        "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
        "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
        "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
    }
    COUNT_SOURCES = {
        "williams":          "williams_entries",
        "temarareo":         "temarareo_entries",
        "papakupu":          "papakupu_entries",
        "pollex":            "pollex_entries",
        "te_aka":            "te_aka_entries",
        "hepatakakupu":      "hepatakakupu_entries",
        "paekupu":           "paekupu_entries",
        "taikupu":           "taikupu_entries",
        "pollex_cognatesets": "pollex_cognatesets",
        "lpo":               "lpo_cognatesets",
        "acd":               "acd_cognatesets",
        # Wakareo landing tables: entry_count is written in the same
        # transaction as the rows by 41_wakareo_import.py's import_source(),
        # so it stays in lockstep with the table whether the table is fully
        # populated, empty, or partially extracted.
        "tregear_exceptions": "tregear_exceptions_entries",
        "ngata":              "ngata_entries",
        "te_matatiki":        "te_matatiki_entries",
        "kimikupu_hou":       "kimikupu_hou_entries",
        "he_kupu_arotake":    "he_kupu_arotake_entries",
        "kupu_rorohiko":      "kupu_rorohiko_entries",
        "tai_kupu_variants":  "tai_kupu_variants_entries",
        "nga_tini_a_tangaroa": "nga_tini_a_tangaroa_entries",
        "kupu_mataora":       "kupu_mataora_entries",
        "maori_law_lexicon":  "maori_law_lexicon_entries",
    }

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()
        cls.meta = {
            r["source_id"]: dict(r)
            for r in cls.conn.execute("SELECT * FROM source_metadata").fetchall()
        }

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_all_sources_present(self):
        self.assertEqual(
            set(self.meta.keys()), self.EXPECTED_SOURCES,
            f"source_metadata mismatch: {set(self.meta.keys())} != {self.EXPECTED_SOURCES}",
        )

    def test_entry_counts_match_actual(self):
        for source_id, table in self.COUNT_SOURCES.items():
            meta_count = self.meta[source_id]["entry_count"]
            actual = _count(self.conn, table)
            self.assertEqual(
                meta_count, actual,
                f"{source_id}: source_metadata.entry_count={meta_count} != actual {actual}",
            )

    def test_last_updated_parseable_datetime(self):
        for source_id, row in self.meta.items():
            ts = row.get("last_updated")
            if ts is None:
                continue  # personal lexicon may have NULL
            try:
                datetime.fromisoformat(ts)
            except ValueError:
                self.fail(f"source_metadata[{source_id}].last_updated not ISO datetime: {ts!r}")


# ── 8. Etymology tables ───────────────────────────────────────────────────────

class TestEtymologyTables(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_pollex_cognatesets_level_distribution(self):
        rows = self.conn.execute(
            "SELECT level, COUNT(*) FROM pollex_cognatesets GROUP BY level ORDER BY COUNT(*) DESC"
        ).fetchall()
        levels = {r[0] for r in rows}
        self.assertIn("OC", levels, "pollex_cognatesets missing OC level")
        self.assertIn("AN", levels, "pollex_cognatesets missing AN level")

    def test_pollex_reflexes_linked_to_cognatesets(self):
        # All reflexes should have a valid cognateset_id
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_reflexes r"
            " LEFT JOIN pollex_cognatesets c ON r.cognateset_id = c.id"
            " WHERE c.id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0, f"{orphans} pollex_reflexes have no matching cognateset")

    def test_pollex_entries_have_cognateset_ids(self):
        # Most pollex_entries should have a cognateset_id (some may be NULL)
        total = _count(self.conn, "pollex_entries")
        linked = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_entries WHERE cognateset_id IS NOT NULL"
        ).fetchone()[0]
        self.assertGreater(linked / total, 0.8, "< 80% of pollex_entries have cognateset_id")

    def test_lpo_name_keys_populated(self):
        null_keys = self.conn.execute(
            "SELECT COUNT(*) FROM lpo_cognatesets WHERE name_key IS NULL OR name_key = ''"
        ).fetchone()[0]
        self.assertEqual(null_keys, 0, f"{null_keys} lpo_cognatesets have NULL/empty name_key")

    def test_acd_level_variety(self):
        levels = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT level FROM acd_cognatesets WHERE level IS NOT NULL"
        ).fetchall()}
        # ACD's raw all-caps PAN/POC are canonicalised at ingest (canonical_level)
        # to the mixed-case node codes PAn/POc; PMP is already canonical.
        for expected in ("PAn", "PMP", "POc"):
            self.assertIn(expected, levels, f"acd_cognatesets missing level {expected}")

    def test_acd_name_keys_populated(self):
        # 2 known exceptions: PAN infixes <in> and <um> normalise to empty string
        null_keys = self.conn.execute(
            "SELECT COUNT(*) FROM acd_cognatesets WHERE name_key IS NULL OR name_key = ''"
        ).fetchone()[0]
        self.assertLessEqual(
            null_keys, 5,
            f"{null_keys} acd_cognatesets have NULL/empty name_key (expected <= 5 infix edge cases)",
        )

    def test_etymology_links_populated(self):
        n = _count(self.conn, "etymology_links")
        self.assertGreater(n, 200, f"etymology_links has only {n} rows (expected > 200)")

    def test_etymology_links_no_orphan_pollex(self):
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM etymology_links el"
            " LEFT JOIN pollex_cognatesets pc ON el.pollex_cognateset_id = pc.id"
            " WHERE pc.id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0, f"{orphans} etymology_links reference unknown pollex cognatesets")

    def test_etymology_links_no_orphan_lpo(self):
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM etymology_links el"
            " LEFT JOIN lpo_cognatesets lc ON el.lpo_cognateset_id = lc.id"
            " WHERE el.lpo_cognateset_id IS NOT NULL AND lc.id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0, f"{orphans} etymology_links reference unknown LPO cognatesets")

    def test_etymology_links_no_orphan_acd(self):
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM etymology_links el"
            " LEFT JOIN acd_cognatesets ac ON el.acd_cognateset_id = ac.id"
            " WHERE el.acd_cognateset_id IS NOT NULL AND ac.id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0, f"{orphans} etymology_links reference unknown ACD cognatesets")

    def test_etymology_links_confidence_range(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) FROM etymology_links"
            " WHERE match_confidence < 0.0 OR match_confidence > 1.0"
        ).fetchone()[0]
        self.assertEqual(bad, 0, f"{bad} etymology_links have confidence outside [0.0, 1.0]")

    def test_etymology_links_known_match(self):
        # POLLEX MP.MIMI "urinate" should link to LPO mimi(s) and ACD mimi
        row = self.conn.execute(
            "SELECT el.lpo_cognateset_id, el.acd_cognateset_id"
            " FROM etymology_links el"
            " JOIN pollex_cognatesets pc ON el.pollex_cognateset_id = pc.id"
            " WHERE pc.id = 'mimi'"
        ).fetchone()
        self.assertIsNotNone(row, "No etymology link found for POLLEX 'mimi'")
        self.assertIsNotNone(row[0], "POLLEX mimi missing LPO link")
        self.assertIsNotNone(row[1], "POLLEX mimi missing ACD link")

    def test_etymology_links_methods_present(self):
        methods = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT match_method FROM etymology_links WHERE match_method IS NOT NULL"
        ).fetchall()}
        self.assertTrue(
            any("tier2_acd_citation" in m for m in methods),
            "No tier2_acd_citation method links found",
        )
        self.assertTrue(
            any("tier1_formkey" in m for m in methods),
            "No tier1_formkey method links found",
        )

    def test_etymology_links_polynesian_level_matches(self):
        # PN/NP/CE → LPO PPn/PNPn/PCEPn mapping should produce form-key matches
        # at Polynesian levels (the original LEVEL_MAP omitted these).
        n = self.conn.execute(
            "SELECT COUNT(*) FROM etymology_links el"
            " JOIN pollex_cognatesets pc ON el.pollex_cognateset_id = pc.id"
            " JOIN lpo_cognatesets lc ON el.lpo_cognateset_id = lc.id"
            " WHERE pc.level IN ('PN','NP','CE')"
            "   AND lc.level IN ('PPn','PNPn','PCEPn')"
        ).fetchone()[0]
        self.assertGreater(n, 0, "No POLLEX Polynesian-level links to LPO PPn/PNPn/PCEPn")


# ── 8b. POLLEX reflex → entry links ───────────────────────────────────────────

class TestPollexEntryLinks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_populated(self):
        n = _count(self.conn, "pollex_entry_links")
        self.assertGreater(n, 10000, f"pollex_entry_links has only {n} rows (expected > 10000)")

    def test_no_orphan_cognateset(self):
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_entry_links pel"
            " LEFT JOIN pollex_cognatesets pc ON pel.cognateset_id = pc.id"
            " WHERE pc.id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0, f"{orphans} pollex_entry_links reference unknown cognatesets")

    def test_no_orphan_entry(self):
        orphans = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_entry_links pel"
            " LEFT JOIN entry e ON pel.entry_id = e.id"
            " WHERE e.id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0, f"{orphans} pollex_entry_links reference unknown entries")

    def test_match_keys_align(self):
        # Every link's match_key must equal the linked entry's headword_search.
        bad = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_entry_links pel"
            " JOIN entry e ON pel.entry_id = e.id"
            " WHERE pel.match_key <> e.headword_search"
        ).fetchone()[0]
        self.assertEqual(bad, 0, f"{bad} pollex_entry_links have match_key ≠ entry.headword_search")

    def test_spans_multiple_sources(self):
        # Links should reach the major user-facing dictionaries, not just one.
        sources = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT e.source_id FROM pollex_entry_links pel"
            " JOIN entry e ON pel.entry_id = e.id"
        ).fetchall()}
        for s in ("te_aka", "williams"):
            self.assertIn(s, sources, f"pollex_entry_links never reaches {s}")


# ── 9. Source abbreviations ───────────────────────────────────────────────────

class TestSourceAbbreviations(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_coverage_by_source_dict(self):
        rows = self.conn.execute(
            "SELECT source_dict, COUNT(*) FROM source_abbreviations GROUP BY source_dict"
        ).fetchall()
        by_dict = {r[0]: r[1] for r in rows}
        self.assertIn("te_aka", by_dict)
        self.assertIn("williams", by_dict)
        self.assertIn("hepatakakupu", by_dict)
        self.assertGreaterEqual(by_dict["te_aka"], 80)
        self.assertGreaterEqual(by_dict["williams"], 5)
        self.assertGreaterEqual(by_dict["hepatakakupu"], 40)

    def test_load_source_abbrevs_te_aka(self):
        abbrevs = load_source_abbrevs("te_aka", DB_PATH)
        self.assertGreater(len(abbrevs), 0, "load_source_abbrevs('te_aka') returned empty")
        # All entries must have a full_name
        for abbrev, info in abbrevs.items():
            self.assertIn("full_name", info, f"te_aka abbrev {abbrev!r} missing full_name")
            self.assertTrue(info["full_name"], f"te_aka abbrev {abbrev!r} has empty full_name")

    def test_load_source_abbrevs_hepatakakupu(self):
        abbrevs = load_source_abbrevs("hepatakakupu", DB_PATH)
        self.assertGreater(len(abbrevs), 0)

    def test_expand_citations_uses_db_abbrevs(self):
        te_aka_abbrevs = load_source_abbrevs("te_aka", DB_PATH)
        # TTR is a known Te Aka abbreviation
        self.assertIn("TTR", te_aka_abbrevs, "TTR not in te_aka source_abbreviations")
        result = expand_citations("Ko te aho (TTR 1996:46).", te_aka_abbrevs)
        self.assertNotIn("(TTR", result)
        self.assertTrue(len(result) > len("Ko te aho (TTR 1996:46)."))

    def test_no_empty_full_names(self):
        n = self.conn.execute(
            "SELECT COUNT(*) FROM source_abbreviations WHERE full_name IS NULL OR full_name = ''"
        ).fetchone()[0]
        self.assertEqual(n, 0, f"{n} source_abbreviations have empty full_name")


# ── 10. Refresh tracking ──────────────────────────────────────────────────────

class TestRefreshTracking(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_te_aka_has_content_hash_column(self):
        cols = _cols(self.conn, "te_aka_entries")
        self.assertIn("content_hash", cols)
        self.assertIn("first_seen", cols)

    def test_paekupu_has_content_hash_column(self):
        cols = _cols(self.conn, "paekupu_entries")
        self.assertIn("content_hash", cols)
        self.assertIn("first_seen", cols)

    def test_te_aka_content_hash_is_hex(self):
        row = self.conn.execute(
            "SELECT content_hash FROM te_aka_entries WHERE content_hash IS NOT NULL LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row, "No te_aka entries have content_hash populated")
        h = row[0]
        self.assertEqual(len(h), 64, f"content_hash length {len(h)} != 64")
        int(h, 16)  # must be valid hex

    def test_data_refresh_runs_schema_ok(self):
        # Table must exist and be queryable (empty is fine — no refreshes run yet)
        n = _count(self.conn, "data_refresh_runs")
        self.assertGreaterEqual(n, 0)

    def test_data_refresh_log_schema_ok(self):
        n = _count(self.conn, "data_refresh_log")
        self.assertGreaterEqual(n, 0)


# ── 11. Performance ───────────────────────────────────────────────────────────

class TestPerformance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_headword_search_lookup_under_10ms(self):
        # Warm up
        self.conn.execute(
            "SELECT headword FROM williams_entries WHERE headword_search = 'aho'"
        ).fetchone()
        # Measure 50 iterations
        t0 = time.perf_counter()
        for _ in range(50):
            self.conn.execute(
                "SELECT headword FROM williams_entries WHERE headword_search = 'aho'"
            ).fetchone()
        elapsed_ms = (time.perf_counter() - t0) / 50 * 1000
        self.assertLess(elapsed_ms, 10, f"headword_search avg {elapsed_ms:.2f}ms > 10ms")

    def test_fts_query_under_100ms(self):
        t0 = time.perf_counter()
        self.conn.execute(
            "SELECT headword FROM williams_fts WHERE williams_fts MATCH 'aroha'"
        ).fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 100, f"FTS query took {elapsed_ms:.2f}ms > 100ms")

    def test_te_aka_headword_search_under_10ms(self):
        self.conn.execute(
            "SELECT headword FROM te_aka_entries WHERE headword_search = 'aroha'"
        ).fetchone()
        t0 = time.perf_counter()
        for _ in range(50):
            self.conn.execute(
                "SELECT headword FROM te_aka_entries WHERE headword_search = 'aroha'"
            ).fetchone()
        elapsed_ms = (time.perf_counter() - t0) / 50 * 1000
        self.assertLess(elapsed_ms, 10, f"te_aka headword_search avg {elapsed_ms:.2f}ms > 10ms")


# ── 12. POLLEX language reference ────────────────────────────────────────────

class TestPollexLanguages(unittest.TestCase):

    EXPECTED_SUBGROUPS = {
        "Tongic",
        "Eastern Polynesian",
        "Samoic-Outlier",
        "Polynesian Outlier",
        "Fijian",
        "Rotuman",
        "Other Oceanic",
    }

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_pollex_languages_table_exists(self):
        cols = _cols(self.conn, "pollex_languages")
        for col in ("language_slug", "language", "iso_code", "subgroup",
                    "region", "country_or_island_group", "notes"):
            self.assertIn(col, cols, f"pollex_languages missing column {col!r}")

    def test_pollex_languages_seed_complete(self):
        n = _count(self.conn, "pollex_languages")
        self.assertEqual(n, 67, f"pollex_languages has {n} rows, expected 67")

    def test_pollex_languages_all_subgroups_present(self):
        present = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT subgroup FROM pollex_languages"
        ).fetchall()}
        self.assertEqual(present, self.EXPECTED_SUBGROUPS)

    def test_pollex_languages_reflex_slugs_covered(self):
        unmatched = self.conn.execute(
            "SELECT COUNT(DISTINCT r.language_slug) FROM pollex_reflexes r"
            " LEFT JOIN pollex_languages l ON r.language_slug = l.language_slug"
            " WHERE l.language_slug IS NULL"
        ).fetchone()[0]
        self.assertEqual(unmatched, 0, f"{unmatched} reflex language_slugs have no pollex_languages entry")

    def test_pollex_languages_known_entries(self):
        row = self.conn.execute(
            "SELECT language, subgroup, iso_code FROM pollex_languages WHERE language_slug = 'maori'"
        ).fetchone()
        self.assertIsNotNone(row, "pollex_languages missing 'maori' entry")
        self.assertEqual(row[0], "New Zealand Maori")
        self.assertEqual(row[1], "Eastern Polynesian")
        self.assertEqual(row[2], "mri")

    def test_pollex_languages_subgroup_join_reflexes(self):
        tongan_reflexes = self.conn.execute(
            "SELECT COUNT(*) FROM pollex_reflexes r"
            " JOIN pollex_languages l ON r.language_slug = l.language_slug"
            " WHERE l.subgroup = 'Tongic'"
        ).fetchone()[0]
        self.assertGreater(tongan_reflexes, 0, "No Tongic reflexes found via join")


# ── 13. Cross-source duplicate candidates ─────────────────────────────────────

class TestCrossSourceCandidates(unittest.TestCase):

    VALID_STATUSES = {"unreviewed", "pending", "approved", "dismissed_by_ai", "dismissed"}

    @classmethod
    def setUpClass(cls):
        cls.conn = _open()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_cross_source_candidates_schema(self):
        cols = _cols(self.conn, "cross_source_candidates")
        for col in ("id", "headword_search", "source_a", "entry_id_a",
                    "source_b", "entry_id_b", "status", "ai_reasoning",
                    "detected_at", "reviewed_at", "review_notes"):
            self.assertIn(col, cols, f"cross_source_candidates missing column {col!r}")

    def test_cross_source_detection_runs_schema(self):
        cols = _cols(self.conn, "cross_source_detection_runs")
        for col in ("id", "run_at", "new_pairs", "skipped_existing", "notes"):
            self.assertIn(col, cols)

    def test_cross_source_candidates_populated(self):
        n = _count(self.conn, "cross_source_candidates")
        self.assertGreater(n, 10_000, f"Expected > 10,000 candidates, got {n}")

    def test_cross_source_all_statuses_valid(self):
        bad = self.conn.execute(
            "SELECT COUNT(*) FROM cross_source_candidates WHERE status NOT IN"
            " ('unreviewed','pending','approved','dismissed_by_ai','dismissed')"
        ).fetchone()[0]
        self.assertEqual(bad, 0, f"{bad} rows have invalid status")

    def test_cross_source_source_ordering(self):
        # source_a must always be the lexicographically smaller source
        bad = self.conn.execute(
            "SELECT COUNT(*) FROM cross_source_candidates WHERE source_a > source_b"
        ).fetchone()[0]
        self.assertEqual(bad, 0, f"{bad} pairs have source_a > source_b (ordering bug)")

    def test_cross_source_detection_run_recorded(self):
        n = _count(self.conn, "cross_source_detection_runs")
        self.assertGreater(n, 0, "No detection runs recorded")

    def test_cross_source_covers_multiple_source_pairs(self):
        pairs = self.conn.execute(
            "SELECT DISTINCT source_a, source_b FROM cross_source_candidates"
        ).fetchall()
        self.assertGreater(len(pairs), 3, "Expected candidates from multiple source combinations")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    assert DB_PATH.exists(), f"Database not found: {DB_PATH}\nRun: py scripts/00_init_db.py"
    unittest.main(verbosity=2)
