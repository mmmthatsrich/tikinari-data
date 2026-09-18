"""
Import Paekupu entries from JSON into staging_dictionary.db.

Default mode (first import):
  Drops and recreates paekupu_entries and its FTS table so the full schema
  replaces the stub, then bulk-inserts all entries.  content_hash and
  first_seen are set on every row.  No change log is written.

Refresh mode (--refresh):
  Keeps existing rows.  Diffs new JSON against the DB by slug, using
  content_hash to detect changes.  Inserts new entries, updates modified
  entries, hard-deletes removed entries.  All changes are logged in
  data_refresh_log; a summary row is written to data_refresh_runs.

Usage:
  py 04_paekupu_import.py             # full replace (initial load)
  py 04_paekupu_import.py --refresh   # incremental diff
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import normalise_sort_key, normalise_search_key, compute_content_hash
from suffix_forms import strip_suffix_notation

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH   = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH = Path(__file__).parent.parent / "sources" / "paekupu" / "parsed" / "paekupu_entries.json"

# Fields that constitute "material" content — changes here are tracked.
# Excludes: id, slug, headword_sort, headword_search, audio_url,
#           content_hash, first_seen, created_at, last_updated.
MATERIAL_FIELDS = (
    "headword", "headword_en", "part_of_speech", "pos_mi",
    "subject_area", "subject_area_en", "subject_areas",
    "definition_mi", "definition", "alternative_words", "usage_examples",
)

# ── DDL ──────────────────────────────────────────────────────────────────────

_DROP_SQL = """
    DROP TRIGGER IF EXISTS paekupu_fts_ins;
    DROP TRIGGER IF EXISTS paekupu_fts_upd;
    DROP TRIGGER IF EXISTS paekupu_fts_del;
    DROP TABLE IF EXISTS paekupu_fts;
    DROP INDEX IF EXISTS idx_paekupu_search;
    DROP INDEX IF EXISTS idx_paekupu_slug;
    DROP TABLE IF EXISTS paekupu_entries;
