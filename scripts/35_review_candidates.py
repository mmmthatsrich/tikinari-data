"""Session 35: human review CLI for cross-source duplicate candidates.

Shows 'pending' rows (AI-flagged as likely matches) one at a time.
Keys: a = approve   d = dismiss   s = skip (later)   q = quit

Run:  py scripts/35_review_candidates.py            # review pending, batch of 20
      py scripts/35_review_candidates.py --limit 50
      py scripts/35_review_candidates.py --stats
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH

# Map source name → (table, headword_col, definition_col)
_SOURCE_TABLES = {
    "williams":     ("williams_entries",     "headword", "definition"),
    "papakupu":     ("papakupu_entries",     "headword", "definition"),
    "te_aka":       ("te_aka_entries",       "headword", "definition"),
    "hepatakakupu": ("hepatakakupu_entries", "headword", "definition"),
    "paekupu":      ("paekupu_entries",      "headword", "definition"),
    "personal":     ("personal_lexicon",     "headword", "definition"),
}

_DEF_TRUNCATE = 400


def _fetch(conn: sqlite3.Connection, source: str, entry_id: int) -> tuple[str, str]:
    table, hw_col, def_col = _SOURCE_TABLES[source]
    row = conn.execute(
        f"SELECT {hw_col}, {def_col} FROM {table} WHERE id = ?", (entry_id,)
    ).fetchone()
    if not row:
        return "(not found)", "(not found)"
    return (row[0] or ""), (row[1] or "(no definition)")


def _show(conn: sqlite3.Connection, row: sqlite3.Row, n: int, total: int) -> None:
    hw_a, def_a = _fetch(conn, row["source_a"], row["entry_id_a"])
    hw_b, def_b = _fetch(conn, row["source_b"], row["entry_id_b"])
    print(f"\n{'='*70}  [{n}/{total}]")
    print(f"  key : {row['headword_search']}")
    print(f"  A   [{row['source_a']} #{row['entry_id_a']}]  {hw_a}")
    print(f"      {def_a[:_DEF_TRUNCATE]}")
    print(f"  B   [{row['source_b']} #{row['entry_id_b']}]  {hw_b}")
    print(f"      {def_b[:_DEF_TRUNCATE]}")
    if row["ai_reasoning"]:
        print(f"  AI  {row['ai_reasoning'][:250]}")
    print()


def _update(conn: sqlite3.Connection, row_id: int, status: str, notes: str = "") -> None:
    conn.execute(
        "UPDATE cross_source_candidates SET status=?, reviewed_at=?, review_notes=? WHERE id=?",
        (status, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), notes or None, row_id),
    )
    conn.commit()


def _review_loop(conn: sqlite3.Connection, limit: int) -> None:
    rows = conn.execute(
        "SELECT * FROM cross_source_candidates WHERE status = 'pending'"
        " ORDER BY headword_search LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        print("No pending candidates. Run detect first, then an AI review session.")
        return
    total = conn.execute(
        "SELECT COUNT(*) FROM cross_source_candidates WHERE status = 'pending'"
    ).fetchone()[0]
    print(f"{len(rows)} shown of {total} pending.  a=approve  d=dismiss  s=skip  q=quit")
    done = 0
    for i, row in enumerate(rows, 1):
        _show(conn, row, i, len(rows))
        while True:
            key = input("  > ").strip().lower()
            if key in ("a", "d", "s", "q"):
                break
            print("  a / d / s / q")
        if key == "q":
            break
        if key == "s":
            continue
        _update(conn, row["id"], "approved" if key == "a" else "dismissed")
        done += 1
    print(f"\n{done} reviewed this session.")


def _stats(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM cross_source_candidates"
        " GROUP BY status ORDER BY status"
    ).fetchall()
    total = sum(r[1] for r in rows)
    print(f"cross_source_candidates — {total} total")
    for status, count in rows:
        print(f"  {status}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max pending rows to show per session")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if args.stats:
            _stats(conn)
        else:
            _review_loop(conn, args.limit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
