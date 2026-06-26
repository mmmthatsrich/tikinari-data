"""
Curation tool for Maunsell and He Karao OCR entries.

Three modes:

  INTERACTIVE (default)
    py scripts/25c_curate.py --source maunsell
    py scripts/25c_curate.py --source maunsell --skip-name-only --alphabetical
    py scripts/25c_curate.py --source hekarao --min-conf 50

    Controls:
      [text] + Enter  ->  approve with that modern headword
      Enter alone     ->  skip (review later)
      d + Enter       ->  discard (never import)
      q + Enter       ->  quit and save progress
      ? + Enter       ->  show full definition

  EXPORT CSV (for spreadsheet curation)
    py scripts/25c_curate.py --source maunsell --export-csv
    py scripts/25c_curate.py --source hekarao  --export-csv

    Writes sources/{source}/curated/{source}_curation.csv.
    Columns: id, ocr_headword, [pos/ocr_conf], definition, page_ref,
             ocr_flags, modern_headword, discard, notes
    Fill in modern_headword (with macrons) OR put "y" in discard.
    Entries already decided in the JSON are prefilled.

  IMPORT CSV (read back filled spreadsheet)
    py scripts/25c_curate.py --source maunsell --import-csv sources/maunsell/curated/maunsell_curation.csv
    py scripts/25c_curate.py --source hekarao  --import-csv sources/hekarao/curated/hekarao_curation.csv

    Merges CSV decisions into the curation JSON.
    modern_headword filled -> approved; discard=="y" -> discarded; else skipped.

Curation JSON is saved after every interactive decision. Safe to quit at any time.
"""

import sys, json, argparse, csv
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent.parent

PARSED = {
    "maunsell": BASE / "sources" / "maunsell" / "parsed" / "maunsell_entries.json",
    "hekarao":  BASE / "sources" / "hekarao"  / "parsed" / "hekarao_entries.json",
}
CURATED = {
    "maunsell": BASE / "sources" / "maunsell" / "curated" / "maunsell_curation.json",
    "hekarao":  BASE / "sources" / "hekarao"  / "curated" / "hekarao_curation.json",
}

DIVIDER = "-" * 55


