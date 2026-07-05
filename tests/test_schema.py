"""Session 1 verification: schema, FTS, triggers, utils, and source_metadata."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Allow imports from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from utils import normalise_search_key, normalise_sort_key

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"


@pytest.fixture
def conn():
    """DB handle for the test_*(conn) functions when collected by pytest.

    The script entry point (main(), run via `py tests/test_schema.py`) passes its
    own connection explicitly and never triggers this fixture — so both run paths
    work. Changes made by the FTS-trigger tests are self-deleted and never
    committed here, so the connection rolls back on close.
    """
    c = sqlite3.connect(DB_PATH)
    yield c
    c.close()

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
                               "word_id", "senses", "audio_url",
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
    # SOURCE_IDS are the seven word-list sources that must always be present; the
    # etymology/comparative sources (acd, lpo, tregear, abvd, walworth, …) are
    # added by later sessions and allowed on top, so assert a subset not equality.
    missing = SOURCE_IDS - present
    assert not missing, f"source_metadata missing required word-list sources: {missing}"
    print("  source_metadata seeded OK")


# ── Dummy row + FTS trigger tests ─────────────────────────────────────────────

def test_williams_insert_fts(conn: sqlite3.Connection):
    # Use a headword ('xqzstub') that cannot exist in the real corpus so the test
    # is safe against the now-populated DB in both run paths (real rows also match
    # 'cord', and the script path commits — deleting by a real headword would be
    # data loss). Assert the stub appears among the FTS hits, not that it is first.
    conn.execute("""
        INSERT INTO williams_entries
            (headword, headword_sort, headword_search, definition, usage_examples)
        VALUES ('xqzstub', 'xqzstub', 'xqzstub', 'A line, cord.', '["Ko te āho o te hao."]')
    """)
    hits = {r[0] for r in conn.execute(
        "SELECT headword FROM williams_fts WHERE williams_fts MATCH 'cord'"
    ).fetchall()}
    assert "xqzstub" in hits, "FTS trigger did not index williams insert"
    conn.execute("DELETE FROM williams_entries WHERE headword = 'xqzstub'")
    print("  williams insert -> FTS trigger OK")


def test_papakupu_insert_fts(conn: sqlite3.Connection):
    variant_forms = json.dumps(["aaho", "aho"], ensure_ascii=False)
    variant_search_keys = json.dumps(["aho"], ensure_ascii=False)
    conn.execute("""
        INSERT INTO papakupu_entries
            (headword, headword_sort, headword_search, definition,
             usage_examples, variant_forms, variant_search_keys)
        VALUES ('xqzstub', 'xqzstub', 'xqzstub', 'He aho, he taura.',
                '[]', ?, ?)
    """, (variant_forms, variant_search_keys))
    hits = {r[0] for r in conn.execute(
        "SELECT headword FROM papakupu_fts WHERE papakupu_fts MATCH 'taura'"
    ).fetchall()}
    assert "xqzstub" in hits, "FTS trigger did not index papakupu insert"
    conn.execute("DELETE FROM papakupu_entries WHERE headword = 'xqzstub'")
    print("  papakupu insert -> FTS trigger OK")


def test_pollex_insert_fts(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO pollex_entries
            (headword, headword_sort, headword_search, definition, usage_examples, protoform)
        VALUES ('xqzstub', 'xqzstub', 'xqzstub', 'Fishing line.', '[]', 'OC.ASO')
    """)
    hits = {r[0] for r in conn.execute(
        "SELECT headword FROM pollex_fts WHERE pollex_fts MATCH 'Fishing'"
    ).fetchall()}
    assert "xqzstub" in hits, "FTS trigger did not index pollex insert"
    conn.execute("DELETE FROM pollex_entries WHERE headword = 'xqzstub'")
    print("  pollex insert -> FTS trigger OK")


def test_personal_insert_fts(conn: sqlite3.Connection):
    conn.execute("""
        INSERT INTO personal_lexicon
            (headword, headword_sort, headword_search, definition, usage_examples, tags)
        VALUES ('xqzstub', 'xqzstub', 'xqzstub', 'Love, compassion.', '[]', '["emotion"]')
    """)
    hits = {r[0] for r in conn.execute(
        "SELECT headword FROM personal_fts WHERE personal_fts MATCH 'compassion'"
    ).fetchall()}
    assert "xqzstub" in hits, "FTS trigger did not index personal_lexicon insert"
    conn.execute("DELETE FROM personal_lexicon WHERE headword = 'xqzstub'")
    print("  personal_lexicon insert -> FTS trigger OK")


def test_stub_tables_insert(conn: sqlite3.Connection):
    # Sentinel word_ids + a corpus-impossible headword so the inserts don't collide
    # with real rows (te_aka/hepatakakupu word_id is UNIQUE) and the deletes can't
    # touch real data in the committing script path.
    conn.execute("""
        INSERT INTO te_aka_entries
            (headword, headword_sort, headword_search, definition, usage_examples, word_id)
        VALUES ('xqzstub', 'xqzstub', 'xqzstub', 'Love.', '[]', 900000001)
    """)
    conn.execute("DELETE FROM te_aka_entries WHERE word_id = 900000001")

    conn.execute("""
        INSERT INTO hepatakakupu_entries
            (headword, headword_sort, headword_search, definition, usage_examples, word_id)
        VALUES ('xqzstub', 'xqzstub', 'xqzstub', 'He aroha.', '[]', 900000002)
    """)
    conn.execute("DELETE FROM hepatakakupu_entries WHERE word_id = 900000002")

    conn.execute("""
        INSERT INTO paekupu_entries
            (slug, headword, headword_sort, headword_search, definition, usage_examples, subject_area)
        VALUES ('xqzstub-slug', 'xqzstub', 'xqzstub', 'xqzstub', 'Mathematics.', '[]', 'Pāngarau')
    """)
    conn.execute("DELETE FROM paekupu_entries WHERE slug = 'xqzstub-slug'")
    print("  stub table inserts OK")


# ── Runner ────────────────────────────────────────────────────────────────────

def test_pos_columns_exist(conn: sqlite3.Connection):
    """Test that part_of_speech columns exist in sense and entry tables."""
    sense_cols = {r[1] for r in conn.execute("PRAGMA table_info(sense)")}
    entry_cols = {r[1] for r in conn.execute("PRAGMA table_info(entry)")}
    assert "part_of_speech" in sense_cols
    assert "part_of_speech_en" in entry_cols
    assert "part_of_speech_mi" in entry_cols
    print("  POS columns exist OK")


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
        test_pos_columns_exist(conn)

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
