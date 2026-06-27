"""
Import te_aka_entries.json into the SQLite database.

Default mode (first import):
  Drops and recreates the te_aka_entries table (and FTS) so the correct
  schema is always in place, then bulk-inserts all entries.  content_hash
  and first_seen are set on every row.  No change log is written.

Refresh mode (--refresh):
  Keeps existing rows.  Diffs new JSON against the DB by word_id, using
  content_hash to detect changes.  Inserts new entries, updates modified
  entries, soft-deletes (actually hard-deletes) removed entries.  All
  changes are logged in data_refresh_log; a summary row is written to
  data_refresh_runs.

Usage:
  py 04_te_aka_import.py             # full replace (initial load)
  py 04_te_aka_import.py --refresh   # incremental diff
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import normalise_sort_key, normalise_search_key, compute_content_hash, \
    load_source_abbrevs, expand_citations

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH   = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH = Path(__file__).parent.parent / "sources" / "te_aka" / "parsed" / "te_aka_entries.json"

# Fields that constitute "material" content — changes here are tracked.
# Excludes: id, word_id, headword_sort, headword_search, audio_url,
#           content_hash, first_seen, created_at, last_updated.
MATERIAL_FIELDS = (
    "headword", "part_of_speech", "definition", "senses",
    "usage_examples", "synonyms", "source_citations", "filters",
)

# ── DDL ──────────────────────────────────────────────────────────────────────

_DROP_SQL = """
    DROP TRIGGER IF EXISTS te_aka_fts_ins;
    DROP TRIGGER IF EXISTS te_aka_fts_upd;
    DROP TRIGGER IF EXISTS te_aka_fts_del;
    DROP TABLE IF EXISTS te_aka_fts;
    DROP INDEX IF EXISTS idx_te_aka_word_id;
    DROP INDEX IF EXISTS idx_te_aka_search;
    DROP TABLE IF EXISTS te_aka_entries;