"""

_CREATE_SQL = """
    CREATE TABLE paekupu_entries (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        slug             TEXT NOT NULL UNIQUE,
        headword         TEXT NOT NULL,
        headword_sort    TEXT NOT NULL,
        headword_search  TEXT NOT NULL,
        headword_en      TEXT,
        part_of_speech   TEXT,
        pos_mi           TEXT,
        subject_area     TEXT,
        subject_area_en  TEXT,
        subject_areas    TEXT DEFAULT '[]',
        audio_url        TEXT,
        definition_mi    TEXT,
        definition       TEXT,
        alternative_words TEXT DEFAULT '[]',
        usage_examples   TEXT DEFAULT '[]',
        content_hash     TEXT,
        first_seen       TEXT,
        created_at       TEXT DEFAULT (datetime('now')),
        last_updated     TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX idx_paekupu_search ON paekupu_entries(headword_search);
    CREATE INDEX idx_paekupu_slug   ON paekupu_entries(slug);

    CREATE VIRTUAL TABLE paekupu_fts USING fts5(
        headword, definition, usage_examples,
        content='paekupu_entries', content_rowid='id',
        tokenize='unicode61'
    );

    CREATE TRIGGER paekupu_fts_ins AFTER INSERT ON paekupu_entries BEGIN
        INSERT INTO paekupu_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER paekupu_fts_upd AFTER UPDATE ON paekupu_entries BEGIN
        INSERT INTO paekupu_fts(paekupu_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
        INSERT INTO paekupu_fts(rowid, headword, definition, usage_examples)
        VALUES (new.id, new.headword, new.definition, new.usage_examples);
    END;
    CREATE TRIGGER paekupu_fts_del AFTER DELETE ON paekupu_entries BEGIN
        INSERT INTO paekupu_fts(paekupu_fts, rowid, headword, definition, usage_examples)
        VALUES ('delete', old.id, old.headword, old.definition, old.usage_examples);
    END;
"""

_INSERT_SQL = """
    INSERT INTO paekupu_entries
        (slug, headword, headword_sort, headword_search, headword_en,
         part_of_speech, pos_mi, subject_area, subject_area_en, subject_areas,
         audio_url, definition_mi, definition, alternative_words, usage_examples,
         content_hash, first_seen)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_material(r: dict) -> dict:
    return {
        "headword":        r.get("headword") or "",
        "headword_en":     r.get("headword_en") or "",
        "part_of_speech":  r.get("part_of_speech") or "",
        "pos_mi":          r.get("pos_mi") or "",
        "subject_area":    r.get("subject_area") or "",
        "subject_area_en": r.get("subject_area_en") or "",
        "subject_areas":   r.get("subject_areas") or [],
        "definition_mi":   r.get("definition_mi") or "",
        "definition":      r.get("definition") or "",
        "alternative_words": r.get("alternative_words") or [],
        "usage_examples":  r.get("usage_examples") or [],
    }


def _build_row(r: dict, now: str) -> tuple:
    hw = r["headword"]
    return (
        r["slug"],
        hw,
        normalise_sort_key(hw),
        # 'ahu ~nga' keys as 'ahu'. The headword column keeps the source's own
        # spelling; only the matching key is built from the bare word, or the
        # entry can never meet the plain 'ahu' four other sources hold.
        normalise_search_key(strip_suffix_notation(hw)),
        r.get("headword_en"),
        r.get("part_of_speech"),
        r.get("pos_mi"),
        r.get("subject_area"),
        r.get("subject_area_en"),
        json.dumps(r.get("subject_areas") or [], ensure_ascii=False),
        r.get("audio_url"),
        r.get("definition_mi"),
        r.get("definition"),
        json.dumps(r.get("alternative_words") or [], ensure_ascii=False),
        json.dumps(r.get("usage_examples") or [], ensure_ascii=False),
        compute_content_hash(_build_material(r)),
        now,
    )


# ── Full replace (initial import) ─────────────────────────────────────────────

def full_import(conn: sqlite3.Connection, records: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(_DROP_SQL)
    print("Dropped old paekupu tables/triggers")

    conn.executescript(_CREATE_SQL)
    print("Recreated paekupu_entries, paekupu_fts, and triggers")

    rows = [_build_row(r, now) for r in records]
    conn.executemany(_INSERT_SQL, rows)
    print(f"Inserted {len(rows):,} rows")

    conn.execute("INSERT INTO paekupu_fts(paekupu_fts) VALUES ('rebuild')")
    print("FTS rebuilt")

    actual = conn.execute("SELECT COUNT(*) FROM paekupu_entries").fetchone()[0]
    conn.execute(
        "UPDATE source_metadata SET entry_count=?, last_updated=datetime('now') "
        "WHERE source_id='paekupu'",
        (actual,),
    )
    conn.execute("PRAGMA foreign_keys = ON")
    print(f"source_metadata updated: {actual:,} entries")


# ── Refresh (incremental diff) ────────────────────────────────────────────────

def _material_from_db_paekupu(db: dict) -> dict:
    """Rebuild the material dict from stored DB field strings (for hash backfill)."""
    return {
        "headword":        db.get("headword") or "",
        "headword_en":     db.get("headword_en") or "",
        "part_of_speech":  db.get("part_of_speech") or "",
        "pos_mi":          db.get("pos_mi") or "",
        "subject_area":    db.get("subject_area") or "",
        "subject_area_en": db.get("subject_area_en") or "",
        "subject_areas":   json.loads(db.get("subject_areas") or "[]"),
        "definition_mi":   db.get("definition_mi") or "",
        "definition":      db.get("definition") or "",
        "alternative_words": json.loads(db.get("alternative_words") or "[]"),
        "usage_examples":  json.loads(db.get("usage_examples") or "[]"),
    }


def refresh_import(conn: sqlite3.Connection, records: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()

    # Load existing DB state keyed by slug
    existing: dict[str, dict] = {}
    for row in conn.execute(
        "SELECT slug, headword, content_hash, first_seen, "
        "headword_en, part_of_speech, pos_mi, subject_area, subject_area_en, "
        "subject_areas, definition_mi, definition, alternative_words, usage_examples "
        "FROM paekupu_entries"
    ):
        existing[row[0]] = {
            "headword": row[1], "content_hash": row[2], "first_seen": row[3],
            "headword_en": row[4], "part_of_speech": row[5], "pos_mi": row[6],
            "subject_area": row[7], "subject_area_en": row[8],
            "subject_areas": row[9], "definition_mi": row[10],
            "definition": row[11], "alternative_words": row[12], "usage_examples": row[13],
        }

    # Backfill content_hash for rows imported before refresh tracking was added
    backfill: list[tuple] = []
    for slug, db in existing.items():
        if db["content_hash"] is None:
            h = compute_content_hash(_material_from_db_paekupu(db))
            db["content_hash"] = h
            backfill.append((h, slug))
    if backfill:
        conn.executemany("UPDATE paekupu_entries SET content_hash=? WHERE slug=?", backfill)
        print(f"  Backfilled content_hash for {len(backfill):,} existing rows")

    incoming: dict[str, dict] = {r["slug"]: r for r in records}

    new_keys     = set(incoming) - set(existing)
    deleted_keys = set(existing) - set(incoming)
    common_keys  = set(incoming) & set(existing)

    modified: list[tuple] = []
    unchanged_count = 0
    for slug in common_keys:
        r = incoming[slug]
        new_hash = compute_content_hash(_build_material(r))
        if new_hash == existing[slug]["content_hash"]:
            unchanged_count += 1
            continue
        old_db = existing[slug]
        changed = []
        old_vals: dict = {}
        new_vals: dict = {}
        field_map = {
            "headword":        (old_db["headword"],         r.get("headword") or ""),
            "headword_en":     (old_db["headword_en"],      r.get("headword_en") or ""),
            "part_of_speech":  (old_db["part_of_speech"],   r.get("part_of_speech") or ""),
            "pos_mi":          (old_db["pos_mi"],            r.get("pos_mi") or ""),
            "subject_area":    (old_db["subject_area"],      r.get("subject_area") or ""),
            "subject_area_en": (old_db["subject_area_en"],   r.get("subject_area_en") or ""),
            "subject_areas":   (old_db["subject_areas"],     json.dumps(r.get("subject_areas") or [], ensure_ascii=False)),
            "definition_mi":   (old_db["definition_mi"],     r.get("definition_mi") or ""),
            "definition":      (old_db["definition"],        r.get("definition") or ""),
            "alternative_words":(old_db["alternative_words"], json.dumps(r.get("alternative_words") or [], ensure_ascii=False)),
            "usage_examples":  (old_db["usage_examples"],    json.dumps(r.get("usage_examples") or [], ensure_ascii=False)),
        }
        for field, (old_v, new_v) in field_map.items():
            if (old_v or "") != (new_v or ""):
                changed.append(field)
                old_vals[field] = old_v
                new_vals[field] = new_v
        if changed:
            modified.append((slug, r, changed, old_vals, new_vals))

    print(f"  new: {len(new_keys)}, modified: {len(modified)}, "
          f"deleted: {len(deleted_keys)}, unchanged: {unchanged_count}")

    run_id = conn.execute(
        "INSERT INTO data_refresh_runs "
        "(source_dict, new_count, modified_count, deleted_count, unchanged_count, total_scraped) "
        "VALUES ('paekupu', ?, ?, ?, ?, ?)",
        (len(new_keys), len(modified), len(deleted_keys), unchanged_count, len(records)),
    ).lastrowid

    log_rows: list[tuple] = []

    for slug in new_keys:
        r = incoming[slug]
        conn.execute(_INSERT_SQL, _build_row(r, now))
        log_rows.append((run_id, "paekupu", slug, r.get("headword"), "new", None, None, None))

    for slug, r, changed, old_vals, new_vals in modified:
        new_hash = compute_content_hash(_build_material(r))
        conn.execute(
            "UPDATE paekupu_entries SET "
            "headword=?, headword_sort=?, headword_search=?, headword_en=?, "
            "part_of_speech=?, pos_mi=?, subject_area=?, subject_area_en=?, "
            "subject_areas=?, audio_url=?, definition_mi=?, definition=?, "
            "alternative_words=?, usage_examples=?, content_hash=?, last_updated=datetime('now') "
            "WHERE slug=?",
            (
                r["headword"],
                normalise_sort_key(r["headword"]),
                normalise_search_key(strip_suffix_notation(r["headword"])),
                r.get("headword_en"),
                r.get("part_of_speech"),
                r.get("pos_mi"),
                r.get("subject_area"),
                r.get("subject_area_en"),
                json.dumps(r.get("subject_areas") or [], ensure_ascii=False),
                r.get("audio_url"),
                r.get("definition_mi"),
                r.get("definition"),
                json.dumps(r.get("alternative_words") or [], ensure_ascii=False),
                json.dumps(r.get("usage_examples") or [], ensure_ascii=False),
                new_hash,
                slug,
            ),
        )
        log_rows.append((
            run_id, "paekupu", slug, r.get("headword"), "modified",
            json.dumps(changed, ensure_ascii=False),
            json.dumps(old_vals, ensure_ascii=False),
            json.dumps(new_vals, ensure_ascii=False),
        ))

    for slug in deleted_keys:
        old = existing[slug]
        old_snapshot = {f: old.get(f) for f in (
            "headword", "headword_en", "part_of_speech", "pos_mi",
            "subject_area", "subject_area_en", "subject_areas",
            "definition_mi", "definition", "alternative_words", "usage_examples",
        )}
        conn.execute("DELETE FROM paekupu_entries WHERE slug=?", (slug,))
        log_rows.append((
            run_id, "paekupu", slug, old["headword"], "deleted",
            None,
            json.dumps(old_snapshot, ensure_ascii=False),
            None,
        ))

    conn.executemany(
        "INSERT INTO data_refresh_log "
        "(run_id, source_dict, entry_key, headword, change_type, changed_fields, old_values, new_values) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        log_rows,
    )

    conn.execute("INSERT INTO paekupu_fts(paekupu_fts) VALUES ('rebuild')")

    actual = conn.execute("SELECT COUNT(*) FROM paekupu_entries").fetchone()[0]
    conn.execute(
        "UPDATE source_metadata SET entry_count=?, last_updated=datetime('now') "
        "WHERE source_id='paekupu'",
        (actual,),
    )
    print(f"source_metadata updated: {actual:,} entries total | run_id={run_id}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Import Paekupu entries into the database")
    parser.add_argument(
        "--refresh", action="store_true",
        help="Incremental refresh: diff against existing DB, log changes, preserve history",
    )
    args = parser.parse_args()

    if not JSON_PATH.exists():
        print(f"Error: {JSON_PATH} not found. Run 04_paekupu_parse.py first.")
        sys.exit(1)

    records: list[dict] = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(records):,} records from JSON")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        with conn:
            if args.refresh:
                print("Mode: incremental refresh")
                refresh_import(conn, records)
            else:
                print("Mode: full replace (initial import)")
                full_import(conn, records)
        conn.commit()
    finally:
        conn.close()

    print("\nImport complete.")


if __name__ == "__main__":
    main()
