"""Session 1 verification: schema, FTS, triggers, utils, and source_metadata."""

import json
import sqlite3
import sys
from pathlib import Path

# Allow imports from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from utils import normalise_search_key, normalise_sort_key

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"

CONTENT_TABLES = [
    "williams_entries",
    "papakupu_entries",
    "pollex_entries",
    "personal_lexicon",
    "te_aka_entries",
    "hepatakakupu_entries",
    "paekupu_entries",
]

FTS_TABLES = [t.replace("_entries", "_fts").replace("personal_lexicon", "personal_fts")
              for t in CONTENT_TABLES]

REQUIRED_COLUMNS = {
    "williams_entries":      ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "sense_number", "cross_refs", "page_number", "source_section",
                               "created_at", "last_updated"],
    "papakupu_entries":      ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "variant_forms", "variant_search_keys", "source_code",
                               "loan_marker", "see_also", "pdf_page",
                               "created_at", "last_updated"],
    "pollex_entries":        ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "protoform", "protoform_desc", "maori_reflex", "maori_gloss",
                               "source_citation", "pollex_url", "created_at", "last_updated"],
    "personal_lexicon":      ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "tags", "pronunciation", "source_note", "is_private",
                               "created_at", "last_updated"],
    "te_aka_entries":        ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "word_id", "definition_en", "definition_mi", "audio_url",
                               "created_at", "last_updated"],
    "hepatakakupu_entries":  ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "word_id", "definition_mi", "created_at", "last_updated"],
    "paekupu_entries":       ["id", "headword", "headword_sort", "headword_search",
                               "part_of_speech", "definition", "usage_examples",
                               "headword_en", "subject_area", "created_at", "last_updated"],
}

SOURCE_IDS = {"williams", "papakupu", "pollex", "te_aka", "hepatakakupu", "paekupu", "personal"}


def get_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')"
    ).fetchall()
    return {r[0] for r in rows}


def get_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


# ── Normalisation tests ───────────────────────────────────────────────────────

def test_normalise_sort_key():
    assert normalise_sort_key("āho") == "aho",       "macron not stripped"
    assert normalise_sort_key("Āho") == "aho",       "uppercase not lowercased"
    assert normalise_sort_key("whānau") == "whanau", "ā in word not stripped"
    assert normalise_sort_key("aaho") == "aaho",     "double vowel must NOT be collapsed by sort key"
    print("  normalise_sort_key OK")


def test_normalise_search_key():
    assert normalise_search_key("āho")    == "aho",    "macron form"
    assert normalise_search_key("aaho")   == "aho",    "double-vowel form"
    assert normalise_search_key("aho")    == "aho",    "plain form"
    assert normalise_search_key("whānau") == "whanau", "whānau macron"
    assert normalise_search_key("whaanau")== "whanau", "whaanau double-vowel"
    assert normalise_search_key("whanau") == "whanau", "whanau plain"
    assert normalise_search_key("kaokao") == "kaokao", "ao must NOT collapse (different vowels)"
    assert normalise_search_key("āpiha")  == "apiha",  "āpiha"
    assert normalise_search_key("aapiha") == "apiha",  "aapiha"
    print("  normalise_search_key OK")


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_tables_exist(conn: sqlite3.Connection):
    existing = get_table_names(conn)
    for table in CONTENT_TABLES:
        assert table in existing, f"Missing table: {table}"
    assert "source_metadata" in existing, "Missing table: source_metadata"
    print("  content tables exist OK")


def test_fts_tables_exist(conn: sqlite3.Connection):
    existing = get_table_names(conn)
    fts_names = [
        "williams_fts", "papakupu_fts", "pollex_fts", "personal_fts",
        "te_aka_fts", "hepatakakupu_fts", "paekupu_fts",
    ]
    for name in fts_names:
        assert name in existing, f"Missing FTS table: {name}"
    print("  FTS virtual tables exist OK")


def test_columns(conn: sqlite3.Connection):
    for table, required in REQUIRED_COLUMNS.items():
        actual = get_column_names(conn, table)
        for col in required:
            assert col in actual, f"{table} missing column: {col}"
    print("  column definitions OK")


def test_source_metadata(conn: sqlite3.Connection):
    rows = conn.execute("SELECT source_id FROM source_metadata").fetchall()
    present = {r[0] for r in rows}
    assert present == SOURCE_IDS, f"source_metadata mismatch: {present} != {SOURCE_IDS}"
    print("  source_metadata seeded OK")


# ── Dummy row + FTS trigger tests ─────────────────────────────────────────────

