"""Import parsed Te Māra Reo data into the staging DB.

Reads sources/temarareo/temarareo_parsed.json (from 42_temarareo_parse.py) and loads:
  temarareo_entries      — one row per Māori plant name (the unified-core slice).
  temarareo_cognatesets  — one row per PPN-*.html protoform page (ETY_* source).
  temarareo_reflexes     — per-language comparative witnesses for those pages.
  temarareo_chain        — the ordered reconstruction steps behind each page.

The entry set is the union of two things: every Māori name listed in the index's
second column (169 of them), and every TMR-*.html page headword (80). A name with a
page of its own gets that page's definition, species and related names; a name that
only appears in the index keeps the row's note and species, with has_page = 0. The
two are distinguished so the unify step can prefer the fuller record — index-only
names are real, attested names, they just carry less.

Idempotent: clears all four tables and re-inserts. Tables are declared in
00_init_db.py — run that first. Windows-safe UTF-8 output.

Usage:  py 42_temarareo_import.py
"""

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from utils import (normalise_proto_key, normalise_search_key,  # noqa: E402
                   normalise_sort_key)

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
JSON_PATH = (Path(__file__).parent.parent / "sources" / "temarareo"
             / "temarareo_parsed.json")
BASE_URL = "https://www.temarareo.org"


