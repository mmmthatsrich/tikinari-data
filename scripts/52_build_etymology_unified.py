"""Build the unified etymology layer (ETY_*) from the raw per-source comparative
tables.  Same stage → unify pattern as 50_build_unified.py, applied to etymology.

This is a pure DB → DB projection.  The raw pollex_*/lpo_*/acd_*/tregear_*/abvd_*
tables remain the curated landing zone; this script reads them and rebuilds:

    ETY_level      <- reconstruction_levels          (reference)
    ETY_language   <- pollex_languages (+ abvd/tregear langs not in POLLEX)
    ETY_cognateset <- pollex + lpo + acd + tregear + abvd cognatesets
    ETY_reflex     <- pollex_reflexes + tregear cognates + abvd form-judgments
    ETY_link       <- etymology_links + protoform_ancestry + cross-source dedup
    ETY_entry_link <- Māori reflexes of EVERY source -> unified `entry`

Per-source and idempotent: each source's cognateset/reflex slice is deleted and
rebuilt independently.  Reference tables (ETY_level, POLLEX ETY_language) are
rebuilt on every run.  ETY_link / ETY_entry_link / cross-source dedup are GLOBAL
(they span sources) so they are only (re)built on a full run — a partial
`--source X` build leaves them untouched and prints a note.  Run 00_init_db.py
first so the ETY_* tables exist.

    py scripts/52_build_etymology_unified.py                  # all sources + links + parity
    py scripts/52_build_etymology_unified.py --source pollex  # one source (no link rebuild)
    py scripts/52_build_etymology_unified.py --source tregear --source abvd
    py scripts/52_build_etymology_unified.py --reset          # wipe all ETY_* then rebuild all

Parity proof (always printed; non-zero exit on mismatch): per-source ETY_cognateset
and ETY_reflex counts must equal the raw source-table counts (or, for tregear, the
headword + cognate totals), and a sampled per-set reflex-count join must agree with
the raw table.  This is what makes the projection safe to trust before the S59 hard
cutover drops the raw tables.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (DB_PATH, normalise_proto_key, normalise_search_key,
                   normalise_sort_key)

# Walworth joins at S58 (gap-fill only).
SOURCES = ("pollex", "lpo", "acd", "tregear", "abvd")
# Delete order matters (FK: ETY_reflex -> ETY_cognateset). Children first.
ETY_TABLES = (
    "ETY_entry_link", "ETY_link", "ETY_reflex", "ETY_cognateset",
    "ETY_language", "ETY_level",
)

MAORI_KEY = "maori"                       # canonical Māori lang_key (POLLEX slug)

# gloss-overlap dedup (reuse 08_etymology_linker thresholds)
_DEDUP_GLOSS_THRESHOLD = 0.20
_STOPWORDS = frozenset({'a', 'an', 'the', 'of', 'to', 'in', 'is', 'be', 'or',
                        'and', 'for', 'with', 'as', 'by', 'at', 'from', 'on',
                        'into', 'v', 'n', 'adj', 'sp', 'vs'})
# split a reflex field into individual forms (mirror 08b_pollex_entry_linker)
_SPLIT_RE = re.compile(r'[,/;|]')
_CLEAN_RE = re.compile(r'[^a-zāēīōū]')


def ety_tables_exist(con) -> bool:
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'ETY_*'")}
    return set(ETY_TABLES).issubset(have)


def _gloss_words(text: str) -> frozenset:
    return frozenset(re.findall(r'[a-z]+', (text or '').lower())) - _STOPWORDS


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _reflex_keys(reflex: str) -> set:
    """Macron-neutral match keys for a raw reflex form (mirror 08b linker)."""
    keys = set()
    for part in _SPLIT_RE.split(reflex or ''):
        part = _CLEAN_RE.sub('', part.lower().strip())
        if len(part) < 2:
            continue
        key = normalise_search_key(part)
        if key:
            keys.add(key)
    return keys


# ── language resolver (map abvd/tregear langs onto POLLEX slugs where possible) ─

def build_lang_resolver(con):
    """Return (by_iso, by_name) POLLEX lookup tables for language resolution."""
    by_iso, by_name = {}, {}
    for slug, name, iso in con.execute(
            "SELECT language_slug, language, iso_code FROM pollex_languages"):
        if iso:
            by_iso.setdefault(iso.strip().lower(), slug)
        if name:
            by_name.setdefault(name.strip().lower(), slug)
    return by_iso, by_name


def resolve_lang(by_iso, by_name, iso=None, name=None):
    """POLLEX slug for a language, matched by ISO then name; else None."""
    if iso and iso.strip().lower() in by_iso:
        return by_iso[iso.strip().lower()]
    if name and name.strip().lower() in by_name:
        return by_name[name.strip().lower()]
    return None


# ── reference tables (POLLEX-derived; rebuilt every run) ─────────────────────

def build_refs(con) -> tuple:
    """Rebuild ETY_level + POLLEX ETY_language rows."""
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
    """Delete one source's ETY_reflex + ETY_cognateset (+ non-POLLEX languages)."""
    n = con.execute("DELETE FROM ETY_reflex WHERE source=?", (source,)).rowcount
    n += con.execute("DELETE FROM ETY_cognateset WHERE source=?", (source,)).rowcount
    if source != "pollex":
        con.execute("DELETE FROM ETY_language WHERE source=?", (source,))
    return n


