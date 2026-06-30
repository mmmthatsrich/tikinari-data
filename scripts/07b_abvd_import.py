"""Import ABVD (Austronesian Basic Vocabulary Database) into the staging DB.

Source: sources/abvd/cldf/  — CLDF from github.com/lexibank/abvd (CC-BY-4.0).

ABVD differs from POLLEX/LPO/ACD: it has NO reconstructed protoforms. A cognateset
is an attested cognacy class scoped to ONE concept (e.g. 'hand-1'); its members are
real forms across Austronesian languages. A form may sit in more than one cognateset
(multistate cognacy).

Filter: keep only cognatesets with >=1 Polynesian/Oceanic member, where "Polynesian"
is determined by matching ABVD languages against the curated `pollex_languages` table
(by ISO 639-3 code or by name). This keeps the family-wide cognates that *reach*
Polynesian — the cross-Austronesian context for a Maori word — and drops cognate
classes with no Polynesian reflex at all.

Writes: abvd_parameters, abvd_languages, abvd_cognatesets, abvd_forms, abvd_cognates.
Tables are declared in 00_init_db.py — run that first.
"""

import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(10_000_000)  # ABVD form/segment fields can be long

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
CLDF_DIR = Path(__file__).parent.parent / "sources" / "abvd" / "cldf"


def load_pollex_language_match(conn: sqlite3.Connection):
    """Return (iso->subgroup, name->subgroup) maps from the curated pollex_languages."""
    iso_sub: dict[str, str] = {}
    name_sub: dict[str, str] = {}
    for language, iso, subgroup in conn.execute(
        "SELECT language, iso_code, subgroup FROM pollex_languages"
    ):
        if iso and iso.strip():
            iso_sub[iso.strip().lower()] = subgroup
        if language:
            name_sub[language.strip().lower()] = subgroup
    return iso_sub, name_sub


def read_csv(name: str):
    with open(CLDF_DIR / name, encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    iso_sub, name_sub = load_pollex_language_match(conn)

    # ── Languages + Polynesian classification ──────────────────────────────
    languages = list(read_csv("languages.csv"))
    poly_ids: set[str] = set()
    lang_subgroup: dict[str, str] = {}
    for r in languages:
        iso = (r["ISO639P3code"] or "").strip().lower()
        nm = r["Name"].strip().lower()
        gnm = (r["Glottolog_Name"] or "").strip().lower()
        sub = iso_sub.get(iso) or name_sub.get(nm) or name_sub.get(gnm)
        if sub:
            poly_ids.add(r["ID"])
            lang_subgroup[r["ID"]] = sub

    # ── Forms: id -> language, and keep full rows in memory ────────────────
    form_lang: dict[str, str] = {}
    form_rows: dict[str, dict] = {}
    for r in read_csv("forms.csv"):
        form_lang[r["ID"]] = r["Language_ID"]
        form_rows[r["ID"]] = r

    # ── Cognates: group members per cognateset, flag Polynesian reach ──────
    cs_members: dict[str, list[str]] = defaultdict(list)
    cog_rows_by_cs: dict[str, list[dict]] = defaultdict(list)
    cs_has_poly: set[str] = set()
    for r in read_csv("cognates.csv"):
        cs = r["Cognateset_ID"]
        fid = r["Form_ID"]
        cs_members[cs].append(fid)
        cog_rows_by_cs[cs].append(r)
        if form_lang.get(fid) in poly_ids:
            cs_has_poly.add(cs)

    kept_cs = cs_has_poly
    kept_form_ids: set[str] = set()
    for cs in kept_cs:
        kept_form_ids.update(cs_members[cs])
    kept_lang_ids = {form_lang[f] for f in kept_form_ids if f in form_lang}

    # ── Build rows ─────────────────────────────────────────────────────────
    param_rows = [
        (r["ID"], r["Name"], r["Concepticon_ID"] or None, r["Concepticon_Gloss"] or None)
        for r in read_csv("parameters.csv")
    ]
    concept_name = {pid: name for pid, name, _, _ in param_rows}

    lang_out = []
    for r in languages:
        if r["ID"] not in kept_lang_ids:
            continue
        lang_out.append((
            r["ID"], r["Name"], r["Glottocode"] or None, r["Glottolog_Name"] or None,
            r["ISO639P3code"] or None, r["Macroarea"] or None, r["Family"] or None,
            1 if r["ID"] in poly_ids else 0, lang_subgroup.get(r["ID"]),
            r["url"] or None,
        ))

    cs_out = []
    for cs in kept_cs:
        members = cs_members[cs]
        # parameter = most common Parameter_ID among member forms (authoritative)
        params = Counter(
            form_rows[f]["Parameter_ID"] for f in members if f in form_rows
        )
        pid = params.most_common(1)[0][0] if params else None
        n_poly = sum(1 for f in members if form_lang.get(f) in poly_ids)
        cs_out.append((cs, pid, concept_name.get(pid), len(members), n_poly))

    form_out = [
        (
            form_rows[f]["ID"], form_rows[f]["Language_ID"], form_rows[f]["Parameter_ID"],
            form_rows[f]["Value"] or None, form_rows[f]["Form"] or None,
            form_rows[f]["Segments"] or None, form_rows[f]["Loan"] or None,
            form_rows[f]["Comment"] or None,
        )
        for f in kept_form_ids
    ]

    cog_out = [
        (r["ID"], r["Form_ID"], r["Cognateset_ID"], r["Doubt"] or None,
         r["Cognate_Detection_Method"] or None)
        for cs in kept_cs for r in cog_rows_by_cs[cs]
    ]

    # ── Write ──────────────────────────────────────────────────────────────
    with conn:
        for tbl in ("abvd_cognates", "abvd_forms", "abvd_cognatesets",
                    "abvd_languages", "abvd_parameters"):
            conn.execute(f"DELETE FROM {tbl}")
        conn.executemany(
            "INSERT INTO abvd_parameters (id, name, concepticon_id, concepticon_gloss) "
            "VALUES (?, ?, ?, ?)", param_rows)
        conn.executemany(
            "INSERT INTO abvd_languages (id, name, glottocode, glottolog_name, iso_code, "
            "macroarea, family, is_polynesian, subgroup, url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", lang_out)
        conn.executemany(
            "INSERT INTO abvd_cognatesets (cognateset_id, parameter_id, concept_name, "
            "n_members, n_poly_members) VALUES (?, ?, ?, ?, ?)", cs_out)
        conn.executemany(
            "INSERT INTO abvd_forms (id, language_id, parameter_id, value, form, "
            "segments, loan, comment) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", form_out)
        conn.executemany(
            "INSERT INTO abvd_cognates (id, form_id, cognateset_id, doubt, method) "
            "VALUES (?, ?, ?, ?, ?)", cog_out)
        conn.execute(
            "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now') "
            "WHERE source_id = 'abvd'", (len(cs_out),))

    print("ABVD import complete (filter: cognatesets with >=1 Polynesian member)")
    print(f"  parameters (concepts): {len(param_rows)}")
    print(f"  languages kept:        {len(lang_out)}  ({len(poly_ids)} Polynesian)")
    print(f"  cognatesets kept:      {len(cs_out)}  / 19,356 total")
    print(f"  forms kept:            {len(form_out)}")
    print(f"  cognate judgments:     {len(cog_out)}")

    sub_spread = Counter(
        lang_subgroup[lid] for lid in kept_lang_ids if lid in lang_subgroup
    )
    print("  Polynesian/Oceanic subgroups present:",
          dict(sub_spread.most_common()))


if __name__ == "__main__":
    main()