def test_williams_insert_fts(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO williams_entries
            (headword, headword_sort, headword_search, definition, usage_examples)
        VALUES ('āho', 'aho', 'aho', 'A line, cord.', '["Ko te āho o te hao."]')
    """)
    row = conn.execute(
        "SELECT headword FROM williams_fts WHERE williams_fts MATCH 'cord'"
    ).fetchone()
    assert row is not None, "FTS trigger did not index williams insert"
    assert row[0] == "āho"
    conn.execute("DELETE FROM williams_entries WHERE headword = 'āho'")
    print("  williams insert -> FTS trigger OK")


def test_papakupu_insert_fts(conn: sqlite3.Connection):
    variant_forms = json.dumps(["aaho", "aho"], ensure_ascii=False)
    variant_search_keys = json.dumps(["aho"], ensure_ascii=False)
    conn.execute("""
        INSERT INTO papakupu_entries
            (headword, headword_sort, headword_search, definition,
             usage_examples, variant_forms, variant_search_keys)
        VALUES ('āho', 'aho', 'aho', 'He aho, he taura.',
                '[]', ?, ?)
    """, (variant_forms, variant_search_keys))
    row = conn.execute(
        "SELECT headword FROM papakupu_fts WHERE papakupu_fts MATCH 'taura'"
    ).fetchone()
    assert row is not None, "FTS trigger did not index papakupu insert"
    conn.execute("DELETE FROM papakupu_entries WHERE headword = 'āho'")
    print("  papakupu insert -> FTS trigger OK")


def test_pollex_insert_fts(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO pollex_entries
            (headword, headword_sort, headword_search, definition, usage_examples, protoform)
        VALUES ('aho', 'aho', 'aho', 'Fishing line.', '[]', 'OC.ASO')
    """)
    row = conn.execute(
        "SELECT headword FROM pollex_fts WHERE pollex_fts MATCH 'Fishing'"
    ).fetchone()
    assert row is not None, "FTS trigger did not index pollex insert"
    conn.execute("DELETE FROM pollex_entries WHERE headword = 'aho'")
    print("  pollex insert -> FTS trigger OK")


def test_personal_insert_fts(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO personal_lexicon
            (headword, headword_sort, headword_search, definition, usage_examples, tags)
        VALUES ('aroha', 'aroha', 'aroha', 'Love, compassion.', '[]', '["emotion"]')
    """)
    row = conn.execute(
        "SELECT headword FROM personal_fts WHERE personal_fts MATCH 'compassion'"
    ).fetchone()
    assert row is not None, "FTS trigger did not index personal_lexicon insert"
    conn.execute("DELETE FROM personal_lexicon WHERE headword = 'aroha'")
    print("  personal_lexicon insert -> FTS trigger OK")


def test_stub_tables_insert(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO te_aka_entries
            (headword, headword_sort, headword_search, definition, usage_examples, word_id)
        VALUES ('aroha', 'aroha', 'aroha', 'Love.', '[]', 1)
    """)
    conn.execute("DELETE FROM te_aka_entries WHERE headword = 'aroha'")

    conn.execute("""
        INSERT INTO hepatakakupu_entries
            (headword, headword_sort, headword_search, definition, usage_examples, word_id)
        VALUES ('aroha', 'aroha', 'aroha', 'He aroha.', '[]', 1)
    """)
    conn.execute("DELETE FROM hepatakakupu_entries WHERE headword = 'aroha'")

    conn.execute("""
        INSERT INTO paekupu_entries
            (headword, headword_sort, headword_search, definition, usage_examples, subject_area)
        VALUES ('pāngarau', 'pangarau', 'pangarau', 'Mathematics.', '[]', 'Pāngarau')
    """)
    conn.execute("DELETE FROM paekupu_entries WHERE headword = 'pāngarau'")
    print("  stub table inserts OK")


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    assert DB_PATH.exists(), f"Database not found: {DB_PATH}\nRun: py scripts/00_init_db.py"

    print("Normalisation tests:")
    test_normalise_sort_key()
    test_normalise_search_key()

    print("Schema tests:")
    with sqlite3.connect(DB_PATH) as conn:
        test_tables_exist(conn)
        test_fts_tables_exist(conn)
        test_columns(conn)
        test_source_metadata(conn)

    print("FTS trigger tests:")
    with sqlite3.connect(DB_PATH) as conn:
        test_williams_insert_fts(conn)
        test_papakupu_insert_fts(conn)
        test_pollex_insert_fts(conn)
        test_personal_insert_fts(conn)
        test_stub_tables_insert(conn)

    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
