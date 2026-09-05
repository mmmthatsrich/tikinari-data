"""Import parsed Wakareo JSON into the ten landing tables.

Idempotent: INSERT OR REPLACE keyed on source_entry_id ('WR-HMN.297').

  py scripts/41_wakareo_import.py                 # every component found
  py scripts/41_wakareo_import.py --source ngata  # just one
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH, normalise_search_key, normalise_sort_key, compute_content_hash
from wakareo_records import EN_MI_SOURCE_IDS, TAG_TO_SOURCE

PARSED_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "parsed"

SOURCE_TO_TABLE = {sid: f"{sid}_entries" for sid in TAG_TO_SOURCE.values()}

BASE_COLS = ("source_entry_id", "wakareo_id", "ref_no", "headword", "headword_sort",
             "headword_search", "part_of_speech", "search_scope", "body_raw",
             "content_hash")


def row_for(rec: dict) -> tuple[tuple, tuple]:
    """Return (column_names, values) for one record, direction-aware."""
    hw = rec["headword"]
    base = (
        rec["source_entry_id"], rec["wakareo_id"], rec["ref_no"], hw,
        normalise_sort_key(hw), normalise_search_key(hw),
        rec["pos"] or None,
        json.dumps(rec["search_scope"], ensure_ascii=False),
        rec["body_raw"],
        compute_content_hash({"hw": hw, "body": rec["body_raw"]}),
    )
    if rec["source_id"] in EN_MI_SOURCE_IDS:
        return (BASE_COLS + ("equivalents", "qualifier", "example_en", "example_mi"),
                base + (json.dumps(rec["equivalents"], ensure_ascii=False),
                        rec["qualifier"], rec["example_en"], rec["example_mi"]))
    if rec["source_id"] == "te_matatiki":
        return (BASE_COLS + ("gloss_en", "derivation", "williams_refs"),
                base + (rec["gloss_en"], rec["derivation"],
                        json.dumps(rec["williams_refs"])))
    return BASE_COLS + ("gloss_en",), base + (rec["gloss_en"],)


def import_source(con: sqlite3.Connection, source_id: str) -> int:
    path = PARSED_DIR / f"{source_id}.json"
    if not path.exists():
        return 0
    records = json.loads(path.read_text(encoding="utf-8"))
    table = SOURCE_TO_TABLE[source_id]
    n = 0
    for rec in records:
        cols, vals = row_for(rec)
        placeholders = ",".join("?" * len(vals))
        con.execute(
            f'INSERT OR REPLACE INTO {table} ({",".join(cols)}) VALUES ({placeholders})',
            vals,
        )
        n += 1
    con.commit()
    con.execute("UPDATE source_metadata SET entry_count=?, last_updated=datetime('now') "
                "WHERE source_id=?", (n, source_id))
    con.commit()
    return n


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Import parsed Wakareo JSON.")
    ap.add_argument("--source", action="append", choices=sorted(SOURCE_TO_TABLE),
                    help="component to import; repeatable. Default: all present.")
    args = ap.parse_args()
    targets = args.source or sorted(SOURCE_TO_TABLE)

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    total = 0
    for source_id in targets:
        n = import_source(con, source_id)
        total += n
        if n:
            print(f"  {source_id:22s} {n:6,d} rows")
    print(f"\nImported {total:,} rows.")
    con.close()


if __name__ == "__main__":
    main()
