"""Rebuilds all FTS5 virtual tables after manual DB edits.

Usage: py scripts/06_fts_rebuild.py
"""
import sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

sys.stdout.reconfigure(encoding='utf-8')

FTS_TABLES = [
    ("williams_fts",     "williams_entries"),
    ("papakupu_fts",     "papakupu_entries"),
    ("pollex_fts",       "pollex_entries"),
    ("te_aka_fts",       "te_aka_entries"),
    ("hepatakakupu_fts", "hepatakakupu_entries"),
    ("paekupu_fts",      "paekupu_entries"),
    ("personal_fts",     "personal_lexicon"),
]


def rebuild_all(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        existing_tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for fts, content in FTS_TABLES:
            if fts not in existing_tables:
                print(f"  skip: {fts} (not in DB)")
                continue
            n = conn.execute(f"SELECT COUNT(*) FROM {content}").fetchone()[0]
            conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")
            print(f"  rebuilt: {fts} ({n:,} rows)")
        conn.commit()
    print("FTS rebuild complete.")


if __name__ == "__main__":
    rebuild_all()