def jdump(value):
    """JSON for a list/dict column, or NULL when empty."""
    return json.dumps(value, ensure_ascii=False) if value else None


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    index_rows = data["index"]
    name_pages = {p["page"]: p for p in data["names"]}

    # --- Māori plant names --------------------------------------------------
    # Index rows first, so a name keeps the stage it is listed under; the page
    # record (when the name is that page's headword) then fills in the detail.
    entries: dict[str, dict] = {}          # search key -> row
    page_claimed: set[str] = set()         # pages already attached to an entry

    def key_of(name: str) -> str:
        return normalise_search_key(name.replace("-", " ").replace("’", "'"))

    for row in index_rows:
        for item in row["maori_names"]:
            name = item["name"].strip()
            if not name:
                continue
            key = key_of(name)
            entry = entries.get(key)
            if entry is None:
                entry = {
                    "headword": name,
                    "homonym_no": item.get("homonym_no"),
                    "variant": item.get("variant"),
                    "definition": None, "note": item.get("note"),
                    "species": list(row["species"]), "related_names": [],
                    "ppn_form": row["ppn_form"], "stage_no": row["stage_no"],
                    "stage_name": row["stage_name"], "page": None, "url": None,
                    "source_entry_id": None, "chain": [],
                }
                entries[key] = entry
            # The index's own note describes the protoform, not this one name, so it
            # is only used when the name has no page of its own (filled in below).
            if row["note"] and not entry["note"]:
                entry["note"] = row["note"]
            for sp in row["species"]:
                if sp not in entry["species"]:
                    entry["species"].append(sp)

            page = item.get("page")
            if not page:
                continue
            rec = name_pages.get(page)
            # Attach a page only to the names it is actually about — many names
            # (whara, harakeke, wharariki) link to one page, but only the ones it
            # heads with should inherit its definition. A page covering several
            # related names serves each of them.
            if rec and key in {key_of(h) for h in rec["headwords"]}:
                page_claimed.add(page)
                entry.update({
                    "definition": rec["gloss"], "note": rec["note"],
                    "related_names": rec["related_names"], "page": page,
                    "url": rec["url"], "chain": rec["chain"],
                })
                for sp in rec["species"]:
                    if sp not in entry["species"]:
                        entry["species"].append(sp)

    # Every page headword the index does not already carry.
    for page, rec in sorted(name_pages.items()):
        for name in rec["headwords"]:
            key = key_of(name)
            entry = entries.get(key)
            if entry is None:
                entries[key] = {
                    "headword": name, "homonym_no": None, "variant": None,
                    "definition": rec["gloss"], "note": rec["note"],
                    "species": list(rec["species"]),
                    "related_names": rec["related_names"], "ppn_form": None,
                    "stage_no": None, "stage_name": None, "page": page,
                    "url": rec["url"], "source_entry_id": None,
                    "chain": rec["chain"],
                }
            elif entry["page"] is None:
                entry.update({
                    "definition": rec["gloss"], "note": rec["note"],
                    "related_names": rec["related_names"], "page": page,
                    "url": rec["url"], "chain": rec["chain"],
                })
        page_claimed.add(page)

    # A page serving several names gives its stem to the first and a name-qualified
    # id to the rest, so source_entry_id stays unique and still traces to the page.
    page_primary = {}
    for _, e in sorted(entries.items()):
        if e["page"]:
            page_primary.setdefault(e["page"], normalise_sort_key(e["headword"]))

    entry_rows, entry_chain = [], []
    for eid, (_, e) in enumerate(sorted(entries.items()), start=1):
        if e["page"]:
            stem = Path(e["page"]).stem
            sort_key = normalise_sort_key(e["headword"])
            seid = stem if page_primary.get(e["page"]) == sort_key else f"{stem}:{sort_key}"
        else:
            seid = f"idx:{e['ppn_form'] or '-'}:{normalise_sort_key(e['headword'])}"
        e["source_entry_id"] = seid
        entry_rows.append((
            eid, seid, e["headword"],
            normalise_sort_key(e["headword"]), normalise_search_key(e["headword"]),
            e.get("homonym_no"), e.get("variant"),
            e["definition"], e["note"], jdump(e["species"]),
            jdump(e["related_names"]), e["ppn_form"], e["stage_no"], e["stage_name"],
            e["page"], e["url"] or (f"{BASE_URL}/{e['page']}" if e["page"] else None),
            1 if e["page"] else 0,
        ))
        for seq, step in enumerate(e["chain"]):
            entry_chain.append((None, eid, seq, step["level_code"], step["level_name"],
                                step["form"], step["proto_key"], step["gloss"]))

    # --- protoform pages -----------------------------------------------------
    set_rows, reflex_rows, set_chain = [], [], []
    for cid, rec in enumerate(data["protoforms"], start=1):
        banners = rec["protoforms"]
        primary = banners[0] if banners else {}
        protoform = primary.get("form") or rec["headword"]
        set_rows.append((
            cid, rec["page"], protoform, normalise_proto_key(protoform),
            primary.get("level_code"), primary.get("level_name"), rec["gloss"],
            jdump(rec["species"]), rec["related_words"], rec["further_info"],
            rec["url"], jdump(banners[1:]), 1 if rec["under_construction"] else 0,
        ))
        for seq, r in enumerate(rec["reflexes"] + rec["cognates"]):
            reflex_rows.append((cid, r["language"], r["qualifier"], r["form"],
                                r["gloss"], r["kind"], seq))
        for seq, step in enumerate(rec["chain"]):
            set_chain.append((cid, None, seq, step["level_code"], step["level_name"],
                              step["form"], step["proto_key"], step["gloss"]))

    # Reflexes recorded on a Māori-name page are attached to the protoform page it
    # descends from, so every comparative witness hangs off a cognateset.
    set_by_key = {}
    for cid, rec in enumerate(data["protoforms"], start=1):
        for banner in rec["protoforms"]:
            set_by_key.setdefault(normalise_proto_key(banner["form"]), cid)

    next_cid = len(set_rows) + 1
    seq_by_set: dict[int, int] = defaultdict(int)
    for row in reflex_rows:
        seq_by_set[row[0]] += 1

    derived_sets = 0
    for rec in data["names"]:
        witnesses = rec["reflexes"] + rec["cognates"]
        if not witnesses:
            continue
        cid = None
        for banner in rec["protoforms"]:
            cid = set_by_key.get(normalise_proto_key(banner["form"]))
            if cid:
                break
        if cid is None:
            # A name page whose protoform has no PPN page of its own still asserts a
            # cognate set. Give it one keyed on the page's own protoform (the Tregear
            # precedent) rather than dropping its comparative witnesses.
            primary = rec["protoforms"][0] if rec["protoforms"] else {}
            protoform = primary.get("form") or rec["headword"]
            cid = next_cid
            next_cid += 1
            set_rows.append((
                cid, rec["page"], protoform, normalise_proto_key(protoform),
                primary.get("level_code"), primary.get("level_name"), rec["gloss"],
                jdump(rec["species"]), rec["related_words"], rec["further_info"],
                rec["url"], jdump(rec["protoforms"][1:]),
                1 if rec["under_construction"] else 0,
            ))
            set_by_key.setdefault(normalise_proto_key(protoform), cid)
            derived_sets += 1
            for seq, step in enumerate(rec["chain"]):
                set_chain.append((cid, None, seq, step["level_code"],
                                  step["level_name"], step["form"],
                                  step["proto_key"], step["gloss"]))
        for r in witnesses:
            reflex_rows.append((cid, r["language"], r["qualifier"], r["form"],
                                r["gloss"], r["kind"], seq_by_set[cid]))
            seq_by_set[cid] += 1

    chain_rows = set_chain + entry_chain

    conn = sqlite3.connect(DB_PATH)
    with conn:
        for table in ("temarareo_chain", "temarareo_reflexes",
                      "temarareo_cognatesets", "temarareo_entries"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            "INSERT INTO temarareo_entries (id, source_entry_id, headword, "
            "headword_sort, headword_search, homonym_no, variant, definition, note, "
            "species, related_names, ppn_form, stage_no, stage_name, page, url, "
            "has_page) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", entry_rows)
        conn.executemany(
            "INSERT INTO temarareo_cognatesets (id, page, protoform, proto_key, "
            "level_code, level_name, gloss, species, related_words, further_info, url, "
            "variant_protoforms, under_construction) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            set_rows)
        conn.executemany(
            "INSERT INTO temarareo_reflexes (cognateset_id, language, qualifier, form, "
            "gloss, kind, seq) VALUES (?,?,?,?,?,?,?)", reflex_rows)
        conn.executemany(
            "INSERT INTO temarareo_chain (cognateset_id, entry_id, seq, level_code, "
            "level_name, form, proto_key, gloss) VALUES (?,?,?,?,?,?,?,?)", chain_rows)
        conn.execute(
            "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now') "
            "WHERE source_id = 'temarareo'", (len(entry_rows),))

    with_page = sum(1 for r in entry_rows if r[16])
    langs = len({r[1] for r in reflex_rows})
    print("Te Māra Reo import complete")
    print(f"  entries:        {len(entry_rows):,}  "
          f"({with_page:,} with their own page, "
          f"{len(entry_rows) - with_page:,} index-only)")
    print(f"  cognatesets:    {len(set_rows):,}  "
          f"({len(data['protoforms']):,} protoform pages, "
          f"{derived_sets:,} derived from name pages)")
    print(f"  reflexes:       {len(reflex_rows):,}  across {langs:,} languages")
    print(f"    polynesian:   {sum(1 for r in reflex_rows if r[5] == 'polynesian'):,}")
    print(f"    austronesian: {sum(1 for r in reflex_rows if r[5] == 'austronesian'):,}")
    print(f"  chain steps:    {len(chain_rows):,}  "
          f"({len(set_chain):,} protoform, {len(entry_chain):,} name)")


if __name__ == "__main__":
    main()