def build_pollex(con, resolver) -> dict:
    """pollex_cognatesets -> ETY_cognateset; pollex_reflexes -> ETY_reflex."""
    sets = con.execute(
        "SELECT id, protoform_name, level, description, notes, pollex_url "
        "FROM pollex_cognatesets"
    ).fetchall()
    id_map = {}
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


def build_lpo(con, resolver) -> dict:
    """lpo_cognatesets -> ETY_cognateset (no reflexes in staging)."""
    n = con.execute(
        "INSERT INTO ETY_cognateset "
        "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
        "SELECT 'lpo', id, name, name_key, level, description, chapter_id, chapter_title, NULL, 0 "
        "FROM lpo_cognatesets"
    ).rowcount
    return {"cognateset": n, "reflex": 0, "orphan_reflex": 0}


def build_acd(con, resolver) -> dict:
    """acd_cognatesets -> ETY_cognateset (no reflexes in staging)."""
    n = con.execute(
        "INSERT INTO ETY_cognateset "
        "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
        "SELECT 'acd', id, name, name_key, level, description, etymon_id, NULL, NULL, 0 "
        "FROM acd_cognatesets"
    ).rowcount
    return {"cognateset": n, "reflex": 0, "orphan_reflex": 0}


def build_tregear(con, resolver) -> dict:
    """tregear_entries -> ETY_cognateset (protoform = Māori headword);
    each entry gets 1 synthetic Māori headword reflex + its comparative cognates.

    Tregear is a comparative dictionary keyed by the Māori word, not a set of
    reconstructions — so each entry becomes an ETY_cognateset whose "protoform"
    is the headword, and whose reflexes are the headword itself (lang=maori) plus
    every per-language cognate row.
    """
    by_iso, by_name = resolver
    added_langs = {}   # lang_key -> (name, source) for unresolved langs
    entries = con.execute(
        "SELECT id, headword, headword_norm, gloss_en, letter, tei_ref "
        "FROM tregear_entries"
    ).fetchall()
    id_map = {}
    for eid, headword, hnorm, gloss, letter, tei_ref in entries:
        cur = con.execute(
            "INSERT INTO ETY_cognateset "
            "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
            "VALUES ('tregear', ?, ?, ?, NULL, ?, ?, NULL, NULL, 0)",
            (str(eid), headword, normalise_proto_key(headword), gloss, letter))
        id_map[eid] = cur.lastrowid
        # synthetic Māori headword reflex (drives the entry bridge)
        con.execute(
            "INSERT INTO ETY_reflex "
            "(cognateset_id, source, source_ref, lang_key, language, form, gloss, "
            " source_code, source_author, flags, gap_fill) "
            "VALUES (?, 'tregear', ?, ?, 'Māori', ?, ?, NULL, NULL, 'headword', 0)",
            (id_map[eid], f"e{eid}", MAORI_KEY, headword, gloss))

    n_reflex = con.execute("SELECT COUNT(*) FROM ETY_reflex WHERE source='tregear'").fetchone()[0]
    cognates = con.execute(
        "SELECT id, tregear_entry_id, language, extra_polynesian, form, gloss "
        "FROM tregear_cognates"
    ).fetchall()
    orphans = 0
    for cid, teid, language, extra_poly, form, gloss in cognates:
        ety_set = id_map.get(teid)
        if ety_set is None:
            orphans += 1
            continue
        lang_key = resolve_lang(by_iso, by_name, name=language)
        if lang_key is None:
            lang_key = "tregear:" + normalise_sort_key(language or "")
            added_langs.setdefault(lang_key, (language, "tregear"))
        con.execute(
            "INSERT INTO ETY_reflex "
            "(cognateset_id, source, source_ref, lang_key, language, form, gloss, "
            " source_code, source_author, flags, gap_fill) "
            "VALUES (?, 'tregear', ?, ?, ?, ?, ?, NULL, NULL, ?, 0)",
            (ety_set, f"c{cid}", lang_key, language, form, gloss,
             "ext_poly" if extra_poly else None))
        n_reflex += 1

    for lang_key, (name, src) in added_langs.items():
        con.execute(
            "INSERT OR IGNORE INTO ETY_language (lang_key, name, source) VALUES (?, ?, ?)",
            (lang_key, name, src))
    return {"cognateset": len(entries), "reflex": n_reflex, "orphan_reflex": orphans}


