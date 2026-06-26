"""Session 33: seed pollex_languages reference table.

Run:  py scripts/33_pollex_languages_import.py
      py scripts/33_pollex_languages_import.py --reset   (default; same effect)
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH

# fmt: off
# (language_slug, language, iso_code, subgroup, region, country_or_island_group, notes)
POLLEX_LANGUAGES = [
    # ── Tongic ────────────────────────────────────────────────────────────────
    ("east-uvea",   "East Uvea",        "wls",  "Tongic",             "Pacific", "Wallis and Futuna",  "Also called Wallisian; Uvea island"),
    ("niue",        "Niue",             "niu",  "Tongic",             "Pacific", "Niue",               None),
    ("nfo",         "Niuafoʻou",        "nnf",  "Tongic",             "Pacific", "Tonga",              "Also called Futu; Niuafoʻou island"),
    ("ntp",         "Niuatoputapu",     None,   "Tongic",             "Pacific", "Tonga",              "Northwest Tongan island; ISO uncertain"),
    ("tongan",      "Tongan",           "ton",  "Tongic",             "Pacific", "Tonga",              None),

    # ── Eastern Polynesian ────────────────────────────────────────────────────
    ("aitutaki",                  "Aitutaki",           "rar",  "Eastern Polynesian", "Pacific", "Cook Islands",     "Cook Islands Māori dialect; Aitutaki island"),
    ("ati",                       "Atiu",               "rar",  "Eastern Polynesian", "Pacific", "Cook Islands",     "Cook Islands Māori dialect; Atiu island"),
    ("austral-island",            "Austral Islands",    None,   "Eastern Polynesian", "Pacific", "French Polynesia", "Collective term; includes Rurutu, Raivavae, Tubuai"),
    ("easter-island",             "Easter Island",      "rap",  "Eastern Polynesian", "Pacific", "Chile",            "Rapa Nui; Isla de Pascua"),
    ("hawaii",                    "Hawaiian",           "haw",  "Eastern Polynesian", "Pacific", "USA (Hawaiʻi)",    None),
    ("mangaia",                   "Mangaia",            "rar",  "Eastern Polynesian", "Pacific", "Cook Islands",     "Cook Islands Māori dialect; Mangaia island"),
    ("mangareva",                 "Mangareva",          "mrv",  "Eastern Polynesian", "Pacific", "French Polynesia", "Gambier Islands"),
    ("manihiki-mauke-rakahanga",  "Manihiki-Rakahanga", "rkh",  "Eastern Polynesian", "Pacific", "Cook Islands",     "Also called Rakahanga-Manihiki"),
    ("marquesas",                 "Marquesas",          "mrq",  "Eastern Polynesian", "Pacific", "French Polynesia", "Northern Marquesas"),
    ("maori",                     "New Zealand Maori",  "mri",  "Eastern Polynesian", "Pacific", "New Zealand",      None),
    ("mooriori",                  "Moriori",            None,   "Eastern Polynesian", "Pacific", "New Zealand",      "Extinct; Chatham Islands (Rekohu); no ISO 639-3 assigned"),
    ("penrhyn",                   "Penrhyn",            "pnh",  "Eastern Polynesian", "Pacific", "Cook Islands",     "Also called Tongareva"),
    ("raivavai",                  "Raivavae",           "rvv",  "Eastern Polynesian", "Pacific", "French Polynesia", "Austral Islands"),
    ("rapa",                      "Rapa",               "ray",  "Eastern Polynesian", "Pacific", "French Polynesia", "Rapa Iti (not Easter Island)"),
    ("rarotongan",                "Rarotongan",         "rar",  "Eastern Polynesian", "Pacific", "Cook Islands",     None),
    ("rurutu",                    "Rurutu",             "rmo",  "Eastern Polynesian", "Pacific", "French Polynesia", "Austral Islands; ISO uncertain"),
    ("tahitian",                  "Tahitian",           "tah",  "Eastern Polynesian", "Pacific", "French Polynesia", None),
    ("tuamotu",                   "Tuamotu",            "pmt",  "Eastern Polynesian", "Pacific", "French Polynesia", None),
    ("tupuaki",                   "Tupuaki",            None,   "Eastern Polynesian", "Pacific", "French Polynesia", "Marquesas-related variety; ISO uncertain"),

    # ── Samoic-Outlier (incl. Futunic) ───────────────────────────────────────
    ("east-futuna", "East Futuna",  "fud",  "Samoic-Outlier", "Pacific", "Wallis and Futuna", "Futunic branch"),
    ("emae",        "Emae",         "mmw",  "Samoic-Outlier", "Pacific", "Vanuatu",           "Futunic; also called Maat"),
    ("mele-fila",   "Ifira-Mele",   "mxe",  "Samoic-Outlier", "Pacific", "Vanuatu",           "Futunic; Ifira and Mele islands"),
    ("pukapuka",    "Pukapuka",     "pka",  "Samoic-Outlier", "Pacific", "Cook Islands",      None),
    ("samoan",      "Samoan",       "smo",  "Samoic-Outlier", "Pacific", "Samoa",             "Also spoken in American Samoa"),
    ("tokelau",     "Tokelau",      "tkl",  "Samoic-Outlier", "Pacific", "Tokelau",           None),
    ("tuvalu",      "Tuvalu",       "tvl",  "Samoic-Outlier", "Pacific", "Tuvalu",            None),
    ("westfutuna",  "West Futuna",  "wfu",  "Samoic-Outlier", "Pacific", "Vanuatu",           "Futunic; Futuna-Aniwa islands"),

    # ── Polynesian Outlier ────────────────────────────────────────────────────
    ("anuta",          "Anuta",            "aud",  "Polynesian Outlier", "Pacific", "Solomon Islands",  None),
    ("kapingimaringi", "Kapingamarangi",   "kpg",  "Polynesian Outlier", "Pacific", "Micronesia (FSM)", None),
    ("luangiua",       "Luangiua",         "lgl",  "Polynesian Outlier", "Pacific", "Solomon Islands",  "Also called Ontong Java"),
    ("ngr",            "Nuguria",          "nug",  "Polynesian Outlier", "Pacific", "Papua New Guinea",  "Also called Abgarris"),
    ("nkm",            "Nukumanu",         "nku",  "Polynesian Outlier", "Pacific", "Papua New Guinea",  None),
    ("nukuoro",        "Nukuoro",          "nkr",  "Polynesian Outlier", "Pacific", "Micronesia (FSM)",  None),
    ("pileni",         "Vaeakau-Taumako",  "vkk",  "Polynesian Outlier", "Pacific", "Solomon Islands",  "Also called Pileni; Reef-Santa Cruz group"),
    ("rennellese",     "Rennellese",       "mnv",  "Polynesian Outlier", "Pacific", "Solomon Islands",  "Rennell-Bellona islands"),
    ("sikaiana",       "Sikaiana",         "sky",  "Polynesian Outlier", "Pacific", "Solomon Islands",  None),
    ("takuu",          "Takuu",            "tku",  "Polynesian Outlier", "Pacific", "Papua New Guinea",  "Also called Mortlock; ISO uncertain"),
    ("tikopia",        "Tikopia",          "tik",  "Polynesian Outlier", "Pacific", "Solomon Islands",  None),
    ("westuvea",       "West Uvea",        None,   "Polynesian Outlier", "Pacific", "New Caledonia",    "Also called Fagauvea; Ouevea island; ISO uncertain"),

    # ── Fijian ────────────────────────────────────────────────────────────────
    ("fijian",   "Fijian",    "fij",  "Fijian",   "Pacific", "Fiji",  "Standard Fijian (Bauan dialect)"),
    ("vaturaga", "Vaturaga",  "fij",  "Fijian",   "Pacific", "Fiji",  "Fijian dialect; Wainimala area"),
    ("waya",     "Waya",      "fij",  "Fijian",   "Pacific", "Fiji",  "Western Fijian dialect; Waya island"),

    # ── Rotuman ───────────────────────────────────────────────────────────────
    ("rotuma",  "Rotuman",  "rtm",  "Rotuman",  "Pacific", "Fiji (Rotuma)",  None),

    # ── Other Oceanic ─────────────────────────────────────────────────────────
    ("alu",      "Mono-Alu",    "mte",  "Other Oceanic", "Pacific", "Solomon Islands",  "Western Oceanic; Mono language of Choiseul/Shortland Islands"),
    ("are",      "ʔAreʔare",   None,   "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; Malaita; ISO uncertain"),
    ("arosi",    "Arosi",       "aia",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; San Cristobal (Makira)"),
    ("bugotu",   "Bugotu",      "bgr",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; Santa Isabel"),
    ("gedaged",  "Gedaged",     "gdd",  "Other Oceanic", "Pacific", "Papua New Guinea", "Oceanic; Madang coast"),
    ("gil",      "Gilbertese",  "gil",  "Other Oceanic", "Pacific", "Kiribati",         "Micronesian; also called Kiribati"),
    ("kwo",      "Kwaio",       "kww",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; Malaita"),
    ("kwaraae",  "Kwaraʔae",   "kwf",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; Malaita"),
    ("lau",      "Lau",         "llu",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; Malaita (Lau lagoon)"),
    ("mota",     "Mota",        "mtt",  "Other Oceanic", "Pacific", "Vanuatu",          "Banks Islands"),
    ("motu",     "Motu",        "meu",  "Other Oceanic", "Pacific", "Papua New Guinea", "Papuan Tip cluster"),
    ("namakura", "Namakir",     "nmk",  "Other Oceanic", "Pacific", "Vanuatu",          "South Vanuatu; also called Namakura"),
    ("nggela",   "Nggela",      "ngg",  "Other Oceanic", "Pacific", "Solomon Islands",  "Also called Gela; Florida Islands"),
    ("nguna",    "Nguna",       "ngu",  "Other Oceanic", "Pacific", "Vanuatu",          "Central Vanuatu"),
    ("paama",    "Paamese",     "pma",  "Other Oceanic", "Pacific", "Vanuatu",          "Central Vanuatu; Paama island"),
    ("raga",     "Raga",        "rbp",  "Other Oceanic", "Pacific", "Vanuatu",          "North Vanuatu; Pentecost island"),
    ("roviana",  "Roviana",     "rug",  "Other Oceanic", "Pacific", "Solomon Islands",  "Western Oceanic; New Georgia"),
    ("saa",      "Saʔa",        "apb",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; Small Malaita"),
    ("tbt",      "Toqabaqita",  "mlu",  "Other Oceanic", "Pacific", "Solomon Islands",  "Southeast Solomonic; North Malaita"),
]
# fmt: on

EXPECTED_SUBGROUPS = {
    "Tongic",
    "Eastern Polynesian",
    "Samoic-Outlier",
    "Polynesian Outlier",
    "Fijian",
    "Rotuman",
    "Other Oceanic",
}


def _import(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM pollex_languages")
    conn.executemany(
        """INSERT INTO pollex_languages
               (language_slug, language, iso_code, subgroup, region,
                country_or_island_group, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        POLLEX_LANGUAGES,
    )
    n = conn.execute("SELECT COUNT(*) FROM pollex_languages").fetchone()[0]
    print(f"  pollex_languages: {n} rows inserted")


def _validate(conn: sqlite3.Connection) -> None:
    seed_slugs = {row[0] for row in POLLEX_LANGUAGES}
    db_slugs = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT language_slug FROM pollex_reflexes"
        ).fetchall()
    }
    missing = db_slugs - seed_slugs
    if missing:
        print(f"  WARNING: {len(missing)} reflex slug(s) not in seed data: {sorted(missing)}")
    else:
        print(f"  Validation OK: all {len(db_slugs)} reflex language_slugs covered")

    subgroups_present = {row[0] for row in conn.execute(
        "SELECT DISTINCT subgroup FROM pollex_languages"
    ).fetchall()}
    missing_sg = EXPECTED_SUBGROUPS - subgroups_present
    if missing_sg:
        print(f"  WARNING: subgroups missing: {missing_sg}")
    else:
        print(f"  Subgroups: {', '.join(sorted(subgroups_present))}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", default=True,
                        help="Delete and re-seed (default)")
    args = parser.parse_args()

    with sqlite3.connect(DB_PATH) as conn:
        _import(conn)
        _validate(conn)
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
