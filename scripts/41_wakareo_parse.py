"""Parse scraped Wakareo HTML into one JSON file per component dictionary.

  py scripts/41_wakareo_parse.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wakareo_records import parse_record

RAW_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "raw"
OUT_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "parsed"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_source = defaultdict(list)
    skipped = 0

    files = sorted(RAW_DIR.glob("*.html"), key=lambda p: int(p.stem))
    for path in files:
        rec = parse_record(path.read_text(encoding="utf-8"))
        if rec is None:
            skipped += 1
            continue
        rec["wakareo_id"] = int(path.stem)
        by_source[rec["source_id"]].append(rec)

    for source_id, records in sorted(by_source.items()):
        out = OUT_DIR / f"{source_id}.json"
        out.write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"  {source_id:22s} {len(records):6,d} -> {out.name}")
    print(f"\nParsed {len(files):,} files; skipped {skipped:,}.")


if __name__ == "__main__":
    main()
