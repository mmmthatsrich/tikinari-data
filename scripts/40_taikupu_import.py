"""Imports the TaiKupu dictionary into taikupu_entries and rebuilds FTS.

TaiKupu (a Ngapuhi vocab app inside the Maori Minute platform) serves its whole
dataset from a single public, no-auth JSON endpoint:

    GET https://maoriminute.com/api/dictionary          -> {version, updatedAt, count, entries:[...]}
    GET https://maoriminute.com/api/dictionary/version   -> {version, updatedAt}   (cheap change check)

Each entry: {id, maori, english, partOfSpeech, example, exampleTranslation,
             category, notes, level, createdAt, updatedAt, levelOverride?}.
partOfSpeech and category are present but currently always empty.

The raw payload lives at sources/taikupu/raw/taikupu_dictionary.json. Content is
used with the owner's permission and is shown in-app under the Papakupu banner.

Usage:
    py scripts/40_taikupu_import.py                 # import the saved raw JSON
    py scripts/40_taikupu_import.py --download       # refresh raw JSON from the API first, then import
    py scripts/40_taikupu_import.py --version-check   # compare local vs live version and exit
"""

import argparse
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import normalise_sort_key, normalise_search_key, compute_content_hash

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
RAW_PATH = (
    Path(__file__).parent.parent / "sources" / "taikupu" / "raw" / "taikupu_dictionary.json"
)
API_URL = "https://maoriminute.com/api/dictionary"
VERSION_URL = "https://maoriminute.com/api/dictionary/version"


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "maori-dict-db/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def download() -> dict:
    """Fetch the full dataset from the API and write it to RAW_PATH."""
    data = _fetch(API_URL)
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  downloaded version {data.get('version')} "
          f"({data.get('count')} entries) -> {RAW_PATH.name}")
    return data


def version_check() -> None:
    live = _fetch(VERSION_URL)
    local = json.loads(RAW_PATH.read_text(encoding="utf-8")) if RAW_PATH.exists() else {}
    lv, cv = local.get("version"), live.get("version")
    print(f"  local  version: {lv}")
    print(f"  live   version: {cv}  (updatedAt {live.get('updatedAt')})")
    print("  -> up to date" if lv == cv else "  -> UPDATE AVAILABLE (run with --download)")


def import_taikupu(conn: sqlite3.Connection, data: dict) -> int:
    entries = data["entries"]
    conn.execute("DELETE FROM taikupu_entries")

    rows = []
    for e in entries:
        hw = e["maori"]
        english = (e.get("english") or "").strip() or None
        example = (e.get("example") or "").strip()
        example_tr = (e.get("exampleTranslation") or "").strip()
        # Bilingual example stored in the shared {text_mi, text_en} shape (as Papakupu).
        examples = (
            [{"text_mi": example or None, "text_en": example_tr or None}]
            if (example or example_tr) else []
        )
        material = {"hw": hw, "def": english, "ex": examples, "lvl": e.get("level")}
        rows.append((
            e["id"],
            hw,
            normalise_sort_key(hw),
            normalise_search_key(hw),
            (e.get("partOfSpeech") or "").strip() or None,
            english,
            json.dumps(examples, ensure_ascii=False),
            e.get("level"),
            (e.get("notes") or "").strip() or None,
            compute_content_hash(material),
        ))

    conn.executemany(
        """INSERT INTO taikupu_entries
               (source_entry_id, headword, headword_sort, headword_search,
                part_of_speech, definition, usage_examples, level, notes, content_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.execute("INSERT INTO taikupu_fts(taikupu_fts) VALUES ('rebuild')")

    count = len(rows)
    conn.execute(
        "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now')"
        " WHERE source_id = 'taikupu'",
        (count,),
    )
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Import the TaiKupu dictionary.")
    ap.add_argument("--download", action="store_true",
                    help="refresh the raw JSON from the API before importing")
    ap.add_argument("--version-check", action="store_true",
                    help="compare local vs live version and exit (no import)")
    args = ap.parse_args()

    if args.version_check:
        version_check()
        return

    data = download() if args.download else json.loads(
        RAW_PATH.read_text(encoding="utf-8"))

    with sqlite3.connect(DB_PATH) as conn:
        n = import_taikupu(conn, data)
        conn.commit()
    print(f"  imported {n} taikupu entries (version {data.get('version')})")


if __name__ == "__main__":
    main()
