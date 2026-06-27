"""Dump the expert-reviewed POS decisions from std_pos to a committed seed file.

std_pos lives in the git-ignored working DB, so the reviewer's canonical_en /
canonical_mi / not_pos decisions would be lost on a from-scratch rebuild. This dumps
those decisions (status in 'reviewed' / 'not_pos') to `seeds/std_pos_seed.csv`, which
IS committed. `13_build_pos_normalisation.py` auto-loads that file (fill-only) so the
decisions survive a from-empty rebuild.

Run after each review session, then commit the updated CSV:
    py scripts/16_dump_std_pos_seed.py
    git add seeds/std_pos_seed.csv && git commit -m "data: refresh POS seed"
"""
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
SEED_CSV = ROOT / "seeds" / "std_pos_seed.csv"
FIELDS = ["raw_pos", "canonical_en", "canonical_mi", "status", "notes"]


def dump(db_path=DB_PATH, out=SEED_CSV):
    out.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT raw_pos, canonical_en, canonical_mi, status, notes FROM std_pos "
            "WHERE status IN ('reviewed','not_pos') AND TRIM(COALESCE(raw_pos,''))!='' "
            "ORDER BY raw_pos"
        ).fetchall()
    clean = []
    for raw, en, mi, st, notes in rows:
        clean.append({
            "raw_pos": (raw or "").strip(),
            "canonical_en": (en or "").strip(),
            "canonical_mi": (mi or "").strip(),
            "status": (st or "").strip(),
            "notes": (notes or "").strip(),
        })
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(clean)
    nrev = sum(1 for r in clean if r["status"] == "reviewed")
    nnot = sum(1 for r in clean if r["status"] == "not_pos")
    print(f"wrote {out.relative_to(ROOT)}: {len(clean)} rows (reviewed={nrev}, not_pos={nnot})")


if __name__ == "__main__":
    dump()
