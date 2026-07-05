"""Import ACD (Austronesian Comparative Dictionary) cognatesets into acd_cognatesets.

Source: sources/acd/cldf/cognatesets.csv  (~10,857 rows)
Level and form are embedded in the Name field: e.g. "PMP *abaw 'high, lofty'"
Etymon_ID groups related reconstructions (a PMP and its derived forms share an etymon).
"""

import csv
import re
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))
from utils import canonical_level, normalise_proto_key

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
CLDF_DIR = Path(__file__).parent.parent / "sources" / "acd" / "cldf"

# Matches: LEVEL *?FORM 'DESCRIPTION'
# Non-greedy form group handles multi-word forms like "abal abal".
NAME_PAT = re.compile(r"^(P\w+)\s+\*?(.+?)\s+'(.+)'$")


def parse_name(name: str) -> tuple[str, str, str | None]:
    """Return (level, form, description) parsed from ACD Name field."""
    m = NAME_PAT.match(name.strip())
    if not m:
        return ("", name.strip(), None)
    return m.group(1), m.group(2), m.group(3)


def main() -> None:
    rows = []
    unmatched = 0
    with open(CLDF_DIR / "cognatesets.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            level, form, description = parse_name(row["Name"])
            if not level:
                unmatched += 1
            rows.append((
                row["ID"],
                form,
                normalise_proto_key(form),
                description,
                canonical_level(level) or None,
                row["Etymon_ID"] or None,
            ))

    if unmatched:
        print(f"Warning: {unmatched} rows did not match name pattern")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM acd_cognatesets")
        conn.executemany(
            """INSERT INTO acd_cognatesets
               (id, name, name_key, description, level, etymon_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        count = conn.execute("SELECT COUNT(*) FROM acd_cognatesets").fetchone()[0]
        conn.execute(
            """UPDATE source_metadata
               SET entry_count = ?, last_updated = datetime('now')
               WHERE source_id = 'acd'""",
            (count,),
        )
        conn.commit()

    print(f"Imported {count} ACD cognatesets")

    # Spot-check level distribution
    with sqlite3.connect(DB_PATH) as conn:
        rows_check = conn.execute(
            "SELECT level, COUNT(*) FROM acd_cognatesets GROUP BY level ORDER BY COUNT(*) DESC"
        ).fetchall()
    print("Level distribution:")
    for level, n in rows_check:
        print(f"  {level}: {n}")


if __name__ == "__main__":
    main()
