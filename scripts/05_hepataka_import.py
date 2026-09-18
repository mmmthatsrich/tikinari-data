"""
Import He Pataka Kupu entries from JSON into staging_dictionary.db.

Drops and recreates hepatakakupu_entries and its FTS table so the final
schema (with sense_number, synonyms, semantic_domain) replaces the stub.
Bulk-inserts all records, rebuilds FTS, updates source_metadata.

Usage:
  py 05_hepataka_import.py
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import normalise_sort_key, normalise_search_key, load_source_abbrevs, expand_citations

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH     = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH   = Path(__file__).parent.parent / "sources" / "hepataka" / "parsed" / "hepataka_entries.json"


_DROP_SQL = """
    DROP TRIGGER IF EXISTS hepatakakupu_fts_ins;
    DROP TRIGGER IF EXISTS hepatakakupu_fts_upd;
    DROP TRIGGER IF EXISTS hepatakakupu_fts_del;
    DROP TABLE IF EXISTS hepatakakupu_fts;
    DROP INDEX IF EXISTS idx_hepatakakupu_search;
    DROP INDEX IF EXISTS idx_hepatakakupu_word_id;
    DROP TABLE IF EXISTS hepatakakupu_entries;
"""

_CREATE_SQL = """
    CREATE TABLE hepatakakupu_entries (
        id               INTEGER PRIMARY KEY,   -- sense div id from HTML
        word_id          INTEGER NOT NULL,       -- numeric URL id (file id)
        headword         TEXT NOT NULL,
        headword_sort    TEXT NOT NULL,
        headword_search  TEXT NOT NULL,
        part_of_speech   TEXT,
        definition       TEXT,                   -- Maori description
        usage_examples   TEXT DEFAULT '[]',      -- JSON array
        sense_number     INTEGER,
        synonyms         TEXT DEFAULT '[]',      -- JSON array
        synonym_senses   TEXT DEFAULT '[]',      -- JSON array, parallel to synonyms
        master_word_id   INTEGER,                -- word holding this sense's master definition
        master_sense     INTEGER,                -- which sense of that word
        semantic_domain  TEXT,
        suffixes         TEXT DEFAULT '[]',      -- JSON array of '-tia' tokens
        definition_mi    TEXT,                   -- unused (no English gloss)
        created_at       TEXT DEFAULT (datetime('now')),
        last_updated     TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_hepatakakupu_search  ON hepatakakupu_entries(headword_search);
    CREATE INDEX idx_hepatakakupu_word_id ON hepatakakupu_entries(word_id);
    CREATE INDEX idx_hepatakakupu_master ON hepatakakupu_entries(master_word_id, master_sense);

    CREATE VIRTUAL TABLE hepatakakupu_fts USING fts5(
        headword, definition, usage_examples,
        content='hepatakakupu_entries', content_rowid='id',
        tokenize='unicode61'
    );

    CREATE TRIGGER hepatakakupu_fts_ins AFTER INSERT ON hepatakakupu_entries BEGIN
        INSERT INTO hepatakakupu_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER hepatakakupu_fts_upd AFTER UPDATE ON hepatakakupu_entries BEGIN
        INSERT INTO hepatakakupu_fts(hepatakakupu_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        INSERT INTO hepatakakupu_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER hepatakakupu_fts_del AFTER DELETE ON hepatakakupu_entries BEGIN
        INSERT INTO hepatakakupu_fts(hepatakakupu_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
    END;
"""

_INSERT_SQL = """
    INSERT INTO hepatakakupu_entries
        (id, word_id, headword, headword_sort, headword_search,
         part_of_speech, definition, usage_examples,
         sense_number, synonyms, synonym_senses,
         master_word_id, master_sense, semantic_domain, suffixes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def main() -> None:
    if not JSON_PATH.exists():
        print(f"Error: {JSON_PATH} not found. Run 05_hepataka_parse.py first.")
        sys.exit(1)

    records: list[dict] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(records):,} records from JSON")

    # Merge te_aka and hepatakakupu abbreviations; HPK-specific codes override shared ones.
    abbrevs = {**load_source_abbrevs("te_aka"), **load_source_abbrevs("hepatakakupu")}
    print(f"Loaded {len(abbrevs)} source abbreviations for expansion")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        with conn:
            conn.executescript(_DROP_SQL)
            print("Dropped old hepatakakupu tables/triggers")

            conn.executescript(_CREATE_SQL)
            print("Recreated hepatakakupu_entries, hepatakakupu_fts, and triggers")

            rows = []
            for r in records:
                hw = r["headword"]
                rows.append((
                    r["id"],
                    r["word_id"],
                    hw,
                    normalise_sort_key(hw),
                    normalise_search_key(hw),
                    r.get("part_of_speech"),
                    r.get("definition"),
                    json.dumps(
                        [expand_citations(ex, abbrevs) for ex in (r.get("usage_examples") or [])],
                        ensure_ascii=False,
                    ),
                    r.get("sense_number"),
                    json.dumps(r.get("synonyms") or [], ensure_ascii=False),
                    json.dumps(r.get("synonym_senses") or [], ensure_ascii=False),
                    r.get("master_word_id"),
                    r.get("master_sense"),
                    r.get("semantic_domain"),
                    json.dumps(r.get("suffixes") or [], ensure_ascii=False),
                ))

            conn.executemany(_INSERT_SQL, rows)
            print(f"Inserted {len(rows):,} rows")

            conn.execute("INSERT INTO hepatakakupu_fts(hepatakakupu_fts) VALUES ('rebuild')")
            print("FTS index rebuilt")

            actual = conn.execute("SELECT COUNT(*) FROM hepatakakupu_entries").fetchone()[0]
            conn.execute(
                "UPDATE source_metadata "
                "SET entry_count = ?, last_updated = datetime('now') "
                "WHERE source_id = 'hepatakakupu'",
                (actual,),
            )
            print(f"source_metadata updated: {actual:,} entries")

        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()

    finally:
        conn.close()

    print("\nImport complete.")


if __name__ == "__main__":
    main()
