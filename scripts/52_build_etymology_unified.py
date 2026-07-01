"""Build the unified etymology layer (ETY_*) from the raw per-source comparative
tables.  Same stage → unify pattern as 50_build_unified.py, applied to etymology.

This is a pure DB → DB projection.  The raw pollex_*/lpo_*/acd_* tables remain the
curated landing zone; this script reads them and rebuilds:

    ETY_level      <- reconstruction_levels          (reference)
    ETY_language   <- pollex_languages               (reference; POLLEX 67)
    ETY_cognateset <- pollex_cognatesets + lpo_cognatesets + acd_cognatesets
    ETY_reflex     <- pollex_reflexes                (LPO/ACD carry no reflexes in staging)

ETY_link and ETY_entry_link are created by 00_init_db.py but populated later
(S57 folds etymology_links + protoform_ancestry → ETY_link and extends
pollex_entry_links → ETY_entry_link over every source).  S57 also folds in the
Tregear + ABVD projections and the Walworth gap-fill (S58).

Per-source and idempotent: each source's cognateset/reflex slice is deleted and
rebuilt independently.  Reference tables (ETY_level, ETY_language) are POLLEX-derived
and rebuilt on every run.  Run 00_init_db.py first so the ETY_* tables exist.

    py scripts/52_build_etymology_unified.py                  # all sources + parity proof
    py scripts/52_build_etymology_unified.py --source pollex  # one source
    py scripts/52_build_etymology_unified.py --source lpo --source acd
    py scripts/52_build_etymology_unified.py --reset          # wipe all ETY_* then rebuild all

Parity proof (always printed; non-zero exit on mismatch): per-source ETY_cognateset
and ETY_reflex counts must equal the raw source-table counts, and a sampled
per-set reflex-count join must agree with the raw table.  This is what makes the
projection safe to trust before the S59 hard cutover drops the raw tables.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH, normalise_proto_key

# S56 subset — Tregear/ABVD/Walworth join at S57/S58.
SOURCES = ("pollex", "lpo", "acd")
# Delete order matters (FK: ETY_reflex -> ETY_cognateset). Children first.
ETY_TABLES = (
    "ETY_entry_link", "ETY_link", "ETY_reflex", "ETY_cognateset",
    "ETY_language", "ETY_level",
)


def ety_tables_exist(con) -> bool:
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'ETY_*'")}
    return set(ETY_TABLES).issubset(have)


# ── reference tables (POLLEX-derived; rebuilt every run) ─────────────────────

def build_refs(con) -> tuple[int, int]:
    """Rebuild ETY_level + ETY_language from reconstruction_levels + pollex_languages."""
    con.execute("DELETE FROM ETY_level")
    n_lvl = con.execute(
        "INSERT INTO ETY_level (code, name, parent_code, depth_rank) "
        "SELECT code, name, parent_code, depth_rank FROM reconstruction_levels"
    ).rowcount

    con.execute("DELETE FROM ETY_language WHERE source='pollex'")
    n_lang = con.execute(
        "INSERT INTO ETY_language (lang_key, name, iso_code, subgroup, region, country, notes, source) "
        "SELECT language_slug, language, iso_code, subgroup, region, "
        "       country_or_island_group, notes, 'pollex' "
        "FROM pollex_languages"
    ).rowcount
    return n_lvl, n_lang


# ── per-source cognateset + reflex projections ───────────────────────────────

def delete_source_slice(con, source: str) -> int:
    """Delete one source's ETY_reflex + ETY_cognateset rows (reflex first, FK)."""
    n = con.execute("DELETE FROM ETY_reflex WHERE source=?", (source,)).rowcount
    n += con.execute("DELETE FROM ETY_cognateset WHERE source=?", (source,)).rowcount
    return n


def build_pollex(con) -> dict:
    """pollex_cognatesets -> ETY_cognateset; pollex_reflexes -> ETY_reflex."""
    sets = con.execute(
        "SELECT id, protoform_name, level, description, notes, pollex_url "
        "FROM pollex_cognatesets"
    ).fetchall()
    # raw slug -> ETY surrogate id, to wire reflexes
    id_map: dict[str, int] = {}
    for raw_id, protoform, level, desc, notes, url in sets:
        cur = con.execute(
            "INSERT INTO ETY_cognateset "
            "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
            "VALUES ('pollex', ?, ?, ?, ?, ?, NULL, ?, ?, 0)",
            (raw_id, protoform, normalise_proto_key(protoform), level, desc, notes, url))
        id_map[raw_id] = cur.lastrowid

    reflexes = con.execute(
        "SELECT id, cognateset_id, language, language_slug, reflex, gloss, "
        "       source_code, source_author, flags "
        "FROM pollex_reflexes"
    ).fetchall()
    n_reflex = 0
    orphans = 0
    for (rid, cs_id, language, lang_slug, reflex, gloss,
         src_code, src_author, flags) in reflexes:
        ety_set = id_map.get(cs_id)
        if ety_set is None:
            orphans += 1
            continue
        con.execute(
            "INSERT INTO ETY_reflex "
            "(cognateset_id, source, source_ref, lang_key, language, form, gloss, "
            " source_code, source_author, flags, gap_fill) "
            "VALUES (?, 'pollex', ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (ety_set, str(rid), lang_slug, language, reflex, gloss,
             src_code, src_author, flags))
        n_reflex += 1
    return {"cognateset": len(sets), "reflex": n_reflex, "orphan_reflex": orphans}


