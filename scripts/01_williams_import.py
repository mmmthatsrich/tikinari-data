"""Imports williams_entries.json into williams_entries and rebuilds FTS."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import normalise_sort_key, normalise_search_key, load_source_abbrevs, expand_citations

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH = (
    Path(__file__).parent.parent
    / "sources" / "williams" / "parsed" / "williams_entries.json"
)


def import_williams(conn: sqlite3.Connection, entries: list) -> int:
    conn.execute("DELETE FROM williams_entries")

    abbrevs = load_source_abbrevs("williams")

    rows = [
        (
            e["headword"],
            normalise_sort_key(e["headword"]),
            normalise_search_key(e["headword"]),
            e.get("part_of_speech") or None,
            expand_citations(e["definition"], abbrevs) if e.get("definition") else None,
            json.dumps(
                [expand_citations(ex, abbrevs) for ex in (e.get("usage_examples") or [])],
                ensure_ascii=False,
            ),
            e.get("sense_number") or None,
            json.dumps(e.get("cross_refs") or [], ensure_ascii=False),
            e.get("page_number"),
            e.get("source_section"),
        )
        for e in entries
    ]

    conn.executemany(
        """INSERT INTO williams_entries
               (headword, headword_sort, headword_search, part_of_speech, definition,
                usage_examples, sense_number, cross_refs, page_number, source_section)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    conn.execute("INSERT INTO williams_fts(williams_fts) VALUES ('rebuild')")

    count = len(rows)
    conn.execute(
        "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now')"
        " WHERE source_id = 'williams'",
        (count,),
    )
    return count


def main() -> None:
    entries = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    with sqlite3.connect(DB_PATH) as conn:
        count = import_williams(conn, entries)
        conn.commit()
    print(f"Imported {count} Williams entries into {DB_PATH}")


if __name__ == "__main__":
    main()
