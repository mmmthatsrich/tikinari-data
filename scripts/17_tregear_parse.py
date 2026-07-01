"""
Parse scraped Tregear (NZETC TEI) letter pages into structured JSON.

Reads sources/tregear/raw/tei-TreMaor-c1-1..c1-15.html (produced by
17_tregear_scrape.py) and writes sources/tregear/tregear_parsed.json — a list of
entry dicts, each with its comparative cognates nested:

  {
    "headword": "HA",
    "pronunciation": "hà",          # from (<i>..</i>); grave/circumflex length marks
    "gloss_en": "breath. Cf. hanene, blowing gently; ... 2. Taste, flavour.",
    "letter": "H",
    "tei_ref": "tei-TreMaor-c1-3#n40",
    "page_no": 40,
    "cognates": [
      {"language": "Hawaiian", "extra_polynesian": 0, "form": "ha",
       "gloss": "ha, to breathe; ...", "seq": 1},
      ...
    ]
  }

Structure of a letter page (verified 2026-07-01):
  <div class="section" ...> <h2>H</h2>
    <p><b>HEADWORD (qualifier)</b> (<i>pron</i>), gloss. Cf. ... 2. sense two.</p>
    <p class="pad-left"><b>Language</b>&mdash;form, gloss; form2, gloss2. </p>
    ...
An entry headword is ALL-CAPS (optionally with a mixed-case "Whaka-" derivational
prefix and a trailing in-bold "(myth.)"/"(passive)"/"(or variant):" qualifier). A
cognate header is a Title-case language name (in <b>, pad-left, or after a dash),
optionally prefixed "Ext. Poly.:" for non-Polynesian Austronesian witnesses. The
first cognate of an entry is occasionally un-bolded and not pad-left (e.g.
"Samoan-fa, ..."). Dashes vary: em (—), en (–), ascii (-), or &mdash;/&ndash;.

Runs offline (no network). Windows-safe UTF-8 output.

Usage:  py 17_tregear_parse.py
"""

import html as htmllib
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RAW_DIR = Path(__file__).parent.parent / "sources" / "tregear" / "raw"
OUT_PATH = Path(__file__).parent.parent / "sources" / "tregear" / "tregear_parsed.json"

# c1-N -> Maori letter section
LETTERS = {1: "A", 2: "E", 3: "H", 4: "I", 5: "K", 6: "M", 7: "N", 8: "NG",
           9: "O", 10: "P", 11: "R", 12: "T", 13: "U", 14: "W", 15: "WH"}

# Canonicalise the core Polynesian language names + their OCR/spelling variants.
LANG_NORM = {
    "hawaiian": "Hawaiian", "hawaii": "Hawaiian",
    "tahitian": "Tahitian", "tahiti": "Tahitian",
    "samoan": "Samoan", "samoa": "Samoan",
    "tongan": "Tongan",
    "mangarevan": "Mangarevan", "mangrevan": "Mangarevan",
    "paumotan": "Paumotan", "paumoutan": "Paumotan",
    "marquesan": "Marquesan", "marquesas": "Marquesan",
    "mangaian": "Mangaian", "mangaia": "Mangaian", "mangaiian": "Mangaian",
    "rarotongan": "Rarotongan",
    "moriori": "Moriori",
    "futuna": "Futuna", "fotuna": "Futuna",
    "niue": "Niue",
    "aniwan": "Aniwa", "aniwa": "Aniwa",
    "sikayana": "Sikayana",
    "fijian": "Fijian", "fiji": "Fijian",
}
# Polynesian languages (extra_polynesian = 0). Everything else Tregear cites
# (Fijian, Malay, Malagasy, Motu, Macassar, Formosa, Java, Aneityum, Tagal, ...)
# is an "Extra Polynesian" Austronesian witness -> extra_polynesian = 1.
POLYNESIAN = {"Samoan", "Tongan", "Hawaiian", "Tahitian", "Marquesan",
              "Mangarevan", "Mangaian", "Rarotongan", "Paumotan", "Moriori",
              "Futuna", "Niue", "Aniwa", "Sikayana"}