def load_curation(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_curation(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stats(curation: dict, total: int) -> tuple[int, int, int]:
    approved  = sum(1 for v in curation.values() if v["status"] == "approved")
    discarded = sum(1 for v in curation.values() if v["status"] == "discarded")
    pending   = total - approved - discarded
    return approved, discarded, pending


def format_maunsell(entry: dict) -> tuple[str, str]:
    """Return (short_display, full_display) for a Maunsell entry."""
    pos  = f"  pos: {entry['part_of_speech']}" if entry["part_of_speech"] else ""
    page = f"Page {entry['book_page']}" if entry["book_page"] else f"PDF p{entry['pdf_page']}"
    defn = (entry["definition"] or "").strip()
    short = (
        f"{DIVIDER}\n"
        f"{page}{pos}\n"
        f"OCR:  \"{entry['headword']}\"\n"
        f"Def:  {defn[:80]}{'...' if len(defn) > 80 else ''}"
    )
    full = (
        f"{DIVIDER}\n"
        f"{page}{pos}\n"
        f"OCR:  \"{entry['headword']}\"\n"
        f"Def:  {defn}"
    )
    if entry.get("usage_examples"):
        full += "\nEx:   " + " / ".join(entry["usage_examples"][:2])
    return short, full


def format_hekarao(entry: dict) -> tuple[str, str]:
    """Return (short_display, full_display) for a He Karao entry."""
    defn = (entry["definition"] or "(no gloss)").strip()
    conf = entry.get("ocr_conf", 0)
    sect = entry.get("section", "")
    display = (
        f"{DIVIDER}\n"
        f"PDF p{entry['pdf_page']}  [{sect}]  conf={conf:.0f}\n"
        f"OCR:  \"{entry['headword']}\"\n"
        f"Def:  {defn[:80]}{'...' if len(defn) > 80 else ''}"
    )
    full = (
        f"{DIVIDER}\n"
        f"PDF p{entry['pdf_page']}  [{sect}]  conf={conf:.0f}\n"
        f"OCR:  \"{entry['headword']}\"\n"
        f"Def:  {defn}"
    )
    return display, full


def run(source: str, min_conf: float, skip_name_only: bool, alphabetical: bool) -> None:
    entries  = json.loads(PARSED[source].read_text(encoding="utf-8"))
    cur_path = CURATED[source]
    curation = load_curation(cur_path)

    # Build work list: indices of entries not yet decided
    work = []
    for i, entry in enumerate(entries):
        key = str(i)
        if key in curation:
            continue  # already approved or discarded
        if source == "maunsell" and skip_name_only and entry.get("is_name_only"):
            continue
        if source == "hekarao" and entry.get("ocr_conf", 0) < min_conf:
            continue
        work.append(i)

    if alphabetical:
        work.sort(key=lambda i: entries[i]["headword"].lower())

    total = len(entries)
    approved, discarded, pending = stats(curation, total)
    print(f"\nSource: {source}  |  Total entries: {total}")
    print(f"Approved: {approved}  Discarded: {discarded}  Pending: {pending}")
    print(f"This session queue: {len(work)} entries\n")

    if not work:
        print("Nothing left to curate with these filters. Done.")
        return

    fmt = format_maunsell if source == "maunsell" else format_hekarao
    session_approved = session_discarded = session_skipped = 0

    for pos, idx in enumerate(work, 1):
        entry   = entries[idx]
        short_d, full_d = fmt(entry)

        print(short_d)
        prompt = f"\n[{pos}/{len(work)}] Modern Maori form  [Enter=skip  d=discard  q=quit  ?=more]: "

        while True:
            try:
                raw = input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                raw = "q"

            if raw == "q":
                save_curation(cur_path, curation)
                approved, discarded, pending = stats(curation, total)
                print(f"\nSession: +{session_approved} approved  +{session_discarded} discarded  {session_skipped} skipped")
                print(f"Overall: {approved} approved  {discarded} discarded  {pending} pending of {total}")
                print(f"Saved to {cur_path}")
                return

            if raw == "?":
                print(full_d)
                continue

            if raw.lower() == "d":
                curation[str(idx)] = {"modern_headword": None, "status": "discarded"}
                save_curation(cur_path, curation)
                session_discarded += 1
                print("  Discarded.")
            elif raw == "":
                session_skipped += 1
                print("  Skipped.")
            else:
                curation[str(idx)] = {"modern_headword": raw, "status": "approved"}
                save_curation(cur_path, curation)
                session_approved += 1
                print(f"  Approved: {raw!r}")

            print()
            break  # next entry

    # Reached end of queue
    save_curation(cur_path, curation)
    approved, discarded, pending = stats(curation, total)
    print(f"\n{DIVIDER}")
    print("Queue complete for this session.")
    print(f"Session: +{session_approved} approved  +{session_discarded} discarded  {session_skipped} skipped")
    print(f"Overall: {approved} approved  {discarded} discarded  {pending} pending of {total}")
    print(f"Saved to {cur_path}")


def export_csv(source: str) -> None:
    entries  = json.loads(PARSED[source].read_text(encoding="utf-8"))
    cur_path = CURATED[source]
    curation = load_curation(cur_path)

    csv_path = cur_path.parent / f"{source}_curation.csv"
    cur_path.parent.mkdir(parents=True, exist_ok=True)

    if source == "maunsell":
        fieldnames = ["id", "ocr_headword", "pos", "definition", "page_ref",
                      "is_name_only", "ocr_flags", "modern_headword", "discard", "notes"]
    else:
        fieldnames = ["id", "ocr_headword", "ocr_conf", "definition", "pdf_page",
                      "section", "ocr_flags", "modern_headword", "discard", "notes"]

    rows_written = 0
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for i, entry in enumerate(entries):
            key  = str(i)
            rec  = curation.get(key, {})
            mh   = rec.get("modern_headword") or ""
            disc = "y" if rec.get("status") == "discarded" else ""
            flags = ";".join(entry.get("ocr_flags") or [])
            defn = (entry.get("definition") or "").replace("\n", " ").strip()

            if source == "maunsell":
                row = {
                    "id":           i,
                    "ocr_headword": entry["headword"],
                    "pos":          entry.get("part_of_speech") or "",
                    "definition":   defn,
                    "page_ref":     entry.get("book_page") or entry.get("pdf_page") or "",
                    "is_name_only": "y" if entry.get("is_name_only") else "",
                    "ocr_flags":    flags,
                    "modern_headword": mh,
                    "discard":      disc,
                    "notes":        "",
                }
            else:
                row = {
                    "id":           i,
                    "ocr_headword": entry["headword"],
                    "ocr_conf":     f"{entry.get('ocr_conf', 0):.0f}",
                    "definition":   defn,
                    "pdf_page":     entry.get("pdf_page") or "",
                    "section":      entry.get("section") or "",
                    "ocr_flags":    flags,
                    "modern_headword": mh,
                    "discard":      disc,
                    "notes":        "",
                }
            writer.writerow(row)
            rows_written += 1

    print(f"Exported {rows_written} rows to {csv_path}")
    already = sum(1 for v in curation.values() if v.get("status") in ("approved", "discarded"))
    print(f"  ({already} already curated, prefilled from JSON)")


def import_csv(source: str, csv_file: str) -> None:
    cur_path = CURATED[source]
    curation = load_curation(cur_path)
    entries  = json.loads(PARSED[source].read_text(encoding="utf-8"))
    total    = len(entries)

    approved = discarded = skipped = 0
    with open(csv_file, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = row.get("id", "").strip()
            if not key.isdigit():
                continue
            mh   = (row.get("modern_headword") or "").strip()
            disc = (row.get("discard") or "").strip().lower()

            if mh:
                curation[key] = {"modern_headword": mh, "status": "approved"}
                approved += 1
            elif disc == "y":
                curation[key] = {"modern_headword": None, "status": "discarded"}
                discarded += 1
            else:
                skipped += 1

    save_curation(cur_path, curation)
    app2, disc2, pend2 = stats(curation, total)
    print(f"Imported: +{approved} approved  +{discarded} discarded  {skipped} rows unchanged")
    print(f"Overall:  {app2} approved  {disc2} discarded  {pend2} pending of {total}")
    print(f"Saved to {cur_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Curate historical OCR entries with modern Maori headwords.")
    ap.add_argument("--source", required=True, choices=["maunsell", "hekarao"],
                    help="Which source to curate")
    ap.add_argument("--export-csv", action="store_true",
                    help="Export entries to CSV for spreadsheet curation")
    ap.add_argument("--import-csv", metavar="FILE",
                    help="Import a filled curation CSV and update the curation JSON")
    ap.add_argument("--min-conf", type=float, default=50.0,
                    help="He Karao only: skip entries with OCR confidence below this (default 50)")
    ap.add_argument("--skip-name-only", action="store_true",
                    help="Maunsell only: skip name-only entries")
    ap.add_argument("--alphabetical", action="store_true",
                    help="Present entries alphabetically instead of page order")
    args = ap.parse_args()

    if not PARSED[args.source].exists():
        print(f"Parsed file not found: {PARSED[args.source]}")
        sys.exit(1)

    if args.export_csv:
        export_csv(args.source)
    elif args.import_csv:
        import_csv(args.source, args.import_csv)
    else:
        run(args.source, args.min_conf, args.skip_name_only, args.alphabetical)


if __name__ == "__main__":
    main()
