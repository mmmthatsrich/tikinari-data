"""Database maintenance utilities for staging_dictionary.db.

Usage:
  py scripts/06_update_tracker.py stats              # entry counts per source
  py scripts/06_update_tracker.py vacuum             # VACUUM + integrity_check
  py scripts/06_update_tracker.py export [outdir]    # export all tables to JSON
"""
import argparse, json, sqlite3, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

sys.stdout.reconfigure(encoding='utf-8')

# Tables tracked in source_metadata: (source_id, table_name)
TRACKED_TABLES = [
    ("williams",           "williams_entries"),
    ("papakupu",           "papakupu_entries"),
    ("pollex",             "pollex_entries"),
    ("pollex_cognatesets", "pollex_cognatesets"),
    ("lpo",                "lpo_cognatesets"),
    ("acd",                "acd_cognatesets"),
    ("te_aka",             "te_aka_entries"),
    ("hepatakakupu",       "hepatakakupu_entries"),
    ("paekupu",            "paekupu_entries"),
    ("personal",           "personal_lexicon"),
]

# Additional tables not tracked in source_metadata
AUX_TABLES = [
    "pollex_reflexes",
    "etymology_links",
    "source_abbreviations",
    "data_refresh_runs",
    "data_refresh_log",
]


def stats(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        meta = {r["source_id"]: dict(r) for r in conn.execute("SELECT * FROM source_metadata")}
        existing = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

        w_src, w_name, w_meta, w_act, w_date = 22, 38, 8, 8, 20
        print()
        print(f"  {'Source':<{w_src}} {'Display name':<{w_name}} "
              f"{'Meta':>{w_meta}} {'Actual':>{w_act}}  {'Last updated':<{w_date}} Status")
        print("  " + "-" * (w_src + w_name + w_meta + w_act + w_date + 12))

        for source_id, table in TRACKED_TABLES:
            m = meta.get(source_id, {})
            display = (m.get("display_name") or source_id)[:w_name]
            meta_count = m.get("entry_count") or 0
            last_updated = m.get("last_updated") or "—"
            if last_updated != "—":
                last_updated = last_updated[:19]

            if table not in existing:
                print(f"  {source_id:<{w_src}} {display:<{w_name}} "
                      f"{'—':>{w_meta}} {'—':>{w_act}}  {last_updated:<{w_date}} MISSING")
                continue

            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if actual == 0 and meta_count == 0:
                status = "empty"
            elif meta_count == actual:
                status = "OK"
            else:
                status = "MISMATCH"
            print(f"  {source_id:<{w_src}} {display:<{w_name}} "
                  f"{meta_count:>{w_meta},} {actual:>{w_act},}  {last_updated:<{w_date}} {status}")

        print()
        print(f"  {'Auxiliary table':<28} {'Rows':>8}")
        print("  " + "-" * 38)
        for table in AUX_TABLES:
            if table not in existing:
                print(f"  {table:<28} {'MISSING':>8}")
                continue
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<28} {n:>8,}")

        db_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"\n  DB file: {db_path}  ({db_mb:.1f} MB)")


def vacuum(db_path=DB_PATH):
    mb_before = db_path.stat().st_size / (1024 * 1024)
    print(f"Before: {mb_before:.1f} MB")
    print("Running VACUUM ...")
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM")
    mb_after = db_path.stat().st_size / (1024 * 1024)
    print(f"After:  {mb_after:.1f} MB  (saved {mb_before - mb_after:.1f} MB)")

    print("Running integrity_check ...")
    with sqlite3.connect(db_path) as conn:
        results = conn.execute("PRAGMA integrity_check").fetchall()
    if results == [("ok",)]:
        print("  integrity_check: ok")
    else:
        print("  integrity_check FAILED:")
        for row in results:
            print(f"    {row[0]}")


def export_all_json(output_dir: str = "backups", db_path=DB_PATH):
    out = Path(output_dir) / datetime.now().strftime("%Y-%m-%d_%H%M")
    out.mkdir(parents=True, exist_ok=True)

    all_tables = (
        [t for _, t in TRACKED_TABLES]
        + AUX_TABLES
        + ["source_metadata"]
    )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

        seen: set[str] = set()
        for table in all_tables:
            if table in seen or table not in existing:
                seen.add(table)
                continue
            seen.add(table)
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
            dest = out / f"{table}.json"
            dest.write_text(
                json.dumps(rows, ensure_ascii=False, separators=(',', ':')),
                encoding="utf-8",
            )
            size_kb = dest.stat().st_size / 1024
            print(f"  {table}: {len(rows):,} rows -> {size_kb:.0f} KB")

    print(f"\nExport complete: {out}")


def main():
    parser = argparse.ArgumentParser(description="staging_dictionary.db maintenance utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="Print entry counts per source")
    sub.add_parser("vacuum", help="VACUUM + integrity_check")
    exp = sub.add_parser("export", help="Export all tables to JSON")
    exp.add_argument("outdir", nargs="?", default="backups",
                     help="Output directory (default: backups/)")
    args = parser.parse_args()

    if args.cmd == "stats":
        stats()
    elif args.cmd == "vacuum":
        vacuum()
    elif args.cmd == "export":
        export_all_json(args.outdir)


if __name__ == "__main__":
    main()