def build_abvd(con, resolver) -> dict:
    """abvd_cognatesets -> ETY_cognateset (per-concept attested class, no protoform);
    each cognacy judgment (abvd_cognates -> abvd_forms) becomes an ETY_reflex.
    """
    by_iso, by_name = resolver
    # language map: abvd language id -> (lang_key, display name); collect additions
    added_langs = {}
    lang_map = {}
    for lid, name, iso, subgroup in con.execute(
            "SELECT id, name, iso_code, subgroup FROM abvd_languages"):
        lang_key = resolve_lang(by_iso, by_name, iso=iso, name=name)
        if lang_key is None:
            lang_key = "abvd:" + lid
            added_langs[lang_key] = (name, iso, subgroup, "abvd")
        lang_map[lid] = (lang_key, name)

    sets = con.execute(
        "SELECT cognateset_id, concept_name FROM abvd_cognatesets"
    ).fetchall()
    id_map = {}
    for raw_id, concept in sets:
        # ABVD sets are attested cognacy classes per concept — no reconstructed
        # protoform, so proto_key stays NULL (excluded from cross-source dedup).
        cur = con.execute(
            "INSERT INTO ETY_cognateset "
            "(source, source_ref, protoform, proto_key, level, gloss, set_group, notes, url, gap_fill) "
            "VALUES ('abvd', ?, ?, NULL, NULL, ?, NULL, NULL, NULL, 0)",
            (raw_id, raw_id, concept))
        id_map[raw_id] = cur.lastrowid

    judgments = con.execute(
        "SELECT j.id, j.cognateset_id, j.doubt, j.method, "
        "       f.language_id, COALESCE(f.form, f.value), cs.concept_name "
        "FROM abvd_cognates j "
        "JOIN abvd_forms f ON f.id = j.form_id "
        "JOIN abvd_cognatesets cs ON cs.cognateset_id = j.cognateset_id"
    ).fetchall()
    rows = []
    orphans = 0
    for jid, cs_id, doubt, method, lang_id, form, concept in judgments:
        ety_set = id_map.get(cs_id)
        if ety_set is None:
            orphans += 1
            continue
        lang_key, lang_name = lang_map.get(lang_id, (None, lang_id))
        rows.append((ety_set, jid, lang_key, lang_name, form, concept, method))
    con.executemany(
        "INSERT INTO ETY_reflex "
        "(cognateset_id, source, source_ref, lang_key, language, form, gloss, "
        " source_code, source_author, flags, gap_fill) "
        "VALUES (?, 'abvd', ?, ?, ?, ?, ?, ?, NULL, NULL, 0)",
        rows)

    for lang_key, (name, iso, subgroup, src) in added_langs.items():
        con.execute(
            "INSERT OR IGNORE INTO ETY_language (lang_key, name, iso_code, subgroup, source) "
            "VALUES (?, ?, ?, ?, ?)", (lang_key, name, iso, subgroup, src))
    return {"cognateset": len(sets), "reflex": len(rows), "orphan_reflex": orphans}


BUILDERS = {"pollex": build_pollex, "lpo": build_lpo, "acd": build_acd,
            "tregear": build_tregear, "abvd": build_abvd}

# raw-table row that each ETY source projects from, for the parity proof
RAW_SET_TABLE = {
    "pollex": "pollex_cognatesets",
    "lpo": "lpo_cognatesets",
    "acd": "acd_cognatesets",
    "tregear": "tregear_entries",
    "abvd": "abvd_cognatesets",
}
RAW_REFLEX_TABLE = {"pollex": "pollex_reflexes", "abvd": "abvd_cognates"}


def build_source(con, source: str, resolver) -> dict:
    delete_source_slice(con, source)
    counts = BUILDERS[source](con, resolver)
    counts["source"] = source
    return counts


