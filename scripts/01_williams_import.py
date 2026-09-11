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


def assign_ids(entries):
    """Deterministic williams_entries ids. mains: 1..N positional.
    sub/hang: 1_000_000 + main*100 + k (k=1..49, S65 scheme — frozen).
    subx (mid-paragraph recoveries, S66): same formula, k = 50 + j."""
    ids, main_seq, sub_k, subx_j = [], 0, 0, 0
    for e in entries:
        kind = e.get("kind", "main")
        if kind == "main":
            main_seq += 1
            sub_k = subx_j = 0
            ids.append(main_seq)
            continue
        if main_seq == 0:
            raise ValueError(f"sub-entry before any main: {e['headword']}")
        if kind == "subx":
            subx_j += 1
            if subx_j > 49:
                raise ValueError(f"over 49 subx under main id {main_seq}")
            ids.append(1_000_000 + main_seq * 100 + 50 + subx_j)
        else:
            sub_k += 1
            if sub_k > 49:
                raise ValueError(f"over 49 sub-entries under main id {main_seq}")
            ids.append(1_000_000 + main_seq * 100 + sub_k)
    return ids


def import_williams(conn: sqlite3.Connection, entries: list) -> int:
    conn.execute("DELETE FROM williams_entries")

    abbrevs = load_source_abbrevs("williams")

    # Explicit deterministic ids. cross_source_candidates (and the downstream
    # device id '{source_id}:{source_entry_id}') reference williams_entries.id,
    # so existing ids must never shift. "main" entries take sequential positions
    # 1..N — identical to the pre-split rowids (the parser preserves the main
    # sequence). Recovered sub-/hang-entries get 1_000_000 + main_id*100 + k
    # (k = order within the parent's section), collision-free and stable across
    # re-runs. subx (mid-paragraph recoveries) take k = 50 + j — see assign_ids.
    eids = assign_ids(entries)
    rows = []
    for eid, e in zip(eids, entries):
        rows.append((
            eid,
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
            e.get("headword_note") or None,
            e.get("page_number"),
            e.get("source_section"),
        ))

    conn.executemany(
        """INSERT INTO williams_entries
               (id, headword, headword_sort, headword_search, part_of_speech, definition,
                usage_examples, sense_number, cross_refs, headword_note,
                page_number, source_section)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
