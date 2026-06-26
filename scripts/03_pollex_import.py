"""
Import POLLEX data into the SQLite database.

Phase 1 (always): pollex_entries from pollex_maori.json
Phase 2 (if pollex_all_reflexes.json exists): pollex_cognatesets + pollex_reflexes

Usage:
  python 03_pollex_import.py
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import normalise_sort_key, normalise_search_key

DB_PATH         = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
MAORI_JSON      = Path(__file__).parent.parent / "sources" / "pollex" / "parsed" / "pollex_maori.json"
ALL_REFLEXES_JSON = Path(__file__).parent.parent / "sources" / "pollex" / "parsed" / "pollex_all_reflexes.json"

POLLEX_BASE = "https://pollex.eva.mpg.de"

# "Reconstructs to CE: Central-Eastern Polynesian" → "CE" / "Central-Eastern Polynesian"
_LEVEL_RE = re.compile(r"Reconstructs to ([A-Z?]{2})(?:: (.+))?")

# POLLEX level pages show "XX - XX" for these — no full name is published on the site.
# Names inferred from reflex language distributions and Polynesian linguistics literature.
_UNDOCUMENTED_LEVEL_NAMES: dict[str, str] = {
    "CC": "Common Core Polynesian",
    "CK": "Cook Islands Maori",
    "FU": "Futunic",
    "LO": "Loans",
    "NO": "Nuclear Outlier",
    "RO": "Remote Oceanic",
    "TO": "Tongic",
    "TU": "Tuvaluan",
}


def _slug_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] if url else ""


def _level_from_reconstruction(reconstruction: str) -> tuple[str, str]:
    """Return (level_code, level_name) parsed from reconstruction text."""
    if not reconstruction:
        return "", ""
    m = _LEVEL_RE.search(reconstruction)
    if not m:
        return "", ""
    code = m.group(1)
    name = (m.group(2) or "").strip()
    if not name or name == code:
        name = _UNDOCUMENTED_LEVEL_NAMES.get(code, "")
    return code, name


# ── DDL ──────────────────────────────────────────────────────────────────────

_DROP_ENTRIES_SQL = """
    DROP TRIGGER IF EXISTS pollex_fts_ins;
    DROP TRIGGER IF EXISTS pollex_fts_upd;
    DROP TRIGGER IF EXISTS pollex_fts_del;
    DROP TABLE IF EXISTS pollex_fts;
    DROP INDEX IF EXISTS idx_pollex_search;
    DROP TABLE IF EXISTS pollex_entries;
