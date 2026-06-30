"""Import Walworth Polynesian comparative wordlist into the staging DB.

Source: sources/walworth/cldf/  — CLDF from github.com/lexibank/walworthpolynesian
(CC-BY-4.0; Walworth 2014, a Polynesian LingPy cognacy wordlist).

Unlike ABVD, the whole dataset is already Polynesian, so this imports FULL +
UNFILTERED — no Polynesian-member filter. Cognateset IDs are bare integers (the
form's `Cognacy` value); a cognateset is an expert-coded cognacy class, scoped in
practice to one concept. Each language is still classified against the curated
`pollex_languages` table to tag its POLLEX `subgroup` (for the ETY_* build), but
NO rows are dropped on the basis of that match.

Writes: walworth_parameters, walworth_languages, walworth_cognatesets,
walworth_forms, walworth_cognates. Tables are declared in 00_init_db.py — run that
first.
"""

import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(10_000_000)  # form/segment/alignment fields can be long

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
CLDF_DIR = Path(__file__).parent.parent / "sources" / "walworth" / "cldf"


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

    # ── Languages — keep ALL, tag subgroup where matched (no filter) ───────
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

    lang_out = [
        (
            r["ID"], r["Name"], r["Glottocode"] or None, r["Glottolog_Name"] or None,
            r["ISO639P3code"] or None, r["Macroarea"] or None, r["Family"] or None,
            r["Latitude"] or None, r["Longitude"] or None,
            1 if r["ID"] in poly_ids else 0, lang_subgroup.get(r["ID"]),
        )
        for r in languages
    ]

    # ── Parameters (concepts) ──────────────────────────────────────────────
    param_rows = [
        (r["ID"], r["Name"], r["Concepticon_ID"] or None, r["Concepticon_Gloss"] or None)
        for r in read_csv("parameters.csv")
    ]
    concept_name = {pid: name for pid, name, _, _ in param_rows}

    # ── Forms — keep all; remember each form's concept for cognateset rollup ─
    form_rows = list(read_csv("forms.csv"))
    form_param: dict[str, str] = {r["ID"]: r["Parameter_ID"] for r in form_rows}
    form_out = [
        (
            r["ID"], r["Local_ID"] or None, r["Language_ID"], r["Parameter_ID"] or None,
            r["Value"] or None, r["Form"] or None, r["Segments"] or None,
            r["Cognacy"] or None, r["Loan"] or None, r["Comment"] or None,
            r["Source"] or None,
        )
        for r in form_rows
    ]

    # ── Cognates — keep all; roll up members per cognateset ────────────────
    cs_members: dict[str, list[str]] = defaultdict(list)
    cog_out = []
    for r in read_csv("cognates.csv"):
        cs = r["Cognateset_ID"]
        cs_members[cs].append(r["Form_ID"])
        cog_out.append((
            r["ID"], r["Form_ID"], cs, r["Doubt"] or None,
            r["Cognate_Detection_Method"] or None, r["Alignment"] or None,
        ))

    cs_out = []
    for cs, members in cs_members.items():
        # parameter = most common concept among member forms (authoritative)
        params = Counter(form_param[f] for f in members if f in form_param)
        pid = params.most_common(1)[0][0] if params else None
        cs_out.append((cs, pid, concept_name.get(pid), len(members)))

    # ── Write ──────────────────────────────────────────────────────────────
    with conn:
        for tbl in ("walworth_cognates", "walworth_forms", "walworth_cognatesets",
                    "walworth_languages", "walworth_parameters"):
            conn.execute(f"DELETE FROM {tbl}")
        conn.executemany(
            "INSERT INTO walworth_parameters (id, name, concepticon_id, concepticon_gloss) "
            "VALUES (?, ?, ?, ?)", param_rows)
        conn.executemany(
            "INSERT INTO walworth_languages (id, name, glottocode, glottolog_name, iso_code, "
            "macroarea, family, latitude, longitude, is_polynesian, subgroup) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", lang_out)
        conn.executemany(
            "INSERT INTO walworth_cognatesets (cognateset_id, parameter_id, concept_name, "
            "n_members) VALUES (?, ?, ?, ?)", cs_out)
        conn.executemany(
            "INSERT INTO walworth_forms (id, local_id, language_id, parameter_id, value, "
            "form, segments, cognacy, loan, comment, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", form_out)
        conn.executemany(
            "INSERT INTO walworth_cognates (id, form_id, cognateset_id, doubt, method, "
            "alignment) VALUES (?, ?, ?, ?, ?, ?)", cog_out)
        conn.execute(
            "UPDATE source_metadata SET entry_count = ?, last_updated = datetime('now') "
            "WHERE source_id = 'walworth'", (len(cs_out),))

    print("Walworth import complete (full + unfiltered)")
    print(f"  parameters (concepts): {len(param_rows)}")
    print(f"  languages:             {len(lang_out)}  ({len(poly_ids)} matched pollex_languages)")
    print(f"  cognatesets:           {len(cs_out)}")
    print(f"  forms:                 {len(form_out)}")
    print(f"  cognate judgments:     {len(cog_out)}")

    sub_spread = Counter(lang_subgroup[lid] for lid in lang_subgroup)
    print("  Polynesian/Oceanic subgroups present:",
          dict(sub_spread.most_common()))


if __name__ == "__main__":
    main()
