"""Export the app-serving database (data/maori_dict.db) from the working
staging database (data/staging_dictionary.db).

WHY TWO DATABASES
-----------------
`staging_dictionary.db` is the full working DB: every scraper / importer /
`50_build_unified.py` writes here (raw `*_entries`, cross-source candidates,
`std_pos`, the unified core, AND the etymology layer). It is large (~210 MB)
and is NEVER copied out of this repo.

`maori_dict.db` is a CLEAN, SMALL projection containing ONLY the surface the
app reads. THIS is the file that gets copied to the app repo. Regenerating it
is one command — so the bloated staging DB never has to travel.

WHAT GOES IN THE APP DB
-----------------------
  * Unified core ....... entry, form, sense, example, relation, entry_domain
                         (+ entry_fts / sense_fts / example_fts, rebuilt)
  * Etymology layer .... pollex_cognatesets, pollex_reflexes, pollex_languages,
                         lpo_cognatesets, acd_cognatesets, etymology_links,
                         protoform_ancestry, reconstruction_levels,
                         pollex_entry_links
  * Support ............ source_abbreviations, source_metadata

Everything else (the raw `*_entries` landing zone, `pollex_entries`,
cross-source candidates, refresh logs, the personal lexicon, `std_pos`) stays
in staging only.

The export is schema-driven: object DDL is pulled from staging's `sqlite_master`
so the app DB never drifts from the source schema. Run it after any build:

    py scripts/60_export_app_db.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).parent.parent / "data"
STAGING  = DATA_DIR / "staging_dictionary.db"
APP_DB   = DATA_DIR / "maori_dict.db"

# Real (non-FTS) tables copied verbatim into the app DB, in FK-safe create order
# (parents before children).
APP_TABLES = [
    "source_metadata",
    "source_abbreviations",
    "entry",
    "form",
    "sense",
    "example",
    "relation",
    "entry_domain",
    "pollex_cognatesets",
    "pollex_languages",
    "pollex_reflexes",
    "lpo_cognatesets",
    "acd_cognatesets",
    "etymology_links",
    "reconstruction_levels",
    "protoform_ancestry",
    "pollex_entry_links",
]

# FTS5 virtual tables rebuilt from their content tables after the copy.
APP_FTS = ["entry_fts", "sense_fts", "example_fts"]


def _ddl(stg, name):
    row = stg.execute(
        "SELECT sql FROM sqlite_master WHERE name = ? AND sql IS NOT NULL", (name,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"ERROR: object '{name}' not found in {STAGING.name}")
    return row[0]


def export():
    if not STAGING.exists():
        raise SystemExit(
            f"ERROR: staging DB not found: {STAGING}\n"
            f"Run the importers + 50_build_unified.py first."
        )

    # Fresh app DB every time — fully reproducible projection.
    for suffix in ("", "-wal", "-shm"):
        p = APP_DB.parent / (APP_DB.name + suffix)
        if p.exists():
            p.unlink()

    stg = sqlite3.connect(STAGING)
    out = sqlite3.connect(APP_DB)
    out.execute("PRAGMA journal_mode = WAL")
    out.execute("PRAGMA foreign_keys = OFF")
    out.execute("ATTACH DATABASE ? AS stg", (str(STAGING),))

    app_objs = set(APP_TABLES) | set(APP_FTS)
    print(f"Building {APP_DB.name} from {STAGING.name}")

    # 1. real tables — create from staging DDL, then copy rows
    for t in APP_TABLES:
        out.execute(_ddl(stg, t))
        out.execute(f'INSERT INTO main."{t}" SELECT * FROM stg."{t}"')
        cnt = out.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
        print(f"  table  {t:<22} {cnt:>8,} rows")

    # 2. FTS virtual tables — create then rebuild from content
    for f in APP_FTS:
        out.execute(_ddl(stg, f))
    for f in APP_FTS:
        out.execute(f'INSERT INTO "{f}"("{f}") VALUES (\'rebuild\')')
        print(f"  fts    {f:<22} rebuilt")

    # 3. indexes + triggers attached to any app object (auto/shadow have sql IS NULL)
    extras = stg.execute(
        "SELECT name, type, tbl_name, sql FROM sqlite_master "
        "WHERE type IN ('index','trigger') AND sql IS NOT NULL"
    ).fetchall()
    for name, typ, tbl, sql in extras:
        if tbl in app_objs:
            out.execute(sql)
            print(f"  {typ:<7} {name}")

    out.commit()
    out.execute("DETACH DATABASE stg")

    # 4. integrity
    ok = out.execute("PRAGMA integrity_check").fetchone()[0]
    fk = out.execute("PRAGMA foreign_key_check").fetchall()
    print(f"  integrity_check: {ok}")
    if fk:
        print(f"  WARNING foreign_key_check found {len(fk)} dangling refs: {fk[:5]}")
    else:
        print("  foreign_key_check: clean")

    out.execute("VACUUM")
    out.close()
    stg.close()

    size_mb = APP_DB.stat().st_size / (1024 * 1024)
    print(f"Done. {APP_DB} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    export()