# ── global link builders (full-build only) ───────────────────────────────────

def _set_id_map(con) -> dict:
    """(source, source_ref) -> ETY_cognateset.id, for wiring raw-id links."""
    return {(s, r): i for i, s, r in con.execute(
        "SELECT id, source, source_ref FROM ETY_cognateset")}


def build_links(con) -> dict:
    """Merge etymology_links + protoform_ancestry -> ETY_link, then add
    cross-source proto_key/gloss dedup equivalences. Returns counts."""
    con.execute("DELETE FROM ETY_link")
    smap = _set_id_map(con)
    linked_pairs = set()          # unordered {a,b} already linked (skip in dedup)
    n_equiv = n_anc = n_orphan = 0

    def _pair(a, b):
        return (a, b) if a <= b else (b, a)

    # etymology_links: pollex <-> lpo / acd equivalences
    for pol, lpo, acd, conf, method in con.execute(
            "SELECT pollex_cognateset_id, lpo_cognateset_id, acd_cognateset_id, "
            "match_confidence, match_method FROM etymology_links"):
        src = smap.get(("pollex", pol))
        if src is None:
            n_orphan += 1
            continue
        for kind, raw in (("lpo", lpo), ("acd", acd)):
            if not raw:
                continue
            tgt = smap.get((kind, raw))
            if tgt is None:
                n_orphan += 1
                continue
            con.execute(
                "INSERT INTO ETY_link (source_set_id, target_set_id, link_type, "
                "relation, match_confidence, match_method, origin, notes) "
                "VALUES (?, ?, 'equivalence', 'same_as', ?, ?, 'etymology_links', NULL)",
                (src, tgt, conf, method))
            linked_pairs.add(_pair(src, tgt))
            n_equiv += 1

    # protoform_ancestry: pollex child descends-from / cf ancestor (skip the
    # rows already sourced from etymology_links to avoid double-counting).
    rel_map = {"descends": "descends_from", "cf": "cf"}
    for child, kind, anc, relation, conf, raw_ref in con.execute(
            "SELECT child_id, ancestor_kind, ancestor_id, relation, confidence, raw_ref "
            "FROM protoform_ancestry WHERE source != 'etymology_links'"):
        src = smap.get(("pollex", child))
        tgt = smap.get((kind, anc))
        if src is None or tgt is None:
            n_orphan += 1
            continue
        con.execute(
            "INSERT INTO ETY_link (source_set_id, target_set_id, link_type, "
            "relation, match_confidence, match_method, origin, notes) "
            "VALUES (?, ?, 'ancestry', ?, ?, 'notes_citation', 'protoform_ancestry', ?)",
            (src, tgt, rel_map.get(relation, relation), conf, raw_ref))
        linked_pairs.add(_pair(src, tgt))
        n_anc += 1
    con.commit()

    # cross-source dedup: sets sharing a proto_key across DIFFERENT sources, with
    # enough gloss overlap, are flagged equivalent (pollex<->lpo/acd is already
    # carried above, so this mostly adds the remaining bare-form matches).
    groups = {}
    for sid, source, pkey, gloss in con.execute(
            "SELECT id, source, proto_key, gloss FROM ETY_cognateset "
            "WHERE proto_key IS NOT NULL AND proto_key != ''"):
        groups.setdefault(pkey, []).append((sid, source, _gloss_words(gloss)))
    n_dedup = 0
    dedup_rows = []
    for members in groups.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                (a_id, a_src, a_g), (b_id, b_src, b_g) = members[i], members[j]
                if a_src == b_src:
                    continue
                if _pair(a_id, b_id) in linked_pairs:
                    continue
                score = _jaccard(a_g, b_g)
                if score < _DEDUP_GLOSS_THRESHOLD:
                    continue
                linked_pairs.add(_pair(a_id, b_id))
                lo, hi = _pair(a_id, b_id)
                dedup_rows.append((lo, hi, round(score, 3)))
                n_dedup += 1
    con.executemany(
        "INSERT INTO ETY_link (source_set_id, target_set_id, link_type, relation, "
        "match_confidence, match_method, origin, notes) "
        "VALUES (?, ?, 'equivalence', 'same_as', ?, 'proto_key_gloss', 'dedup', NULL)",
        dedup_rows)
    con.commit()
    return {"equivalence": n_equiv, "ancestry": n_anc, "dedup": n_dedup,
            "orphan": n_orphan, "total": n_equiv + n_anc + n_dedup}


