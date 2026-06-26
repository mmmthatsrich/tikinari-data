"""
Merges website-scraped data into papakupu_entries.json, then re-imports to DB.

Adds:
  1.  9 headwords found in the archived website (A/K/P sections) but missing
      from the PDF-parsed JSON.
  2.  682 WRRT-TAPEHA terminology entries (kupu hou with English equivalents).

Saves:
  sources/papakupu/parsed/papakupu_sources.json
      Expanded source-code → description mapping from Abbr_Sources.htm.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from utils import normalise_sort_key, normalise_search_key

ROOT       = Path(__file__).parent.parent
DB_PATH    = ROOT / "data" / "staging_dictionary.db"
PAKU_JSON  = ROOT / "sources" / "papakupu" / "parsed" / "papakupu_entries.json"
WEB_JSON   = ROOT / "sources" / "papakupu" / "website" / "website_entries.json"
ABBR_JSON  = ROOT / "sources" / "papakupu" / "website" / "abbr_sources.json"
SOURCES_OUT = ROOT / "sources" / "papakupu" / "parsed" / "papakupu_sources.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def papakupu_row(e: dict, *, pdf_page=None) -> dict:
    """Convert a website entry dict to the papakupu_entries.json schema."""
    return {
        "headword":      e["headword"],
        "sense_number":  e.get("sense_number"),
        "variant_forms": e.get("variant_forms") or [],
        "source_code":   e.get("source_code") or None,
        "loan_marker":   None,
        "part_of_speech": e.get("part_of_speech") or None,
        "definition":    clean_definition(e.get("definition") or ""),
        "usage_examples": [],
        "see_also":      [],
        "pdf_page":      pdf_page,
    }


# Patterns that indicate bleed-through from adjacent entries
_BLEED_RE = re.compile(
    r'\s+(?:[a-zāēīōūA-ZĀĒĪŌŪ][a-zāēīōūA-ZĀĒĪŌŪ]+\s+v\.\s|'  # "koreto v. cry"
    r'[a-zāēīōū]{2,}\s+\[\d+\]\s+\[)'                           # "kori [1] ["
)


def clean_definition(text: str) -> str:
    """Strip bleed-through from adjacent entries and tidy whitespace."""
    m = _BLEED_RE.search(text)
    if m:
        text = text[:m.start()].rstrip(" ,.")
    return re.sub(r'\s+', ' ', text).strip()


# ---------------------------------------------------------------------------
# 1. Load existing JSON and build headword lookup
# ---------------------------------------------------------------------------

existing: list[dict] = json.loads(PAKU_JSON.read_text(encoding="utf-8"))
existing_hw = {e["headword"].lower().strip() for e in existing}
print(f"Existing entries: {len(existing)}")

# ---------------------------------------------------------------------------
# 2. Load website entries
# ---------------------------------------------------------------------------

web_entries: list[dict] = json.loads(WEB_JSON.read_text(encoding="utf-8"))
main_entries = [e for e in web_entries if not e["website_page"].upper().startswith("WRRT")]
wrrt_entries = [e for e in web_entries if e["website_page"].upper().startswith("WRRT")]

# ---------------------------------------------------------------------------
# 3. 9 dictionary gaps (A / K / P main pages)
# ---------------------------------------------------------------------------

gap_entries = [
    e for e in main_entries
    if e.get("headword") and e["headword"].lower().strip() not in existing_hw
]
print(f"\nGap entries to add: {len(gap_entries)}")
new_dict_rows = []
for e in gap_entries:
    row = papakupu_row(e)
    print(f"  + {row['headword']!r:45s} [{row['part_of_speech']}]")
    new_dict_rows.append(row)

# ---------------------------------------------------------------------------
# 4. WRRT-TAPEHA terminology entries
# ---------------------------------------------------------------------------

# Deduplicate by (headword.lower, definition.lower) — same term appears
# under multiple source codes for different subject domains
seen_wrrt: set[tuple] = set()
new_wrrt_rows = []
for e in wrrt_entries:
    hw  = (e.get("headword") or "").strip()
    defn = (e.get("definition") or "").strip()
    if not hw or not defn:
        continue
    key = (hw.lower(), defn.lower())
    if key in seen_wrrt:
        continue
    seen_wrrt.add(key)
    new_wrrt_rows.append(papakupu_row(e))

print(f"\nWRRT-TAPEHA terminology entries to add: {len(new_wrrt_rows)}")

# ---------------------------------------------------------------------------
# 5. Merge and write updated JSON
# ---------------------------------------------------------------------------

updated = existing + new_dict_rows + new_wrrt_rows
PAKU_JSON.write_text(
    json.dumps(updated, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"\nUpdated papakupu_entries.json → {len(updated)} total entries")

# ---------------------------------------------------------------------------
# 6. Save expanded abbreviations / sources reference
# ---------------------------------------------------------------------------

abbr: dict = json.loads(ABBR_JSON.read_text(encoding="utf-8"))

# Enrich the source_codes dict with known context from the existing JSON
# (codes that appear in the data but weren't on the abbreviations page)
data_codes = {
    e["source_code"] for e in updated
    if e.get("source_code") and "/" not in (e.get("source_code") or "")
}
known_codes = set(abbr.get("source_codes", {}).keys())
undocumented = sorted(data_codes - known_codes)

sources_out = {
    "description": (
        "Source codes, example-sentence informant codes, and POS abbreviations "
        "from Te Papakupu o Te Tai Tokerau — Abbr_Sources.htm (archived 2017-11-01)"
    ),
    "source_codes":       abbr.get("source_codes", {}),
    "example_sources":    abbr.get("example_sources", {}),
    "pos_abbreviations":  abbr.get("pos_abbreviations", {}),
    "undocumented_codes": undocumented,
}
SOURCES_OUT.write_text(
    json.dumps(sources_out, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"Saved abbreviations → {SOURCES_OUT}")
print(f"  {len(sources_out['source_codes'])} source codes documented")
print(f"  {len(sources_out['example_sources'])} example-source codes documented")
print(f"  {len(undocumented)} codes in data but undocumented: {undocumented[:10]}")

# ---------------------------------------------------------------------------
# 7. Re-import into SQLite
# ---------------------------------------------------------------------------

print(f"\nRe-importing into {DB_PATH} ...")

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
    conn.execute(
        "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now')"
        " WHERE source_id = 'papakupu'",
        (len(rows),),
    )
    return len(rows)

with sqlite3.connect(DB_PATH) as conn:
    count = import_papakupu(conn, updated)
    conn.commit()

print(f"Imported {count} entries into papakupu_entries table")
print("\nDone.")