"""

_CREATE_ENTRIES_SQL = """
    CREATE TABLE pollex_entries (
        id              INTEGER PRIMARY KEY,
        headword        TEXT NOT NULL,
        headword_sort   TEXT NOT NULL,
        headword_search TEXT NOT NULL,
        part_of_speech  TEXT,
        definition      TEXT,
        usage_examples  TEXT DEFAULT '[]',
        protoform       TEXT,
        protoform_desc  TEXT,
        maori_reflex    TEXT,
        maori_gloss     TEXT,
        source_citation TEXT,
        source_author   TEXT,
        cognateset_id   TEXT,
        pollex_url      TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        last_updated    TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_pollex_search ON pollex_entries(headword_search);

    CREATE VIRTUAL TABLE pollex_fts USING fts5(
        headword, definition, usage_examples,
        content='pollex_entries', content_rowid='id',
        tokenize='unicode61'
    );

    CREATE TRIGGER pollex_fts_ins AFTER INSERT ON pollex_entries BEGIN
        INSERT INTO pollex_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER pollex_fts_upd AFTER UPDATE ON pollex_entries BEGIN
        INSERT INTO pollex_fts(pollex_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        INSERT INTO pollex_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER pollex_fts_del AFTER DELETE ON pollex_entries BEGIN
        INSERT INTO pollex_fts(pollex_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
    END;
"""

_DROP_COGNATESETS_SQL = """
    DROP INDEX IF EXISTS idx_pollex_reflexes_lang;
    DROP INDEX IF EXISTS idx_pollex_reflexes_cs;
    DROP TABLE IF EXISTS pollex_reflexes;
    DROP INDEX IF EXISTS idx_pollex_cognatesets_level;
    DROP TABLE IF EXISTS pollex_cognatesets;
"""

_CREATE_COGNATESETS_SQL = """
    CREATE TABLE pollex_cognatesets (
        id             TEXT PRIMARY KEY,
        protoform_name TEXT NOT NULL,
        level          TEXT NOT NULL,
        level_name     TEXT,
        description    TEXT,
        reconstruction TEXT,
        notes          TEXT,
        pollex_url     TEXT
    );
    CREATE INDEX idx_pollex_cognatesets_level ON pollex_cognatesets(level);

    CREATE TABLE pollex_reflexes (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        cognateset_id  TEXT NOT NULL REFERENCES pollex_cognatesets(id),
        language       TEXT NOT NULL,
        language_slug  TEXT,
        reflex         TEXT,
        gloss          TEXT,
        source_code    TEXT,
        source_author  TEXT,
        flags          TEXT
    );
    CREATE INDEX idx_pollex_reflexes_cs   ON pollex_reflexes(cognateset_id);
    CREATE INDEX idx_pollex_reflexes_lang ON pollex_reflexes(language_slug);
"""

_INSERT_ENTRY_SQL = """
    INSERT INTO pollex_entries
        (headword, headword_sort, headword_search,
         part_of_speech, definition, usage_examples,
         protoform, protoform_desc, maori_reflex, maori_gloss,
         source_citation, source_author, cognateset_id, pollex_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_COGNATESET_SQL = """
    INSERT INTO pollex_cognatesets
        (id, protoform_name, level, level_name, description, reconstruction, notes, pollex_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_REFLEX_SQL = """
    INSERT INTO pollex_reflexes
        (cognateset_id, language, language_slug, reflex, gloss,
         source_code, source_author, flags)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── Import helpers ────────────────────────────────────────────────────────────

def import_entries(conn: sqlite3.Connection, maori_entries: list) -> int:
    conn.executescript(_DROP_ENTRIES_SQL)
    print("Dropped old pollex_entries tables/triggers")
    conn.executescript(_CREATE_ENTRIES_SQL)
    print("Recreated pollex_entries, pollex_fts, and triggers")

    rows = []
    for e in maori_entries:
        slug = _slug_from_url(e.get("pollex_url", ""))
        rows.append((
            e["maori_reflex"],
            normalise_sort_key(e["maori_reflex"]),
            normalise_search_key(e["maori_reflex"]),
            None,
            e.get("maori_gloss"),
            "[]",
            e.get("protoform"),
            e.get("protoform_desc"),
            e["maori_reflex"],
            e.get("maori_gloss"),
            e.get("source_citation"),
            e.get("source_author"),
            slug or None,
            e.get("pollex_url"),
        ))

    conn.executemany(_INSERT_ENTRY_SQL, rows)
    conn.execute("INSERT INTO pollex_fts(pollex_fts) VALUES ('rebuild')")
    return len(rows)


def import_cognatesets(
    conn: sqlite3.Connection,
    protoforms: list,
    slug_to_protoform: dict,
) -> tuple[int, int]:
    conn.executescript(_DROP_COGNATESETS_SQL)
    print("Dropped old pollex_cognatesets/pollex_reflexes tables")
    conn.executescript(_CREATE_COGNATESETS_SQL)
    print("Recreated pollex_cognatesets and pollex_reflexes")

    cs_rows = []
    reflex_rows = []

    for pf in protoforms:
        slug = pf["slug"]
        protoform_name = slug_to_protoform.get(slug, slug.upper())
        level, level_name = _level_from_reconstruction(pf.get("reconstruction") or "")

        cs_rows.append((
            slug,
            protoform_name,
            level,
            level_name if level_name and level_name != level else None,
            pf.get("description"),
            pf.get("reconstruction"),
            pf.get("notes"),
            f"{POLLEX_BASE}/entry/{slug}/",
        ))

        for r in pf.get("reflexes", []):
            reflex_rows.append((
                slug,
                r["language"],
                r.get("language_slug"),
                r.get("reflex"),
                r.get("gloss"),
                r.get("source_code"),
                r.get("source_author"),
                json.dumps(r.get("flags") or [], ensure_ascii=False),
            ))

    conn.executemany(_INSERT_COGNATESET_SQL, cs_rows)
    conn.executemany(_INSERT_REFLEX_SQL, reflex_rows)
    return len(cs_rows), len(reflex_rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    if not MAORI_JSON.exists():
        print(f"Error: {MAORI_JSON} not found. Run 03_pollex_scrape.py first.")
        sys.exit(1)

    maori_entries: list = json.loads(MAORI_JSON.read_text(encoding="utf-8"))
    print(f"Loaded {len(maori_entries):,} Māori entries from JSON")

    slug_to_protoform: dict[str, str] = {}
    for e in maori_entries:
        url = e.get("pollex_url", "")
        if url:
            slug = _slug_from_url(url)
            if slug and slug not in slug_to_protoform:
                slug_to_protoform[slug] = e["protoform"]

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        with conn:
            n_entries = import_entries(conn, maori_entries)
            print(f"Inserted {n_entries:,} pollex_entries")

            actual = conn.execute("SELECT COUNT(*) FROM pollex_entries").fetchone()[0]
            conn.execute(
                "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now') "
                "WHERE source_id = 'pollex'",
                (actual,),
            )
            print(f"source_metadata updated: {actual:,} entries")

            if ALL_REFLEXES_JSON.exists():
                protoforms: list = json.loads(ALL_REFLEXES_JSON.read_text(encoding="utf-8"))
                print(f"\nLoaded {len(protoforms):,} protoform entries from JSON")
                n_cs, n_reflexes = import_cognatesets(conn, protoforms, slug_to_protoform)
                print(f"Inserted {n_cs:,} cognatesets, {n_reflexes:,} reflexes")

                conn.execute(
                    "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now') "
                    "WHERE source_id = 'pollex_cognatesets'",
                    (n_cs,),
                )
                print(f"source_metadata updated: {n_cs:,} cognatesets")
            else:
                print(
                    f"\nSkipping cognatesets/reflexes "
                    f"({ALL_REFLEXES_JSON.name} not found — "
                    f"run 03_pollex_scrape.py --entries to fetch)"
                )

        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()

    finally:
        conn.close()

    print("\nImport complete.")


if __name__ == "__main__":
    main()
