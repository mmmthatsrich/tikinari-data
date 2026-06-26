"""
Populate source_abbreviations table with inline citation expansions.

Sources covered:
  - te_aka: full official bibliography from maoridictionary.co.nz/dictionary-project
  - williams: inline citations used within definition text (J., W., S., P., etc.)

Papakupu source_codes (e.g. RH1, NKM, WAI) are dialect-informant identifiers,
not published works, so are not included here.

Usage:
  py scripts/30_source_abbrevs_import.py
  py scripts/30_source_abbrevs_import.py --reset   # drop and re-insert all rows
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).parent.parent / "data" / "staging_dictionary.db"

# fmt: off
# (abbrev, source_dict, full_name, pub_type, year_range, notes)
TE_AKA_ABBREVS = [
    # ── Māori-language newspapers ─────────────────────────────────────────────
    ("AO",      "te_aka", "Aotearoa",                                                      "newspaper",   "1892",      None),
    ("HKW",     "te_aka", "He Kupu Whakamarama",                                           "newspaper",   "1898",      None),
    ("HTK",     "te_aka", "Huia Tangata Kotahi",                                           "newspaper",   "1893-1895", None),
    ("KA",      "te_aka", "Ko Aotearoa or the Maori Recorder",                             "newspaper",   "1861-1862", None),
    ("KO",      "te_aka", "Te Korimako",                                                   "newspaper",   "1882-1890", None),
    ("KTP",     "te_aka", "Ko te Panui o Aotearoa",                                        "newspaper",   "1894-1896", None),
    ("Ma",      "te_aka", "He Maramatakahaere",                                            "newspaper",   "1841-1889", None),
    ("MM",      "te_aka", "The Maori Messenger / Ko te Karere Maori",                      "newspaper",   "1849-1854", None),
    ("MM.TKM",  "te_aka", "The Maori Messenger / Te Karere Maori",                        "newspaper",   "1855-1861", None),
    ("NH",      "te_aka", "Nga Hua o te Mohiotanga ma nga Tangata Maori",                  "newspaper",   "1874",      None),
    ("NHW",     "te_aka", "Nga Hiiringa i te Whitu",                                       "newspaper",   "1896",      None),
    ("TA",      "te_aka", "Takitimu",                                                      "newspaper",   "1883",      None),
    ("TH",      "te_aka", "Te Haeata",                                                     "newspaper",   "1859-1861", None),
    ("THM",     "te_aka", "Te Hoa Maori",                                                  "newspaper",   "1885-1910", None),
    ("THNT",    "te_aka", "Te Hokioi o Niu Tireni e Rere atu na",                          "newspaper",   "1863",      None),
    ("TJ",      "te_aka", "The Jubilee / Te Tiupiri",                                      "newspaper",   "1898-1900", None),
    ("TK",      "te_aka", "Ko te Karere o Nui Tireni",                                    "newspaper",   "1842-1846", None),
    ("TKH",     "te_aka", "Te Korimako Hou",                                               "newspaper",   "1889-1890", None),
    ("TKM",     "te_aka", "The Maori Messenger / Ko te Karere Maori",                      "newspaper",   "1849-1854", None),
    ("TKM.MM",  "te_aka", "Te Karere Maori or Maori Messenger",                           "newspaper",   "1861-1863", None),
    ("TKO",     "te_aka", "Te Kopara",                                                     "newspaper",   "1913-1921", None),
    ("TKP",     "te_aka", "Te Karere o Poneke",                                            "newspaper",   "1857-1858", None),
    ("TM",      "te_aka", "Te Matariki",                                                   "newspaper",   "1881",      None),
    ("TMA",     "te_aka", "Te Matuhi",                                                     "newspaper",   "1903-1906", None),
    ("TMK",     "te_aka", "Te Mareikura",                                                  "newspaper",   "1911-1913", None),
    ("TMP",     "te_aka", "Te Paki o Matariki",                                            "newspaper",   "1892-1935", None),
    ("TMR",     "te_aka", "The Maori Record",                                              "newspaper",   "1904-1907", None),
    ("TMT",     "te_aka", "Te Manuhiri Tuarangi and Maori Intelligencer",                  "newspaper",   "1861",      None),
    ("TMU",     "te_aka", "Te Manukura",                                                   "newspaper",   "1916-1923", None),
    ("TP",      "te_aka", "Te Pipiwharauroa",                                              "newspaper",   "1899-1913", None),
    ("TPH",     "te_aka", "Te Puke ki Hikurangi",                                          "newspaper",   "1897-1913", None),
    ("TPM",     "te_aka", "Te Pihoihoi Mokemoke i runga i te Tuanui",                      "newspaper",   "1863",      None),
    ("TRA",     "te_aka", "Te Reo o Aotearoa",                                             "newspaper",   "1932-1933", None),
    ("TTT",     "te_aka", "Te Toa Takitini",                                               "newspaper",   "1921-1932", None),
    ("TW",      "te_aka", "Te Wananga",                                                    "newspaper",   "1874-1878", None),
    ("TWI",     "te_aka", "Te Waka o Te Iwi",                                              "newspaper",   "1856-1863", None),
    ("TWM",     "te_aka", "Te Waka Maori o Ahuriri",                                       "newspaper",   "1863-1871", None),
    ("TWMA",    "te_aka", "Te Waka Maori o Aotearoa",                                      "newspaper",   "1884",      None),
    ("TWMNT",   "te_aka", "Te Waka Maori o Niu Tirani",                                    "newspaper",   "1871-1879", None),

    # ── Books, journals, reference works ─────────────────────────────────────
    ("BFM",     "te_aka", "Te Mātāpunenga: A Compendium of References to the Concepts and Institutions of Māori Customary Law",
                                                                                           "book",        "2013",      None),
    ("CS",      "te_aka", "Ina mate ohorere te tangata: He aratohu ki ngā ratonga tirotiro mate whawhati",
                                                                                           "book",        "2013",      "Ministry of Health guidance"),
    ("DNZB",    "te_aka", "Dictionary of New Zealand Biography",                           "reference",   "1990-2000", None),
    ("EM",      "te_aka", "Eruera Mānuera",                                                "book",        "2002",      None),
    ("HHK",     "te_aka", "He Kohinga Kīwaha",                                             "reference",   "1999",      None),
    ("HKKT",    "te_aka", "He Kohinga Kīwaha nō Tainui",                                   "reference",   "2011",      None),
    ("HM",      "te_aka", "He Muka",                                                       "reference",   None,        None),
    ("HP",      "te_aka", "He Hokinga Mahara",                                             "book",        "1991",      None),
    ("HRO",     "te_aka", "He Reo Ōkawa",                                                  "reference",   "2014",      None),
    ("HS",      "te_aka", "Ko Tautoro, Te Pito o Tōku Ao: A Ngāpuhi Narrative",            "book",        "2014",      None),
    ("HW",      "te_aka", "Te Rangatahi (vols 1–2)",                                       "book",        "1968-1969", None),
    ("HWM",     "te_aka", "Whakapapa Tupuna",                                              "other",       None,        "Unpublished manuscript"),
    ("JM",      "te_aka", "PhD thesis on Māori education",                                 "thesis",      "2013",      None),
    ("JPS",     "te_aka", "Journal of the Polynesian Society",                             "journal",     "1892-",     None),
    ("KR",      "te_aka", "Kia Rōnaki: The Māori Performing Arts",                         "book",        "2013",      None),
    ("MT",      "te_aka", "I Whānau Au Ki Kaiapoi: The Story of Natanahira Waruwarutu",    "book",        "2011",      None),
    ("NIT",     "te_aka", "Ngā Iwi o Tainui",                                              "book",        "1995",      None),
    ("NM",      "te_aka", "Nga Mahi a nga Tupuna",                                         "book",        "1928",      None),
    ("NP",      "te_aka", "Ngā Pēpeha a ngā Tīpuna",                                       "book",        "2001",      None),
    ("NW",      "te_aka", "Ngā Whatiwhatinga",                                             "reference",   "1991",      None),
    ("NWH",     "te_aka", "Ngā Waiata me ngā Haka a Tāua a te Māori",                      "book",        "1978",      None),
    ("PK",      "te_aka", "He Pātaka Kupu: Te Kai a te Rangatira",                          "reference",   "2008",      None),
    ("PT",      "te_aka", "Ko Te Paipera Tapu",                                            "bible",       "1952",      "Māori Bible translation"),
    ("RHR",     "te_aka", "He Reo Hītori o Ngā Rākau",                                     "reference",   "2017",      None),
    ("RK",      "te_aka", "Nga Kōrero a Reweti Kohere Mā",                                  "book",        "1994",      None),
    ("RM",      "te_aka", "Grammar of the New Zealand Language",                           "book",        "1894",      "Maunsell, R."),
    ("RMR",     "te_aka", "He Rito Reo Māori",                                             "reference",   "2017",      None),
    ("RP",      "te_aka", "Te Reo Putaiao",                                                "reference",   "2009",      None),
    ("RR",      "te_aka", "Te Reo Rangatira",                                              "book",        "1974",      None),
    ("RT",      "te_aka", "He Papakupu Reo Ture: A Dictionary of Māori Legal Terms",        "reference",   "2013",      None),
    ("RTA",     "te_aka", "Te Reo o Ngā Toi Ataata: He Tauira Papakupu",                    "reference",   "2014",      None),
    ("RTP",     "te_aka", "Te Reo o Ngā Toi Puoro: He Tauira Papakupu",                     "reference",   "2015",      None),
    ("TAH",     "te_aka", "Te Ao Hou",                                                     "other",       "1952-1975", "Māori magazine, issues 1–76"),
    ("TKI",     "te_aka", "Te Kete Ipurangi",                                              "other",       None,        "NZ Ministry of Education online resource (tki.org.nz)"),
    ("TRM",     "te_aka", "Te Reo Māori i roto i Te Marautanga o Aotearoa",                "curriculum",  "1996",      None),
    ("TRP",     "te_aka", "Te Reo Pāngarau (Putanga Tuarua)",                              "reference",   "2010",      "Māori-language mathematics terminology"),
    ("TT",      "te_aka", "Tikao Talks: Ka Taoka Tapu o Te Ao Kohatu",                     "book",        "1990",      None),
    ("TTR",     "te_aka", "Ngā Tāngata Taumata Rau",                                       "reference",   "1990-2000", "5-volume biographical dictionary of prominent Māori people"),
    ("TTTT",    "te_aka", "Te Tū a Te Toka: He Ieretanga nō ngā Tai e Whā",                "book",        "2006",      None),
    ("TTW",     "te_aka", "Tauākī Whakamaunga Atu 04-08",                                  "other",       "2004",      None),
    ("TWK",     "te_aka", "Te Wharekura",                                                  "other",       None,        "Publication series, issues 1–61"),
    ("VC",      "te_aka", "He Kōrero Whakaari",                                            "book",        "1943",      None),
    ("WIII",    "te_aka", "The Ancient History of the Maori (vol. III)",                    "book",        "1889",      "White, John. 6 vols, 1887–1890"),
    ("WT",      "te_aka", "Living by the Moon: Te Maramataka a Te Whānau-ā-Apanui",         "book",        "2013",      None),
    ("WW",      "te_aka", "Lore of the Whare-wānanga",                                     "book",        "1913-1915", "2 parts"),

    # ── Institutions/organisations cited as sources ───────────────────────────
    ("ACC",     "te_aka", "Accident Compensation Corporation (ACC)",                       "other",       None,        None),
    ("IR",      "te_aka", "Inland Revenue — Te Tari Taake",                                "other",       None,        None),
    ("NZH",     "te_aka", "New Zealand Herald",                                            "newspaper",   None,        None),
    ("NZP",     "te_aka", "New Zealand Parliament",                                        "other",       None,        None),
    ("NZSTI",   "te_aka", "New Zealand Society of Translators and Interpreters",            "other",       None,        None),
    ("RNZ",     "te_aka", "Radio New Zealand — Reo Irirangi o Aotearoa",                   "other",       None,        None),
]

WILLIAMS_ABBREVS = [
    # Inline citations used within Williams (1957) definition text.
    # Source: analysis of definition text + knowledge of Williams's citation practice.
    ("J.",   "williams", "Journal of the Polynesian Society",                      "journal", "1892-",     "Cited by volume/page, e.g. 'J. vii. 132'"),
    ("T.",   "williams", "Tregear's Maori-Polynesian Comparative Dictionary",      "book",    "1891",      "Tregear, E. Cited by page, e.g. 'T. 144'"),
    ("W.",   "williams", "White's Ancient History of the Maori",                  "book",    "1887-1890", "White, J. 6 vols. Cited by volume/page, e.g. 'W. v. 116'"),
    ("P.",   "williams", "Māori proverb collection",                              "other",   None,        None),
    ("S.",   "williams", "Traditional Māori song texts",                          "other",   None,        None),
    ("R.",   "williams", "Rotorua oral tradition texts",                          "other",   None,        "Precise source unconfirmed"),
    ("K.",   "williams", "Korero oral narrative texts",                           "other",   None,        "Precise source unconfirmed"),
    ("M.",   "williams", "Ngā Mōteatea",                                          "book",    "1853",      "Traditional song poetry, Grey"),
]

HEPATAKAKUPU_ABBREVS = [
    # Source: hepatakakupu.nz/sources (He Pātaka Kupu, Te Taura Whiri i te Reo Māori, 2008)
    # Import script merges these with te_aka abbrevs so shared-code entries need not be duplicated.

    # ── Māori-language newspapers (HPK-specific abbreviation forms) ───────────
    ("AM",    "hepatakakupu", "Ko Aotearoa or the Maori Recorder",                            "newspaper",   "1861-1862", None),
    ("Ao",    "hepatakakupu", "Aotearoa",                                                     "newspaper",   "1892",      None),
    ("Ha",    "hepatakakupu", "Te Haeata",                                                    "newspaper",   "1859-1861", None),
    ("HMa",   "hepatakakupu", "Te Hoa Maori",                                                 "newspaper",   "1885-1910", None),
    ("KM",    "hepatakakupu", "Te Karere Maori or Maori Messenger",                           "newspaper",   "1861-1863", None),
    ("KNT",   "hepatakakupu", "Te Karere o Nui Tireni",                                       "newspaper",   "1842-1846", None),
    ("Ko",    "hepatakakupu", "Te Kopara",                                                    "newspaper",   "1913-1921", None),
    ("KtKM",  "hepatakakupu", "The Maori Messenger, Te Karere Maori",                         "newspaper",   "1855-1861", None),
    ("Mata",  "hepatakakupu", "Te Matariki",                                                  "newspaper",   "1881",      None),
    ("PH",    "hepatakakupu", "Te Puke ki Hikurangi",                                         "newspaper",   "1897-1913", None),
    ("Pi",    "hepatakakupu", "Te Pipiwharauroa",                                             "newspaper",   "1899-1913", None),
    ("PM",    "hepatakakupu", "Te Pihoihoi Mokemoke i runga i te Tuanui",                     "newspaper",   "1863",      None),
    ("PoM",   "hepatakakupu", "Te Paki o Matariki",                                           "newspaper",   "1892-1935", None),
    ("Tak",   "hepatakakupu", "Takitimu",                                                     "newspaper",   "1883",      None),
    ("Wa",    "hepatakakupu", "Te Wananga",                                                   "newspaper",   "1874-1878", None),
    ("Wh",    "hepatakakupu", "Te Wharekura",                                                 "other",       None,        "Publication series, issues 1–61"),
    ("WM",    "hepatakakupu", "Te Waka Maori o Niu Tirani",                                   "newspaper",   "1871-1879", None),
    ("WMA",   "hepatakakupu", "Te Waka Maori o Ahuriri",                                      "newspaper",   "1863-1871", None),
    ("WMAo",  "hepatakakupu", "Te Waka Maori o Aotearoa",                                     "newspaper",   "1884",      None),

    # ── Books and reference works ─────────────────────────────────────────────
    ("FL",    "hepatakakupu", "Forest Lore of the Maori",                                     "book",        "1942",      "Best, Elsdon"),
    ("GP",    "hepatakakupu", "Games and Pastimes of the Maori",                              "book",        "1925",      "Best, Elsdon"),
    ("IwiT",  "hepatakakupu", "Ngā Iwi o Tainui",                                             "book",        "1995",      None),
    ("KK",    "hepatakakupu", "He Kohinga Kīwaha",                                            "reference",   "1999",      None),
    ("KRK",   "hepatakakupu", "Ngā Kōrero a Reweti Kohere Mā",                                "book",        "1994",      None),
    ("ME",    "hepatakakupu", "Māori-English Tutor and Vade Mecum",                           "book",        None,        None),
    ("MPro",  "hepatakakupu", "Māori Proverbs",                                               "reference",   None,        None),
    ("MR",    "hepatakakupu", "A Māori Reference Grammar",                                    "book",        "1993",      "Harlow, Ray"),
    ("MRM",   "hepatakakupu", "Māori Religion and Mythology",                                 "book",        None,        "Best, Elsdon. 2 vols"),
    ("NAW",   "hepatakakupu", "Notes on the Art of War",                                      "book",        None,        "Best, Elsdon"),
    ("Ng",    "hepatakakupu", "English-Maori Dictionary",                                     "reference",   "1926",      "Ngata, A.T."),
    ("NWK",   "hepatakakupu", "Ngā Waiata me ngā Haka a te Kapa Haka o Te Whare Wānanga o Waikato",
                                                                                              "book",        None,        None),
    ("PR",    "hepatakakupu", "Te Ao o te Whaikōrero",                                        "book",        None,        None),
    ("Tu",    "hepatakakupu", "Tuhoe, Children of the Mist",                                  "book",        "1925",      "Best, Elsdon"),
    ("WotT",  "hepatakakupu", "Te Whetu o te Tau",                                            "other",       None,        "Annual publication"),

    # ── Curriculum and teaching resources ─────────────────────────────────────
    ("HaM",   "hepatakakupu", "Hangarau i roto i te Marautanga o Aotearoa",                   "curriculum",  None,        None),
    ("KWK",   "hepatakakupu", "Ko wai ka hua?",                                               "other",       None,        "Teaching resource"),
    ("NN",    "hepatakakupu", "Te Niwha o te Niwha",                                          "other",       None,        "Teaching resource"),
    ("TaIM",  "hepatakakupu", "Tikanga a Iwi i roto i te Marautanga o Aotearoa",              "curriculum",  None,        None),
    ("TO",    "hepatakakupu", "Taku Ohooho",                                                  "other",       None,        "Teaching resource"),

    # ── Online and broadcast sources ──────────────────────────────────────────
    ("PTR",   "hepatakakupu", "Ngā Putanga Takitaro o te Rangahau",                           "other",       None,        "Online research outputs"),
    ("PTT",   "hepatakakupu", "Te Puna o Te Tai Tokerau",                                     "other",       None,        "Online resource"),
    ("PTa",   "hepatakakupu", "Te Pūranga Tākupu a Taranaki",                                 "other",       None,        "Online resource, Taranaki"),
    ("PWW",   "hepatakakupu", "Panui Whakawa Whenua Maori",                                   "other",       None,        "Māori land court notice series"),
    ("RW",    "hepatakakupu", "Radio Wātea",                                                  "other",       None,        "Māori radio station"),
    ("Tki",   "hepatakakupu", "Te Kete Ipurangi",                                             "other",       None,        "NZ Ministry of Education online resource (tki.org.nz)"),
    ("TPTT",  "hepatakakupu", "Te Papakupu o te Tai Tokerau",                                 "reference",   None,        "Tai Tokerau dialect dictionary, online"),
    ("Tpu",   "hepatakakupu", "Aratohu Pae Tukutuku o Te Puna",                               "other",       None,        "Website"),
]
# fmt: on

ALL_ROWS = TE_AKA_ABBREVS + WILLIAMS_ABBREVS + HEPATAKAKUPU_ABBREVS


def import_abbrevs(conn: sqlite3.Connection, reset: bool) -> None:
    if reset:
        conn.execute("DELETE FROM source_abbreviations")
        print("  cleared existing rows")

    conn.executemany(
        """INSERT OR REPLACE INTO source_abbreviations
               (abbrev, source_dict, full_name, pub_type, year_range, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ALL_ROWS,
    )
    count = conn.execute("SELECT COUNT(*) FROM source_abbreviations").fetchone()[0]
    print(f"  {len(ALL_ROWS)} rows upserted; table total: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import source abbreviation expansions")
    parser.add_argument("--reset", action="store_true", help="Delete all rows before inserting")
    args = parser.parse_args()

    with sqlite3.connect(DB_PATH) as conn:
        import_abbrevs(conn, args.reset)
        conn.commit()
    print("Done.")


if __name__ == "__main__":
    main()
