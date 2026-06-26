"""Session 35: detect cross-source duplicate candidates.

Loads all sources (incl. personal_lexicon where is_private=0), generates every
sense-level cross-source pair sharing a headword_search, and inserts as
status='unreviewed'.  Pairs already in the table (approved or dismissed) are
skipped via ON CONFLICT IGNORE — they will never be re-queued.

Run:  py scripts/35_detect_pairs.py
      py scripts/35_detect_pairs.py --stats
      py scripts/35_detect_pairs.py --limit 500   (cap new inserts, for testing)
"""

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH

# Canonical ordering: lower index = source_a so every pair has a unique direction.
SOURCE_ORDER = {
    "hepatakakupu": 0,
    "paekupu":      1,
    "papakupu":     2,
    "personal":     3,
    "te_aka":       4,
    "williams":     5,
}

_QUERIES = [
    ("williams",     "SELECT headword_search, id FROM williams_entries"),
    ("papakupu",     "SELECT headword_search, id FROM papakupu_entries"),
    ("te_aka",       "SELECT headword_search, id FROM te_aka_entries"),
    ("hepatakakupu", "SELECT headword_search, id FROM hepatakakupu_entries"),
    ("paekupu",      "SELECT headword_search, id FROM paekupu_entries"),
    ("personal",     "SELECT headword_search, id FROM personal_lexicon WHERE is_private = 0"),
]


def _load_entries(conn: sqlite3.Connection) -> dict:
    """Return {headword_search: [(source, entry_id), ...]} across all sources."""
    by_key: dict = defaultdict(list)
    for source, sql in _QUERIES:
        for hws, eid in conn.execute(sql).fetchall():
            by_key[hws].append((source, eid))
    return by_key


def _generate_pairs(by_key: dict, limit: int) -> list:
    """Return list of (headword_search, source_a, entry_id_a, source_b, entry_id_b, detected_at)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    pairs = []
    for hws, entries in by_key.items():
        sources_here = {s for s, _ in entries}
        if len(sources_here) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                sa, ia = entries[i]
                sb, ib = entries[j]
                if sa == sb:
                    continue
                # canonicalise direction
                if SOURCE_ORDER.get(sa, 99) > SOURCE_ORDER.get(sb, 99):
                    sa, ia, sb, ib = sb, ib, sa, ia
                pairs.append((hws, sa, ia, sb, ib, now))
                if limit and len(pairs) >= limit:
                    return pairs
    return pairs


def _insert_pairs(conn: sqlite3.Connection, pairs: list) -> tuple[int, int]:
    before = conn.execute("SELECT COUNT(*) FROM cross_source_candidates").fetchone()[0]
    _CHUNK = 500
    for start in range(0, len(pairs), _CHUNK):
        conn.executemany(
            """INSERT OR IGNORE INTO cross_source_candidates
                   (headword_search, source_a, entry_id_a, source_b, entry_id_b, detected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            pairs[start : start + _CHUNK],
        )
    after = conn.execute("SELECT COUNT(*) FROM cross_source_candidates").fetchone()[0]
    new = after - before
    skipped = len(pairs) - new
    return new, skipped


def _stats(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM cross_source_candidates"
        " GROUP BY status ORDER BY status"
    ).fetchall()
    total = sum(r[1] for r in rows)
    print(f"cross_source_candidates — {total} total")
    for status, count in rows:
        print(f"  {status}: {count}")

    by_pair = conn.execute(
        "SELECT source_a || ' x ' || source_b AS pair, COUNT(*)"
        " FROM cross_source_candidates GROUP BY pair ORDER BY pair"
    ).fetchall()
    print(f"\nPairs by source combination:")
    for pair, count in by_pair:
        print(f"  {pair}: {count}")

    runs = conn.execute(
        "SELECT COUNT(*) FROM cross_source_detection_runs"
    ).fetchone()[0]
    print(f"\nDetection runs: {runs}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true", help="Show counts by status")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap new pairs generated (0 = no limit; useful for testing)")
    args = parser.parse_args()

    with sqlite3.connect(DB_PATH) as conn:
        if args.stats:
            _stats(conn)
            return

        print("Loading entries from all sources...")
        by_key = _load_entries(conn)
        shared = sum(1 for e in by_key.values() if len({s for s, _ in e}) >= 2)
        print(f"  {shared:,} headword_search values appear in 2+ sources")

        print("Generating pairs...")
        pairs = _generate_pairs(by_key, args.limit)
        print(f"  {len(pairs):,} candidate pairs generated"
              + (" (capped)" if args.limit and len(pairs) >= args.limit else ""))

        print("Inserting (chunks of 500)...")
        new, skipped = _insert_pairs(conn, pairs)
        conn.execute(
            """INSERT INTO cross_source_detection_runs (new_pairs, skipped_existing)
               VALUES (?, ?)""",
            (new, skipped),
        )
        conn.commit()

    print(f"Done: {new:,} new, {skipped:,} skipped (already existed)")


if __name__ == "__main__":
    main()