# Core set used to recognise the occasional un-bolded first cognate line.
CORE_PLAIN = {"Samoan", "Tongan", "Hawaiian", "Tahitian", "Marquesan",
              "Mangarevan", "Mangaian", "Rarotongan", "Paumotan", "Moriori",
              "Futuna", "Niue"}

DASH = r"(?:&mdash;|&ndash;|—|–|-)"
DASH_SPLIT_RE = re.compile(DASH)
PB_RE = re.compile(r'<span class="pb"[^>]*id="n(\d+)"')
BLOCK_RE = re.compile(r'<p\b[^>]*>.*?</p>|<span class="pb"[^>]*id="n\d+"[^>]*>', re.S)
BOLD_RE = re.compile(r'^\s*<b>(.*?)</b>(.*)$', re.S)
PRON_RE = re.compile(r'</b>\s*\(<i>(.*?)</i>\)')
CAPS_RUN_RE = re.compile(r"[A-ZĀĒĪŌŪ][A-ZĀĒĪŌŪ'\- ]*")
EXTPOLY_RE = re.compile(r'Ext\.?\s*Poly\.?\s*:\s*(.+)$', re.S)


def plain(s: str) -> str:
    """HTML fragment -> collapsed plain text."""
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', htmllib.unescape(s)).strip()


def content_region(html: str) -> str:
    """The dictionary body of a letter page: from <h2>Letter</h2> to the footer nav."""
    m = re.search(
        r'(<h2>[^<]{1,4}</h2>.*?)(?:<div class="footer"|<div id="footer"|Previous Section \| <a)',
        html, re.S)
    if m:
        return m.group(1)
    i = html.find('<h2>')
    return html[i:] if i >= 0 else html


def parse_headword(bold_text: str) -> str | None:
    """Return the entry headword if *bold_text* is an ALL-CAPS headword, else None.

    Handles the mixed-case 'Whaka-' prefix and a trailing in-bold qualifier
    ('AEWA (myth.)' -> 'AEWA';  'Whaka-HA' -> 'Whaka-HA';  'Tongan' -> None).
    """
    mpre = re.match(r'(Whaka[a-z]*-)', bold_text)
    prefix = mpre.group(1) if mpre else ''
    core = bold_text[len(prefix):]
    mc = CAPS_RUN_RE.match(core)
    if not mc:
        return None
    caps = mc.group(0).rstrip()
    tail = core[mc.end():]
    # Entry only if the caps run is not immediately followed by a lowercase letter
    # (a lowercase continuation means it was a Title-case language, e.g. 'Tongan').
    if caps and (not tail or not tail[:1].islower()):
        return (prefix + caps).strip()
    return None


def split_cognate(after_dash: str) -> tuple[str | None, str]:
    """From a comparative block, return (lead_form, full_gloss).

    lead_form is the first comma-delimited token, or None when the block only
    carries a cross-reference ('cf. ...') with no direct reflex.
    """
    gloss = after_dash.strip().strip(';').strip()
    if not gloss:
        return None, gloss
    if re.match(r'(?i)cf\.', gloss):
        return None, gloss
    lead = re.split(r'[,;:]', gloss, 1)[0].strip()
    lead = lead.strip('.').strip()
    return (lead or None), gloss