def build_lpo(con) -> dict:
    """lpo_cognatesets -> ETY_cognateset (no reflexes in staging)."""
    n = con.execute(
        "INSERT INTO ETY_cognateset "
        "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
        "SELECT 'lpo', id, name, name_key, level, description, chapter_id, chapter_title, NULL, 0 "
        "FROM lpo_cognatesets"
    ).rowcount
    return {"cognateset": n, "reflex": 0, "orphan_reflex": 0}


def build_acd(con) -> dict:
    """acd_cognatesets -> ETY_cognateset (no reflexes in staging)."""
    n = con.execute(
        "INSERT INTO ETY_cognateset "
        "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
        "SELECT 'acd', id, name, name_key, level, description, etymon_id, NULL, NULL, 0 "
        "FROM acd_cognatesets"
    ).rowcount
    return {"cognateset": n, "reflex": 0, "orphan_reflex": 0}


BUILDERS = {"pollex": build_pollex, "lpo": build_lpo, "acd": build_acd}

# raw-table row that each ETY source projects from, for the parity proof
RAW_SET_TABLE = {
    "pollex": "pollex_cognatesets",
    "lpo": "lpo_cognatesets",
    "acd": "acd_cognatesets",
}
RAW_REFLEX_TABLE = {"pollex": "pollex_reflexes"}


def build_source(con, source: str) -> dict:
    delete_source_slice(con, source)
    counts = BUILDERS[source](con)
    counts["source"] = source
    return counts


# ── parity proof ─────────────────────────────────────────────────────────────

def _count(con, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def parity_check(con, targets) -> bool:
    """Prove the projection equals the raw source tables. Returns True if all pass."""
    ok = True
    print("\n── parity proof ─────────────────────────────────────────")
    for src in targets:
        raw_sets = _count(con, RAW_SET_TABLE[src])
        ety_sets = con.execute(
            "SELECT COUNT(*) FROM ETY_cognateset WHERE source=?", (src,)).fetchone()[0]
        set_ok = raw_sets == ety_sets
        ok &= set_ok
        print(f"  [{src}] cognateset  raw={raw_sets:>6}  ETY={ety_sets:>6}  "
              f"{'OK' if set_ok else 'MISMATCH'}")

        raw_reflex_tbl = RAW_REFLEX_TABLE.get(src)
        if raw_reflex_tbl:
            raw_ref = _count(con, raw_reflex_tbl)
            ety_ref = con.execute(
                "SELECT COUNT(*) FROM ETY_reflex WHERE source=?", (src,)).fetchone()[0]
            ref_ok = raw_ref == ety_ref
            ok &= ref_ok
            print(f"  [{src}] reflex     raw={raw_ref:>6}  ETY={ety_ref:>6}  "
                  f"{'OK' if ref_ok else 'MISMATCH'}")

    # sampled join proof: for POLLEX, a per-set reflex count must match the raw table.
    if "pollex" in targets:
        row = con.execute(
            "SELECT cs.source_ref, COUNT(r.id) "
            "FROM ETY_cognateset cs JOIN ETY_reflex r ON r.cognateset_id=cs.id "
            "WHERE cs.source='pollex' GROUP BY cs.id ORDER BY COUNT(r.id) DESC LIMIT 1"
        ).fetchone()
        if row:
            raw_slug, ety_n = row
            raw_n = con.execute(
                "SELECT COUNT(*) FROM pollex_reflexes WHERE cognateset_id=?",
                (raw_slug,)).fetchone()[0]
            join_ok = raw_n == ety_n
            ok &= join_ok
            print(f"  [pollex] sampled set '{raw_slug}'  raw reflexes={raw_n}  "
                  f"ETY={ety_n}  {'OK' if join_ok else 'MISMATCH'}")

    print("─────────────────────────────────────────────────────────")
    print("PARITY: PASS" if ok else "PARITY: FAIL")
    return ok


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="Project POLLEX/LPO/ACD into the unified ETY_* etymology layer.")
    ap.add_argument("--source", action="append", choices=SOURCES + ("all",),
                    help="source to (re)project; repeatable. Default: all.")
    ap.add_argument("--reset", action="store_true",
                    help="wipe ALL ETY_* tables first, then rebuild all sources.")
    args = ap.parse_args()

    targets = SOURCES if (not args.source or "all" in args.source) else tuple(
        dict.fromkeys(args.source))

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    if not ety_tables_exist(con):
        con.close()
        sys.exit("ETY_* tables missing. Run:  py scripts/00_init_db.py  first.")

    if args.reset:
        for t in ETY_TABLES:            # FK-safe order (children first)
            con.execute(f"DELETE FROM {t}")
        con.commit()
        targets = SOURCES               # a reset always rebuilds everything
        print("reset: all ETY_* tables cleared")

    n_lvl, n_lang = build_refs(con)
    con.commit()
    print(f"refs: ETY_level {n_lvl}, ETY_language {n_lang}")

    for src in targets:
        c = build_source(con, src)
        con.commit()
        extra = f"  (dropped {c['orphan_reflex']} orphan reflexes)" if c["orphan_reflex"] else ""
        print(f"[{src}] cognateset {c['cognateset']}, reflex {c['reflex']}{extra}")

    passed = parity_check(con, targets)
    con.close()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