def build_entry_links(con) -> dict:
    """Bridge every source's Māori reflexes to unified `entry` rows by macron-
    neutral headword key (extends 08b_pollex_entry_linker to all sources)."""
    con.execute("DELETE FROM ETY_entry_link")
    entry_idx = {}
    for eid, hs in con.execute(
            "SELECT id, headword_search FROM entry WHERE headword_search IS NOT NULL"):
        entry_idx.setdefault(hs, []).append(eid)

    seen = set()
    rows = []
    for rid, cs_id, source, form in con.execute(
            "SELECT id, cognateset_id, source, form FROM ETY_reflex "
            "WHERE lang_key = ?", (MAORI_KEY,)):
        for key in _reflex_keys(form):
            for eid in entry_idx.get(key, ()):
                dedup = (cs_id, eid)
                if dedup in seen:
                    continue
                seen.add(dedup)
                rows.append((cs_id, rid, eid, source, key))
    con.executemany(
        "INSERT INTO ETY_entry_link "
        "(cognateset_id, reflex_id, entry_id, source, match_key, match_method, match_confidence) "
        "VALUES (?, ?, ?, ?, ?, 'headword_exact', 1.0)", rows)
    con.commit()
    by_source = dict(con.execute(
        "SELECT source, COUNT(*) FROM ETY_entry_link GROUP BY source"))
    return {"total": len(rows),
            "entries": len({r[2] for r in rows}),
            "by_source": by_source}


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

        ety_ref = con.execute(
            "SELECT COUNT(*) FROM ETY_reflex WHERE source=?", (src,)).fetchone()[0]
        if src == "tregear":
            # tregear reflexes = 1 synthetic headword per entry + every cognate row
            expect = _count(con, "tregear_entries") + _count(con, "tregear_cognates")
            ref_ok = ety_ref == expect
            ok &= ref_ok
            print(f"  [tregear] reflex   raw={expect:>6}  ETY={ety_ref:>6}  "
                  f"{'OK' if ref_ok else 'MISMATCH'}  (entries+cognates)")
        elif src in RAW_REFLEX_TABLE:
            raw_ref = _count(con, RAW_REFLEX_TABLE[src])
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

    # FK integrity of the reflex -> cognateset join
    orphan_ref = con.execute(
        "SELECT COUNT(*) FROM ETY_reflex r LEFT JOIN ETY_cognateset cs "
        "ON r.cognateset_id=cs.id WHERE cs.id IS NULL").fetchone()[0]
    ok &= orphan_ref == 0
    print(f"  orphan reflexes (no set): {orphan_ref}  {'OK' if orphan_ref == 0 else 'MISMATCH'}")

    print("─────────────────────────────────────────────────────────")
    print("PARITY: PASS" if ok else "PARITY: FAIL")
    return ok


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="Project the comparative sources into the unified ETY_* etymology layer.")
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

    # Global link tables reference per-source reflexes/sets. Clear them BEFORE
    # re-slicing any source so foreign_keys=ON delete checks don't block on (and
    # full-scan) the referencing rows. They are rebuilt below on a full run; on a
    # partial --source build they stay empty (rerun a full build to repopulate).
    con.execute("DELETE FROM ETY_entry_link")
    con.execute("DELETE FROM ETY_link")
    con.commit()

    resolver = build_lang_resolver(con)
    n_lvl, n_lang = build_refs(con)
    con.commit()
    print(f"refs: ETY_level {n_lvl}, ETY_language(pollex) {n_lang}")

    for src in targets:
        c = build_source(con, src, resolver)
        con.commit()
        extra = f"  (dropped {c['orphan_reflex']} orphan reflexes)" if c["orphan_reflex"] else ""
        print(f"[{src}] cognateset {c['cognateset']}, reflex {c['reflex']}{extra}")

    # Global links span all sources — only rebuild on a full run.
    full_build = set(targets) >= set(SOURCES)
    if full_build:
        lk = build_links(con)
        print(f"ETY_link: {lk['total']} "
              f"(equivalence {lk['equivalence']}, ancestry {lk['ancestry']}, "
              f"dedup {lk['dedup']}; {lk['orphan']} orphan raw-ids skipped)")
        el = build_entry_links(con)
        print(f"ETY_entry_link: {el['total']} links -> {el['entries']} entries")
        for s, n in sorted(el["by_source"].items(), key=lambda x: -x[1]):
            print(f"    {s}: {n}")
    else:
        print("(partial --source build: ETY_link / ETY_entry_link cleared and NOT "
              "repopulated — run a full build to rebuild them)")

    passed = parity_check(con, targets)
    con.close()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
