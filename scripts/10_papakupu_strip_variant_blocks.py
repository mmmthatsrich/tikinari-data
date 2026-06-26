"""Strip inline variant-form blocks (e.g. ``< koohure, kohure >``) from
papakupu_entries.definition.

Background: 02_papakupu_extract.py parsed the ``<...>`` block into the
variant_forms column but never removed it from the definition text, so many
definitions still begin with the duplicated variant list.

Rules (per user request):
  - Take the FIRST ``<...>`` block in the definition (the leading variant block;
    later ``<#>`` markers and run-on sub-entries of OTHER headwords are left alone).
  - If its comma-split contents already equal variant_forms -> delete the block.
  - If variant_forms is empty and the block is a genuine leading Māori-word list
    -> add the forms to variant_forms (and variant_search_keys), then delete it.
  - A small set of OCR-malformed blocks that close with ``]`` instead of ``>``
    are handled explicitly by id (verified by exact text assertion).

Dry-run by default; pass --apply to write. A timestamped DB backup is made before
writing. FTS stays in sync via the papakupu_fts_upd trigger.

Usage:
    py scripts/10_papakupu_strip_variant_blocks.py            # dry-run
    py scripts/10_papakupu_strip_variant_blocks.py --apply    # write changes
"""
import argparse, json, re, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH, normalise_search_key

VARIANT_RE = re.compile(r"<([^>]+)>")
# A genuine variant token: Māori letters (with macrons), spaces, hyphen, apostrophe, '#'.
TOKEN_RE = re.compile(r"^[a-zāēīōūA-ZĀĒĪŌŪ '#\-]+$")

# OCR-malformed blocks that close with ']' instead of '>'. Each: id -> (exact
# substring to remove, list of variant forms). Asserted before editing.
MALFORMED = {
    1062: ("< koomata, komata]", ["koomata", "komata"]),
    3388: ("< tupapaku, tuupaapaku ", ["tupapaku", "tuupaapaku"]),
    3399: ("< tuupuna, tuupuna]", ["tuupuna"]),
}


def tidy(t: str) -> str:
    t = re.sub(r"[ \t]{2,}", " ", t)     # collapse runs of spaces/tabs (keep newlines)
    t = re.sub(r"^[\s:;,.]+", "", t)     # strip leading whitespace / dangling separators
    t = re.sub(r"[ \t]+\n", "\n", t)     # trailing spaces before a newline
    return t.strip()


def looks_like_variants(forms: list[str]) -> bool:
    return bool(forms) and all(TOKEN_RE.match(f) for f in forms)


def keys_for(forms: list[str]) -> list[str]:
    return list({normalise_search_key(v) for v in forms})


def plan_row(id_, definition, vf):
    """Return (new_def, new_vf|None, action) or None if nothing to do."""
    if id_ in MALFORMED:
        sub, forms = MALFORMED[id_]
        if sub not in definition:
            raise SystemExit(f"id {id_}: expected substring not found: {sub!r}")
        new_def = tidy(definition.replace(sub, "", 1))
        return new_def, forms, "add+strip(malformed)"

    m = VARIANT_RE.search(definition)
    if not m:
        return None
    inner = [v.strip() for v in m.group(1).split(",") if v.strip()]
    new_def = tidy(definition[:m.start()] + definition[m.end():])

    if vf and inner == vf:
        return new_def, None, "strip"
    if not vf and m.start() < 60 and looks_like_variants(inner):
        return new_def, inner, "add+strip"
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT id, definition, variant_forms FROM papakupu_entries "
        "WHERE definition LIKE '%<%'"
    ).fetchall()

    updates = []          # (id, new_def, new_vf|None, new_keys|None)
    counts = {"strip": 0, "add+strip": 0, "add+strip(malformed)": 0}
    emptied = []
    for id_, d, vf_json in rows:
        if d is None:
            continue
        vf = json.loads(vf_json) if vf_json else []
        res = plan_row(id_, d, vf)
        if res is None:
            continue
        new_def, new_vf, action = res
        counts[action] += 1
        keys = keys_for(new_vf) if new_vf is not None else None
        updates.append((id_, new_def, new_vf, keys))
        if not new_def.strip():
            emptied.append(id_)

    print(f"rows with '<' scanned: {len(rows)}")
    print(f"definitions to change: {len(updates)}")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"definitions emptied by strip: {len(emptied)} -> {emptied}")

    if not args.apply:
        print("\nsample (first 8):")
        for id_, nd, nvf, _ in updates[:8]:
            extra = f"  +vf={nvf}" if nvf is not None else ""
            print(f"  id {id_}: {nd[:70]!r}{extra}")
        print("\nDRY-RUN. Re-run with --apply to write.")
        con.close()
        return

    backup = Path(str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-varstrip")
    shutil.copy2(DB_PATH, backup)
    print(f"\nbackup written: {backup}")

    now = datetime.now(timezone.utc).isoformat()
    for id_, nd, nvf, keys in updates:
        if nvf is None:
            con.execute(
                "UPDATE papakupu_entries SET definition=?, last_updated=? WHERE id=?",
                (nd, now, id_),
            )
        else:
            con.execute(
                "UPDATE papakupu_entries SET definition=?, variant_forms=?, "
                "variant_search_keys=?, last_updated=? WHERE id=?",
                (nd, json.dumps(nvf, ensure_ascii=False),
                 json.dumps(keys, ensure_ascii=False), now, id_),
            )
    con.commit()

    # verify: no row we touched should still start with a leading variant block
    remaining = 0
    for id_, nd, _, _ in updates:
        cur = con.execute(
            "SELECT definition FROM papakupu_entries WHERE id=?", (id_,)
        ).fetchone()[0]
        m = VARIANT_RE.search(cur or "")
        if m and m.start() < 60:
            remaining += 1
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"applied {len(updates)} updates. leading blocks remaining: {remaining}")
    print(f"integrity_check: {integrity}")
    con.close()


if __name__ == "__main__":
    main()