"""

_CREATE_SQL = """
    CREATE TABLE te_aka_entries (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        word_id          INTEGER NOT NULL,
        headword         TEXT NOT NULL,
        headword_sort    TEXT NOT NULL,
        headword_search  TEXT NOT NULL,
        part_of_speech   TEXT,
        definition       TEXT,
        senses           TEXT DEFAULT '[]',
        usage_examples   TEXT DEFAULT '[]',
        audio_url        TEXT,
        synonyms         TEXT DEFAULT '[]',
        source_citations TEXT DEFAULT '[]',
        filters          TEXT DEFAULT '[]',
        content_hash     TEXT,
        first_seen       TEXT,
        created_at       TEXT DEFAULT (datetime('now')),
        last_updated     TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_te_aka_word_id ON te_aka_entries(word_id);
    CREATE INDEX idx_te_aka_search  ON te_aka_entries(headword_search);

    CREATE VIRTUAL TABLE te_aka_fts USING fts5(
        headword, definition, usage_examples,
        content='te_aka_entries', content_rowid='id',
        tokenize='unicode61'
    );

    CREATE TRIGGER te_aka_fts_ins AFTER INSERT ON te_aka_entries BEGIN
        INSERT INTO te_aka_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER te_aka_fts_upd AFTER UPDATE ON te_aka_entries BEGIN
        INSERT INTO te_aka_fts(te_aka_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        INSERT INTO te_aka_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER te_aka_fts_del AFTER DELETE ON te_aka_entries BEGIN
        INSERT INTO te_aka_fts(te_aka_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
    END;
"""

_INSERT_SQL = """
    INSERT INTO te_aka_entries
        (word_id, headword, headword_sort, headword_search,
         part_of_speech, definition, senses, usage_examples,
         audio_url, synonyms, source_citations, filters,
         content_hash, first_seen)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialise(v) -> str:
    """Serialise a value to its JSON string form for storage."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v or ""


def _expand_entry(entry: dict, abbrevs: dict) -> dict:
    """Return a copy of entry with source abbreviations expanded in text fields."""
    out = entry.copy()
    out["usage_examples"] = [
        expand_citations(ex, abbrevs) for ex in (entry.get("usage_examples") or [])
    ]
    out["source_citations"] = [
        expand_citations(c, abbrevs) for c in (entry.get("source_citations") or [])
    ]
    # Expand abbreviations inside each sense's examples/citations too, so the
    # per-sense rows match the entry-level aggregates.
    senses = []
    for s in (entry.get("senses") or []):
        s = s.copy()
        s["examples"] = [expand_citations(ex, abbrevs) for ex in (s.get("examples") or [])]
        s["citations"] = [expand_citations(c, abbrevs) for c in (s.get("citations") or [])]
        senses.append(s)
    out["senses"] = senses
    return out


def _build_material(entry: dict) -> dict:
    """Extract material fields from a parsed entry dict."""
    return {
        "headword":        entry.get("headword") or "",
        "part_of_speech":  entry.get("part_of_speech") or "",
        "definition":      entry.get("definition") or "",
        "senses":          entry.get("senses") or [],
        "usage_examples":  entry.get("usage_examples") or [],
        "synonyms":        entry.get("synonyms") or [],
        "source_citations": entry.get("source_citations") or [],
        "filters":         entry.get("filters") or [],
    }


def _build_row(entry: dict, now: str) -> tuple:
    m = _build_material(entry)
    return (
        entry["word_id"],
        entry["headword"],
        normalise_sort_key(entry["headword"]),
        normalise_search_key(entry["headword"]),
        entry.get("part_of_speech"),
        entry.get("definition"),
        json.dumps(entry.get("senses") or [], ensure_ascii=False),
        json.dumps(entry.get("usage_examples") or [], ensure_ascii=False),
        entry.get("audio_url"),
        json.dumps(entry.get("synonyms") or [], ensure_ascii=False),
        json.dumps(entry.get("source_citations") or [], ensure_ascii=False),
        json.dumps(entry.get("filters") or [], ensure_ascii=False),
        compute_content_hash(m),
        now,
    )


# ── Full replace (initial import) ─────────────────────────────────────────────

def full_import(conn: sqlite3.Connection, entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    abbrevs = load_source_abbrevs("te_aka")

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(_DROP_SQL)
    print("Dropped old te_aka tables/triggers")

    conn.executescript(_CREATE_SQL)
    print("Recreated te_aka_entries, te_aka_fts, and triggers")

    rows = [_build_row(_expand_entry(e, abbrevs), now) for e in entries]
    conn.executemany(_INSERT_SQL, rows)
    print(f"Inserted {len(rows):,} rows")

    conn.execute("INSERT INTO te_aka_fts(te_aka_fts) VALUES ('rebuild')")
    print("FTS rebuilt")

    actual = conn.execute("SELECT COUNT(*) FROM te_aka_entries").fetchone()[0]
    conn.execute(
        "UPDATE source_metadata SET entry_count=?, last_updated=datetime('now') "
        "WHERE source_id='te_aka'",
        (actual,),
    )
    conn.execute("PRAGMA foreign_keys = ON")
    print(f"source_metadata updated: {actual:,} entries")


# ── Refresh (incremental diff) ────────────────────────────────────────────────

def _material_from_db_te_aka(db: dict) -> dict:
    """Rebuild the material dict from stored DB field strings (for hash backfill)."""
    return {
        "headword":        db.get("headword") or "",
        "part_of_speech":  db.get("part_of_speech") or "",
        "definition":      db.get("definition") or "",
        "senses":          json.loads(db.get("senses") or "[]"),
        "usage_examples":  json.loads(db.get("usage_examples") or "[]"),
        "synonyms":        json.loads(db.get("synonyms") or "[]"),
        "source_citations": json.loads(db.get("source_citations") or "[]"),
        "filters":         json.loads(db.get("filters") or "[]"),
    }


def refresh_import(conn: sqlite3.Connection, entries: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    abbrevs = load_source_abbrevs("te_aka")
    entries = [_expand_entry(e, abbrevs) for e in entries]

    # Load existing DB state keyed by word_id
    existing: dict[int, dict] = {}
    for row in conn.execute(
        "SELECT word_id, headword, content_hash, first_seen, "
        "part_of_speech, definition, senses, usage_examples, synonyms, source_citations, filters "
        "FROM te_aka_entries"
    ):
        existing[row[0]] = {
            "headword": row[1], "content_hash": row[2], "first_seen": row[3],
            "part_of_speech": row[4], "definition": row[5], "senses": row[6],
            "usage_examples": row[7], "synonyms": row[8],
            "source_citations": row[9], "filters": row[10],
        }

    # Backfill content_hash for rows imported before refresh tracking was added
    backfill: list[tuple] = []
    for word_id, db in existing.items():
        if db["content_hash"] is None:
            h = compute_content_hash(_material_from_db_te_aka(db))
            db["content_hash"] = h
            backfill.append((h, word_id))
    if backfill:
        conn.executemany("UPDATE te_aka_entries SET content_hash=? WHERE word_id=?", backfill)
        print(f"  Backfilled content_hash for {len(backfill):,} existing rows")

    # Build incoming keyed by word_id
    incoming: dict[int, dict] = {}
    for e in entries:
        incoming[e["word_id"]] = e

    new_keys     = set(incoming) - set(existing)
    deleted_keys = set(existing) - set(incoming)
    common_keys  = set(incoming) & set(existing)

    # Identify modified entries
    modified: list[tuple[int, dict, list, dict, dict]] = []  # (key, entry, changed_fields, old_vals, new_vals)
    unchanged_count = 0
    for k in common_keys:
        e = incoming[k]
        new_hash = compute_content_hash(_build_material(e))
        if new_hash == existing[k]["content_hash"]:
            unchanged_count += 1
            continue
        # Identify which fields changed
        old_db = existing[k]
        changed = []
        old_vals: dict = {}
        new_vals: dict = {}
        field_map = {
            "headword":        (old_db["headword"],        e.get("headword") or ""),
            "part_of_speech":  (old_db["part_of_speech"],  e.get("part_of_speech") or ""),
            "definition":      (old_db["definition"],       e.get("definition") or ""),
            "senses":          (old_db["senses"],           json.dumps(e.get("senses") or [], ensure_ascii=False)),
            "usage_examples":  (old_db["usage_examples"],   json.dumps(e.get("usage_examples") or [], ensure_ascii=False)),
            "synonyms":        (old_db["synonyms"],          json.dumps(e.get("synonyms") or [], ensure_ascii=False)),
            "source_citations":(old_db["source_citations"],  json.dumps(e.get("source_citations") or [], ensure_ascii=False)),
            "filters":         (old_db["filters"],           json.dumps(e.get("filters") or [], ensure_ascii=False)),
        }
        for field, (old_v, new_v) in field_map.items():
            if (old_v or "") != (new_v or ""):
                changed.append(field)
                old_vals[field] = old_v
                new_vals[field] = new_v
        if changed:
            modified.append((k, e, changed, old_vals, new_vals))

    print(f"  new: {len(new_keys)}, modified: {len(modified)}, "
          f"deleted: {len(deleted_keys)}, unchanged: {unchanged_count}")

    # Create a refresh run record
    run_id = conn.execute(
        "INSERT INTO data_refresh_runs "
        "(source_dict, new_count, modified_count, deleted_count, unchanged_count, total_scraped) "
        "VALUES ('te_aka', ?, ?, ?, ?, ?)",
        (len(new_keys), len(modified), len(deleted_keys), unchanged_count, len(entries)),
    ).lastrowid

    log_rows: list[tuple] = []

    # INSERT new entries
    for k in new_keys:
        e = incoming[k]
        first_seen = existing.get(k, {}).get("first_seen") or now
        conn.execute(_INSERT_SQL, _build_row(e, first_seen))
        log_rows.append((run_id, "te_aka", str(k), e.get("headword"), "new", None, None, None))

    # UPDATE modified entries
    for k, e, changed, old_vals, new_vals in modified:
        new_hash = compute_content_hash(_build_material(e))
        conn.execute(
            "UPDATE te_aka_entries SET "
            "headword=?, headword_sort=?, headword_search=?, part_of_speech=?, "
            "definition=?, senses=?, usage_examples=?, audio_url=?, synonyms=?, "
            "source_citations=?, filters=?, content_hash=?, last_updated=datetime('now') "
            "WHERE word_id=?",
            (
                e["headword"],
                normalise_sort_key(e["headword"]),
                normalise_search_key(e["headword"]),
                e.get("part_of_speech"),
                e.get("definition"),
                json.dumps(e.get("senses") or [], ensure_ascii=False),
                json.dumps(e.get("usage_examples") or [], ensure_ascii=False),
                e.get("audio_url"),
                json.dumps(e.get("synonyms") or [], ensure_ascii=False),
                json.dumps(e.get("source_citations") or [], ensure_ascii=False),
                json.dumps(e.get("filters") or [], ensure_ascii=False),
                new_hash,
                k,
            ),
        )
        log_rows.append((
            run_id, "te_aka", str(k), e.get("headword"), "modified",
            json.dumps(changed, ensure_ascii=False),
            json.dumps(old_vals, ensure_ascii=False),
            json.dumps(new_vals, ensure_ascii=False),
        ))

    # DELETE removed entries (log old material snapshot first)
    for k in deleted_keys:
        old = existing[k]
        old_snapshot = {
            f: old.get(f) for f in
            ("headword", "part_of_speech", "definition", "usage_examples",
             "synonyms", "source_citations", "filters")
        }
        conn.execute("DELETE FROM te_aka_entries WHERE word_id=?", (k,))
        log_rows.append((
            run_id, "te_aka", str(k), old["headword"], "deleted",
            None,
            json.dumps(old_snapshot, ensure_ascii=False),
            None,
        ))

    # Bulk-insert log rows
    conn.executemany(
        "INSERT INTO data_refresh_log "
        "(run_id, source_dict, entry_key, headword, change_type, changed_fields, old_values, new_values) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        log_rows,
    )

    conn.execute("INSERT INTO te_aka_fts(te_aka_fts) VALUES ('rebuild')")

    actual = conn.execute("SELECT COUNT(*) FROM te_aka_entries").fetchone()[0]
    conn.execute(
        "UPDATE source_metadata SET entry_count=?, last_updated=datetime('now') "
        "WHERE source_id='te_aka'",
        (actual,),
    )
    print(f"source_metadata updated: {actual:,} entries total | run_id={run_id}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Import Te Aka entries into the database")
    parser.add_argument(
        "--refresh", action="store_true",
        help="Incremental refresh: diff against existing DB, log changes, preserve history",
    )
    args = parser.parse_args()

    if not JSON_PATH.exists():
        print(f"Error: {JSON_PATH} not found. Run 04_te_aka_parse.py first.")
        sys.exit(1)

    entries: list[dict] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(entries):,} entries from JSON")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        with conn:
            if args.refresh:
                print("Mode: incremental refresh")
                refresh_import(conn, entries)
            else:
                print("Mode: full replace (initial import)")
                full_import(conn, entries)
        conn.commit()
    finally:
        conn.close()

    print("\nImport complete.")


if __name__ == "__main__":
    main()
