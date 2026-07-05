"""Backfill sense.gloss_en for existing Papakupu senses.

The unified build historically stored each Papakupu entry's whole ``definition``
blob (gloss + usage examples + editorial notes) in ``sense.gloss_en``. This
rewrites gloss_en in place to the definition only, using the same
``papakupu_gloss.clean_gloss`` the build now applies, so a re-export shows the
clean gloss. When nothing remains (Māori-only example entries) gloss_en is set
to NULL and the app falls back to entries.headword_en.

Only ``sense.gloss_en`` is touched. ``definition_raw`` and the ``example`` table
are left byte-for-byte unchanged.

Dry-run by default; pass --apply to write. A timestamped DB backup is made first.

Usage:
    py scripts/51_papakupu_gloss_backfill.py            # dry-run, prints stats
    py scripts/51_papakupu_gloss_backfill.py --apply    # write changes
"""
import argparse
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH
from papakupu_gloss import clean_gloss, _ws


def load_example_texts(con) -> dict:
    """Map sense_id -> list of stored example.text_mi (Papakupu senses only)."""
    by_sense = defaultdict(list)
    for sid, tmi in con.execute(
        "SELECT sense_id, text_mi FROM example "
        "WHERE entry_id IN (SELECT id FROM entry WHERE source_id='papakupu')"
    ):
        if tmi:
            by_sense[sid].append(tmi)
    return by_sense


def compute_updates(con):
    """Return (rows, updates, emptied, by_sense); updates is [(new_gloss|None, sid)]."""
    by_sense = load_example_texts(con)
    rows = con.execute(
        "SELECT s.id, s.gloss_en, s.definition_raw FROM sense s "
        "JOIN entry e ON e.id = s.entry_id WHERE e.source_id = 'papakupu'"
    ).fetchall()

    updates = []
    emptied = 0
    for sid, gloss_en, definition_raw in rows:
        new = clean_gloss(definition_raw, by_sense.get(sid, []))
        if new != gloss_en:
            updates.append((new, sid))
            if new is None:
                emptied += 1
    return rows, updates, emptied, by_sense


def verify(con, by_sense) -> int:
    """Count Papakupu senses whose gloss_en still contains an own example.text_mi."""
    bad = 0
    for sid, gloss_en in con.execute(
        "SELECT s.id, s.gloss_en FROM sense s "
        "JOIN entry e ON e.id = s.entry_id WHERE e.source_id = 'papakupu'"
    ):
        g = _ws(gloss_en)
        if g and any(_ws(t) in g for t in by_sense.get(sid, [])):
            bad += 1
    return bad


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    rows, updates, emptied, by_sense = compute_updates(con)

    print(f"papakupu senses scanned : {len(rows)}")
    print(f"gloss_en to change      : {len(updates)}")
    print(f"  ...emptied -> NULL     : {emptied}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        con.close()
        return

    ex_before = con.execute(
        "SELECT count(*) FROM example WHERE entry_id IN "
        "(SELECT id FROM entry WHERE source_id='papakupu')"
    ).fetchone()[0]

    backup = Path(str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    con.executemany("UPDATE sense SET gloss_en = ? WHERE id = ?", updates)
    con.commit()

    bad = verify(con, by_sense)
    ex_after = con.execute(
        "SELECT count(*) FROM example WHERE entry_id IN "
        "(SELECT id FROM entry WHERE source_id='papakupu')"
    ).fetchone()[0]
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]

    print(f"applied. gloss_en updated: {len(updates)}")
    print(f"verify: senses whose gloss_en still contains own example text_mi: {bad}")
    print(f"example rows (papakupu) before/after: {ex_before} / {ex_after}")
    print(f"integrity_check: {integrity}")
    con.close()


if __name__ == "__main__":
    main()
