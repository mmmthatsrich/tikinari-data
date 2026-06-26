"""Imports papakupu_entries.json into papakupu_entries and rebuilds FTS."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import normalise_sort_key, normalise_search_key

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH = (
    Path(__file__).parent.parent
    / "sources" / "papakupu" / "parsed" / "papakupu_entries.json"
)


def import_papakupu(conn: sqlite3.Connection, entries: list) -> int:
    conn.execute("DELETE FROM papakupu_entries")

    rows = []
    for e in entries:
        variant_forms = e.get("variant_forms") or []
        variant_search_keys = list(
            {normalise_search_key(v) for v in variant_forms}
        )
        rows.append((
            e["headword"],
            normalise_sort_key(e["headword"]),
            normalise_search_key(e["headword"]),
            e.get("part_of_speech") or None,
            e.get("definition") or None,
            json.dumps(e.get("usage_examples") or [], ensure_ascii=False),
            json.dumps(variant_forms, ensure_ascii=False),
            json.dumps(variant_search_keys, ensure_ascii=False),
            e.get("source_code") or None,
            e.get("loan_marker") or None,
            json.dumps(e.get("see_also") or [], ensure_ascii=False),
            e.get("pdf_page"),
        ))

    conn.executemany(
        """INSERT INTO papakupu_entries
               (headword, headword_sort, headword_search, part_of_speech, definition,
                usage_examples, variant_forms, variant_search_keys, source_code,
                loan_marker, see_also, pdf_page)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    conn.execute("INSERT INTO papakupu_fts(papakupu_fts) VALUES ('rebuild')")

    count = len(rows)
    conn.execute(
        "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now')"
        " WHERE source_id = 'papakupu'",
        (count,),
    )
    return count


def main() -> None:
    entries = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    with sqlite3.connect(DB_PATH) as conn:
        count = import_papakupu(conn, entries)
        conn.commit()
    print(f"Imported {count} Papakupu entries into {DB_PATH}")


if __name__ == "__main__":
    main()
