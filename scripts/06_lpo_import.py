"""Import LPO (tlopo) Proto-Oceanic cognatesets into lpo_cognatesets table.

Source: sources/lpo/cldf/cognatesets.csv  (2,820 rows)
Chapter linkage via cognatesetreferences.csv -> chapters.csv
"""

import csv
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent))
from utils import canonical_level, normalise_proto_key

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
CLDF_DIR = Path(__file__).parent.parent / "sources" / "lpo" / "cldf"


def load_chapters() -> dict[str, str]:
    """Return {chapter_id: chapter_title} from chapters.csv."""
    chapters: dict[str, str] = {}
    with open(CLDF_DIR / "chapters.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            chapters[row["ID"]] = row["Name"]
    return chapters


def load_cognateset_chapters() -> dict[str, str]:
    """Return {cognateset_id: chapter_id} — first chapter reference wins."""
    cs_chapter: dict[str, str] = {}
    with open(CLDF_DIR / "cognatesetreferences.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cid = row["Cognateset_ID"]
            if cid not in cs_chapter:
                cs_chapter[cid] = row["Chapter_ID"]
    return cs_chapter


def main() -> None:
    chapters = load_chapters()
    cs_chapter = load_cognateset_chapters()

    rows = []
    with open(CLDF_DIR / "cognatesets.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cs_id = row["ID"]
            name = row["Name"]
            chapter_id = cs_chapter.get(cs_id)
            rows.append((
                cs_id,
                name,
                normalise_proto_key(name),
                row["Description"] or None,
                canonical_level(row["Level"] or None),
                chapter_id,
                chapters.get(chapter_id) if chapter_id else None,
            ))

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM lpo_cognatesets")
        conn.executemany(
            """INSERT INTO lpo_cognatesets
               (id, name, name_key, description, level, chapter_id, chapter_title)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        count = conn.execute("SELECT COUNT(*) FROM lpo_cognatesets").fetchone()[0]
        conn.execute(
            """UPDATE source_metadata
               SET entry_count = ?, last_updated = datetime('now')
               WHERE source_id = 'lpo'""",
            (count,),
        )
        conn.commit()

    print(f"Imported {count} LPO cognatesets")


if __name__ == "__main__":
    main()
