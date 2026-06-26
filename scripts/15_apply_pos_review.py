"""Apply a reviewed POS CSV back into the std_pos table.

Reads a review CSV (either `docs/POS_REVIEW_atomic.csv` keyed by `atomic_code`, or
`docs/POS_REVIEW.csv` keyed by `raw_pos`) and upserts each row whose `review_en`
and/or `review_mi` column is filled in:

  * canonical_en := review_en  (if given; else existing value is kept)
  * canonical_mi := review_mi  (if given; else NULL)
  * status       := 'reviewed'

Rows with both review columns blank are skipped. Idempotent; safe to re-run.
After applying, rebuild + export so the new labels flow into the entry POS wrap-up:

    py scripts/15_apply_pos_review.py            # default: docs/POS_REVIEW_atomic.csv
    py scripts/15_apply_pos_review.py --csv docs/POS_REVIEW.csv
    py scripts/50_build_unified.py && py scripts/60_export_app_db.py
"""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
DEFAULT_CSV = ROOT / "docs" / "POS_REVIEW_atomic.csv"


def _key_column(fieldnames):
    for cand in ("atomic_code", "raw_pos"):
        if cand in fieldnames:
            return cand
    raise SystemExit(
        f"ERROR: CSV must have an 'atomic_code' or 'raw_pos' column; got {fieldnames}"
    )


def apply_csv(csv_path, db_path=DB_PATH):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise SystemExit(f"ERROR: CSV not found: {csv_path}")

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        key = _key_column(reader.fieldnames or [])
        applied = skipped = 0
        with sqlite3.connect(db_path) as conn:
            for row in reader:
                code = (row.get(key) or "").strip()
                en = (row.get("review_en") or "").strip()
                mi = (row.get("review_mi") or "").strip()
                if not code or (not en and not mi):
                    skipped += 1
                    continue
                exists = conn.execute(
                    "SELECT canonical_en FROM std_pos WHERE raw_pos=?", (code,)
                ).fetchone()
                mi_val = mi or None
                if exists:
                    # keep existing en if review_en blank; set reviewed mi (NULL if blank)
                    en_val = en or exists[0]
                    conn.execute(
                        "UPDATE std_pos SET canonical_en=?, canonical_mi=?, status='reviewed' "
                        "WHERE raw_pos=?",
                        (en_val, mi_val, code),
                    )
                else:
                    conn.execute(
                        "INSERT INTO std_pos (raw_pos, source_counts, total_count, is_loan, "
                        "canonical_en, canonical_mi, status, notes) "
                        "VALUES (?, '{}', 0, 0, ?, ?, 'reviewed', 'from POS review CSV')",
                        (code, en or None, mi_val),
                    )
                applied += 1
            conn.commit()
    print(f"Applied {applied} reviewed POS rows from {csv_path.name} (skipped {skipped} blank).")


def main():
    ap = argparse.ArgumentParser(description="Apply reviewed POS CSV into std_pos")
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="path to the filled review CSV")
    args = ap.parse_args()
    apply_csv(args.csv)


if __name__ == "__main__":
    main()