def parse_page(n: int, html: str) -> list[dict]:
    region = content_region(html)
    stem = f"tei-TreMaor-c1-{n}"
    letter = LETTERS[n]
    entries: list[dict] = []
    cur: dict | None = None
    cur_cog: dict | None = None
    page_no: int | None = None

    for block in BLOCK_RE.finditer(region):
        raw = block.group(0)
        if raw.startswith('<span'):
            page_no = int(PB_RE.match(raw).group(1))
            continue

        inner = re.sub(r'^<p\b[^>]*>|</p>$', '', raw, flags=re.S)
        pad = 'pad-left' in raw
        text = plain(inner)
        if not text:
            continue
        mb = BOLD_RE.match(inner)

        # ── entry headword ────────────────────────────────────────────────
        if mb and not pad:
            hw = parse_headword(plain(mb.group(1)))
            if hw:
                pron = None
                mp = PRON_RE.search(inner)
                if mp:
                    pron = plain(mp.group(1)) or None
                gloss = text[len(hw):].lstrip(" ,")
                # drop a leading "(pron)," that duplicates the pronunciation
                if pron:
                    gloss = re.sub(r'^\(\s*' + re.escape(pron) + r'\s*\)\s*,?\s*', '', gloss)
                cur = {
                    "headword": hw, "pronunciation": pron, "gloss_en": gloss,
                    "letter": letter, "tei_ref": f"{stem}#n{page_no}" if page_no else stem,
                    "page_no": page_no, "cognates": [],
                }
                entries.append(cur)
                cur_cog = None
                continue

        # ── comparative cognate ───────────────────────────────────────────
        lang = None
        ext = None
        after = None
        if mb:
            bt = plain(mb.group(1))
            me = EXTPOLY_RE.match(bt)
            starts_dash = bool(re.match(r'\s*' + DASH, mb.group(2)))
            if me:
                raw_lang = me.group(1).strip()
                lang = LANG_NORM.get(raw_lang.lower(), raw_lang)
                ext = 1
                after = DASH_SPLIT_RE.sub('', mb.group(2), count=1)
            elif (pad or starts_dash) and re.match(r'[A-Z][a-z]', bt) and len(bt) < 40:
                lang = LANG_NORM.get(bt.lower(), bt)
                after = DASH_SPLIT_RE.sub('', mb.group(2), count=1)
        if lang is None:
            # un-bolded first cognate, e.g. "Samoan-fa, ..."
            mp = re.match(r'([A-Z][a-z]+)\s*' + DASH + r'\s*(.*)$', text, re.S)
            if mp and LANG_NORM.get(mp.group(1).lower(), mp.group(1)) in CORE_PLAIN:
                lang = LANG_NORM.get(mp.group(1).lower(), mp.group(1))
                after = mp.group(2)

        if lang is not None and cur is not None:
            if ext is None:
                ext = 0 if lang in POLYNESIAN else 1
            form, cog_gloss = split_cognate(plain(after) if after else text)
            cur_cog = {"language": lang, "extra_polynesian": ext,
                       "form": form, "gloss": cog_gloss,
                       "seq": len(cur["cognates"]) + 1}
            cur["cognates"].append(cur_cog)
            continue

        # ── continuation prose: append to whatever context is open ─────────
        if cur_cog is not None:
            cur_cog["gloss"] = (cur_cog["gloss"] + " " + text).strip()
        elif cur is not None:
            cur["gloss_en"] = (cur["gloss_en"] + " " + text).strip()

    return entries


def main() -> None:
    all_entries: list[dict] = []
    for n in range(1, 16):
        path = RAW_DIR / f"tei-TreMaor-c1-{n}.html"
        if not path.exists():
            print(f"  [warn] missing {path.name} — run 17_tregear_scrape.py first")
            continue
        page_entries = parse_page(n, path.read_text(encoding="utf-8"))
        cog = sum(len(e["cognates"]) for e in page_entries)
        print(f"  c1-{n:<2} {LETTERS[n]:<2} entries={len(page_entries):>4}  cognates={cog:>4}")
        all_entries.extend(page_entries)

    OUT_PATH.write_text(json.dumps(all_entries, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    total_cog = sum(len(e["cognates"]) for e in all_entries)
    print(f"\nParsed {len(all_entries):,} entries, {total_cog:,} cognates -> {OUT_PATH}")


if __name__ == "__main__":
    main()
