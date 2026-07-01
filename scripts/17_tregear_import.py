"""Import parsed Tregear entries + cognates into the staging DB.

Reads sources/tregear/tregear_parsed.json (from 17_tregear_parse.py) and loads:
  tregear_entries  — one row per Maori headword occurrence (homonyms distinguished
                     by homonym_index); headword_norm is the macron/vowel-folded
                     search key used by the S57 ETY_entry_link bridge.
  tregear_cognates — one row per (entry, language) comparative witness.

Idempotent: clears both tables and re-inserts. Tables are declared in
00_init_db.py — run that first. Windows-safe UTF-8 output.

Usage:  py 17_tregear_import.py
"""

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from utils import normalise_search_key  # noqa: E402

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH = Path(__file__).parent.parent / "sources" / "tregear" / "tregear_parsed.json"


def norm_headword(headword: str) -> str:
    """Macron/vowel-folded, space/hyphen-stripped key for the entry bridge.

    'HAERE-AWAAWA' and modern 'haere āwaawa' both fold to 'haereawawa';
    'Whaka-HAERE' -> 'whakahaere'.
    """
    return normalise_search_key(headword.replace("-", "").replace(" ", ""))


def main() -> None:
    entries = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    entry_rows = []
    cognate_rows = []
    homonym = Counter()
    next_id = 1
    for e in entries:
        hw = e["headword"]
        homonym[hw] += 1
        eid = next_id
        next_id += 1
        entry_rows.append((
            eid, hw, norm_headword(hw), homonym[hw],
            e.get("pronunciation"), e.get("gloss_en"),
            e.get("letter"), e.get("tei_ref"), e.get("page_no"),
        ))
        for c in e["cognates"]:
            cognate_rows.append((
                eid, c["language"], c["extra_polynesian"],
                c.get("form"), c.get("gloss"), c["seq"],
            ))

    conn = sqlite3.connect(DB_PATH)
    with conn:
        conn.execute("DELETE FROM tregear_cognates")
        conn.execute("DELETE FROM tregear_entries")
        conn.executemany(
            "INSERT INTO tregear_entries (id, headword, headword_norm, homonym_index, "
            "pronunciation, gloss_en, letter, tei_ref, page_no) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", entry_rows)
        conn.executemany(
            "INSERT INTO tregear_cognates (tregear_entry_id, language, extra_polynesian, "
            "form, gloss, seq) VALUES (?, ?, ?, ?, ?, ?)", cognate_rows)
        conn.execute(
            "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now') "
            "WHERE source_id = 'tregear'", (len(entry_rows),))

    homonym_groups = sum(1 for v in homonym.values() if v > 1)
    print("Tregear import complete")
    print(f"  entries:          {len(entry_rows):,}")
    print(f"  distinct headwords:{len(homonym):,}  ({homonym_groups:,} homonym groups)")
    print(f"  cognates:         {len(cognate_rows):,}")
    print(f"  extra-Polynesian: {sum(1 for r in cognate_rows if r[2]):,}")


if __name__ == "__main__":
    main()
