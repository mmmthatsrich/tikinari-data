"""Parse the scraped Te Māra Reo pages into sources/temarareo/temarareo_parsed.json.

Reads sources/temarareo/raw/ (from 42_temarareo_scrape.py) and produces three blocks:

  index      — the TMR-Ingoa.html table: one row per Proto-Polynesian form, carrying
               its etymological stage, the Māori name(s) listed against it, and the
               species column.
  protoforms — one per PPN-*.html: protoform(s), level, gloss, the reconstruction
               chain (PAn -> PMP -> POc -> PPn), reflexes across Polynesian languages,
               and cognates in wider Austronesian languages.
  names      — one per TMR-*.html: Māori headword, definition, the same chain, cognate
               words, and the related plant names discussed in prose.

Every page is a Dreamweaver template instance, so content is sliced out of the
`Mara Reo Contents` editable region — the surrounding chrome (19 nav links repeated
on every page) never reaches the parser.

Section headings and banners vary a lot across the 191 pages (surveyed rather than
assumed): 40+ heading spellings — REFLEXES IN SOME POLYNESIAN LANGUAGES, POSSIBLE
REFLEXES…, (PARTIALLY) COGNATE REFLEXES…, ALTERNATIVE MĀORI PLANT NAMES — so headings
are classified by pattern, not matched against a fixed list. Banners likewise: a page
may declare several protoforms (`*Aute [PCE] ~ Aute [Māori]` on four lines), and chain
levels appear in both title case and caps (`PROTO OCEANIC *puRe`).

DELIBERATE NON-GOAL — the index's name/species pairing. In the index table, column 2
(Māori names) and column 3 (species) are aligned only visually, with <br/> runs that
do not correspond one-to-one: the *fara row has 7 names against 9 species lines. That
pairing is therefore NOT reconstructed here. Species are kept as an unordered list on
the row, and authoritative name->species pairs come from the individual pages instead.

Usage:
  py 42_temarareo_parse.py            # parse everything
  py 42_temarareo_parse.py --page PPN-Aka.html   # dump one page as JSON (debugging)
"""

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from utils import canonical_level, normalise_proto_key  # noqa: E402

RAW_DIR = Path(__file__).parent.parent / "sources" / "temarareo" / "raw"
OUT_PATH = Path(__file__).parent.parent / "sources" / "temarareo" / "temarareo_parsed.json"
BASE_URL = "https://www.temarareo.org"
INDEX_PAGE = "TMR-Ingoa.html"

CONTENT_RE = re.compile(
    r'<!--\s*InstanceBeginEditable name="Mara Reo Contents "\s*-->(.*?)<!--\s*InstanceEndEditable\s*-->',
    re.S,
)
# Four pages predate the Dreamweaver template and put their content straight in
# <body>, headed by the site title instead of a nav bar.
BODY_RE = re.compile(r"(?is)<body[^>]*>(.*?)</body>")
SITE_TITLE_RE = re.compile(r"^Te M[äāa]ra Reo\b", re.I)


def content_region(raw: str) -> str | None:
    """The page's content: its editable region, or the whole body as a fallback."""
    m = CONTENT_RE.search(raw)
    if m:
        return m.group(1)
    m = BODY_RE.search(raw)
    return m.group(1) if m else None

# Te Māra Reo writes reconstruction levels out in full; map them onto the ETY_level
# ladder already in the DB (utils.canonical_level then folds PAN/POC spellings).
# Keys are level_key()-normalised. Anything unmapped keeps its name with code = None
# rather than inventing a ladder node — notably "Proto South/East Central Pacific"
# and the Rarotongan/Māori shared level, which the ladder does not carry.
LEVEL_CODES = {
    "proto austronesian": "PAn",
    "proto malayo polynesian": "PMP",
    "proto western malayo polynesian": "PWMP",
    "proto central malayo polynesian": "PCMP",
    "proto eastern malayo polynesian": "PEMP",
    "proto central eastern malayo polynesian": "PCEMP",
    "proto oceanic": "POc",
    "proto western oceanic": "PWOc",
    "proto eastern oceanic": "PEOc",
    "proto remote oceanic": "PROc",
    "proto southern oceanic": "PSOc",
    "proto central pacific": "PCP",
    "proto fijian": "PFij",
    "proto polynesian": "PPn",
    "proto nuclear polynesian": "PNPn",
    "proto eastern polynesian": "EP",
    "proto east polynesian": "EP",
    "proto central eastern polynesian": "PCEPn",
    "proto tahitic": "Proto Tahitic",
    "proto micronesian": "PMic",
    "proto southeast solomonic": "PSES",
    "proto north central vanuatu": "PNCV",
    # Source spellings that are the same node: a typo, an abbreviation, and a
    # variant name for Proto Tahitic.
    "proto austronesan": "PAn",
    "pcep": "PCEPn",
    "proto tahitian": "Proto Tahitic",
}

# Hedges the source puts in front of a level ("Possibly Proto-Tahitic", "? Proto
# Eastern Polynesian"), stripped before lookup.
HEDGE_RE = re.compile(
    r"^(?:\(?\s*(?:possibly|probably|perhaps|apparently|presumably|likely)\s*\)?|\?)\s*",
    re.I)

# `*Aka [Proto Polynesian]`, repeated when a page covers several protoforms, and
# optionally followed by `~ Aka [Māori]` giving the Māori reflex.
# The closing bracket is optional before a `~`: PPN-Piripiri.html drops it
# (`*Piri-Piri [Proto Central Eastern Polynesian ~ Piripiri [Māori]`).
BANNER_RE = re.compile(r"\*\s*~?\s*([^\[\]~*]+?)\s*\[\s*([^\[\]~]+?)\s*(?:\]|(?=~))"
                       r"(?:\s*~\s*\*?\s*([^\[\]~*]+?)\s*\[\s*[^\[\]]*?\])?")
# Some pages state the protoform with no bracket at all (`*Futu`), leaving the level
# to the chain below.
# `*Futu`, and the two-variant form `*Hulufe ~ *Sulufe`.
BARE_BANNER_RE = re.compile(
    r"^\*\s*~?\s*([A-Za-zāēīōūĀĒĪŌŪ'’()\-,]{2,30})"
    r"(?:\s*~\s*\*?\s*([A-Za-zāēīōūĀĒĪŌŪ'’()\-,]{2,30}))?\s*$")
# A bracket only names a reconstruction level if it says so; the same syntax is used
# for asides like `*aute [made from paper mulberry bast]`.
LEVEL_BRACKET_RE = re.compile(
    r"proto|māori|maori|rarotongan|hawaiian|tahitian|polynesian|oceanic|austronesian",
    re.I)
# A chain step: `Proto Oceanic *akar "root"`, `PROTO OCEANIC *puRe, …`,
# `through PROTO POLYNESIAN *fue`, `(1) from Proto Remote Oceanic *Raka …`.
CHAIN_RE = re.compile(
    r"^(?:\(\d\)\s*)?(?:and,?\s*)?(?:from\s+|through\s+)*"
    r"(proto[\s\-][a-z\- ]+?)\s*[:,]?\s*\*\s*([^\s,\"“]+)\s*,?\s*(.*)$",
    re.I,
)
# A per-language line: `Tongan: aka "root"` / `Tahitian, Marquesan, Rarotongan: aka "root"`.
LANG_RE = re.compile(r"^([A-Z][A-Za-zāēīōū’'\- ]*(?:,\s*[A-Z][A-Za-zāēīōū’'\- ]*)*)"
                     r"(\s*\([^)]*\))?\s*:\s*(.+)$")
# A related-name line: `Akakiore, Akakaikiore [Rat (food) vine] (Parsonsia heterophylla, …).`
RELATED_RE = re.compile(r"^([A-Za-zāēīōūĀĒĪŌŪ’'\-]+(?:,\s*[A-Za-zāēīōūĀĒĪŌŪ’'\-]+)*)\s*"
                        r"\[([^\]]+)\]\s*(.*)$")
# Binomial: `Metrosideros excelsa`, `Astelia spp.`, `M. albiflora`.
BINOMIAL_RE = re.compile(r"\b([A-Z][a-z]{2,}|[A-Z]\.)\s+((?:spp?|[a-z]{3,})\.?)\b")
QUOTED_RE = re.compile(r"[\"“]([^\"”]+)[\"”]")

# Capitalised words that open a sentence and would otherwise be read as a genus
# ("The original meaning…" -> "The original").
NOT_GENUS = {
    "The", "This", "That", "These", "Those", "There", "Their", "They", "Its", "It",
    "And", "But", "For", "From", "With", "When", "Where", "What", "While", "Which",
    "New", "Some", "Many", "Most", "All", "Both", "Also", "However", "Although",
    "Because", "Since", "Photo", "Photos", "Photograph", "Photographs", "See",
    "Note", "Notes", "Further", "Left", "Right", "Above", "Below", "Other",
    "Another", "Each", "Such", "Like", "Only", "More", "Less", "One", "Two",
    "Three", "Probably", "Possibly", "Perhaps", "Originally", "Later", "Now",
    "Formerly", "Generic", "Alternative", "Name", "Names", "Word", "Words",
    "Maori", "Māori", "English", "Polynesian", "Proto", "Compare", "Used", "Any",
}

# Prose labels that look like a language prefix but are not. Longer prose is caught
# by the word cap in parse_langs (real language names run to at most three words —
# "Cook Islands Maori", "Wayan Fijian" — while these run to whole sentences).
NOT_LANGUAGE = {
    "further information", "photographs", "photograph", "photo", "note", "notes",
    "sources", "source", "references", "reference", "bibliography", "see also",
    "acknowledgements", "acknowledgement", "illustration", "illustrations",
    "caption", "above", "below", "left", "right", "top", "bottom", "warning",
    "update", "revised", "citation", "citations", "introduction", "appearance",
    "distribution", "association", "further reading", "description", "uses", "use",
    "history", "cultivation", "habitat", "conservation", "status", "origin",
    "origins", "discussion", "summary", "background", "etymology", "taxonomy",
    "kjv", "in the garden", "te mara reo", "te māra reo", "related words",
}

# Language names the source spells more than one way, or misspells; folded so one
# language is one name before the ETY_language resolver ever sees it.
LANGUAGE_ALIASES = {
    "māori": "Maori", "maori": "Maori", "hawaian": "Hawaiian",
    "ilokano": "Ilocano", "bau": "Bauan", "east uvea": "East Uvean",
    "chūk": "Chuukese", "chuuk": "Chuukese",
}
MAX_LANGUAGE_WORDS = 3
# Words that never open a language name; they mark a chain step or a continuation
# of prose that happens to carry a colon.
NOT_LANGUAGE_LEAD = {
    "from", "through", "and", "also", "but", "note", "compare", "cf", "see",
    "proto", "possibly", "probably", "perhaps", "in", "on", "at", "the", "a",
}


def is_language(name: str) -> bool:
    """Whether a colon-prefixed label is plausibly a language name.

    Real names are one to three capitalised words — "Tongan", "Wayan Fijian",
    "Cook Islands Maori". This rejects the two shapes that otherwise slip through:
    a plant-name list on a Hawaiian page (`Kūkae 'iole:`, `Kōwhai kura:`), whose
    later words are lowercase, and chain fragments like `From Proto-Rarotongan-Māori`.
    """
    words = name.split()
    if not words or len(words) > MAX_LANGUAGE_WORDS:
        return False
    if name.lower() in NOT_LANGUAGE or words[0].lower() in NOT_LANGUAGE_LEAD:
        return False
    return all(w[:1].isupper() for w in words if w)


def find_species(text: str) -> list[str]:
    """Scientific binomials in *text*, ignoring anything inside quotes.

    The source quotes English common names and leaves Latin unquoted, so dropping
    quoted spans first stops `"Kudzu vine"` and `"New Zealand Jasmine"` being read
    as binomials. A NOT_GENUS guard then rejects ordinary sentence openings.
    """
    out = set()
    for genus, epithet in BINOMIAL_RE.findall(QUOTED_RE.sub(" ", text)):
        if genus in NOT_GENUS:
            continue
        out.add(f"{genus} {epithet}")
    return sorted(out)


def to_lines(fragment: str) -> list[str]:
    """Flatten an HTML fragment to text lines, keeping <br>/block breaks as newlines."""
    fragment = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment)
    fragment = re.sub(r"(?is)<!--.*?-->", " ", fragment)
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</(p|tr|td|div|h[1-6]|li|table)\s*>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = htmllib.unescape(fragment).replace("\xa0", " ")
    out = []
    for line in fragment.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            out.append(line)
    return out


# A line that is only the start of a level name, left dangling by a wrapped <br/>.
DANGLING_RE = re.compile(
    r"^(?:and,?\s*)?(?:\(\d\)\s*)?(?:from\s+|through\s+)*proto[\s\-a-z]*$", re.I)
# A line that begins a chain step in its own right.
STEP_START_RE = re.compile(
    r"^(?:\(\d\)\s*)?(?:and,?\s*)?(?:from\s+|through\s+)*proto\b", re.I)


def join_wrapped(lines: list[str]) -> list[str]:
    """Rejoin chain steps broken mid-name by a wrapped <br/>.

    The source wraps long level names, leaving a bare `Proto` / `Proto Remote` on its
    own line with the rest following; without this the step is dropped as unparseable.
    A dangling fragment is only joined to a continuation — never to a line that starts
    a step of its own, which would otherwise produce `Proto Oceanic Proto Oceanic`.
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        # `PROTO-POLYNESIAN ETYMOLOGIES` also matches DANGLING_RE, so without the
        # heading guard every PPN page's banner heading was glued onto the protoform
        # line below it and then misread as a level name.
        while (i + 1 < len(lines) and "*" not in cur and DANGLING_RE.match(cur)
               and heading_of(cur) is None
               and not STEP_START_RE.match(lines[i + 1])):
            cur = f"{cur} {lines[i + 1]}".strip()
            i += 1
        out.append(re.sub(r"\s+", " ", cur))
        i += 1
    return out


# `From Proto Oceanic Proto Oceanic *bala` and `Proto Central Eastern Polynesian
# Polynesian: *Naupata` are typos in the source; collapse the repeated run.
DUP_RE = re.compile(r"\b((?:\w+\s+){0,3}?\w+)\s+\1\b", re.I)


def level_key(name: str) -> str:
    """Fold a level name for lookup: case, hyphens, slashes and duplicated runs.

    Brackets, hyphens and slashes all fold to spaces, and a stray `?` (the source's
    `Proto Polynesian (?)` hedge) is dropped, so one spelling reaches the lookup.
    """
    key = re.sub(r"[\-/()?]", " ", (name or "").lower())
    key = re.sub(r"\s+", " ", key).strip()
    for _ in range(3):
        collapsed = re.sub(r"\s+", " ", DUP_RE.sub(r"\1", key)).strip()
        if collapsed == key:
            break
        key = collapsed
    return key


def level_code(name: str) -> str | None:
    """Map a level name onto an ETY_level code, tolerating how the source writes it.

    Beyond case and hyphens, a bracket often carries a hedge and a whole ancestry
    clause — `Probably Proto-Polynesian, from Proto-Fijiic *Nungka`. The level being
    asserted is the head of that phrase, so hedges are stripped and the text before
    the first comma / `from` is tried before giving up.
    """
    if not name:
        return None
    candidates = [name]
    stripped = HEDGE_RE.sub("", name).strip()
    if stripped != name:
        candidates.append(stripped)
    head = re.split(r",| from | through | ultimately |;", stripped, maxsplit=1)[0]
    if head != stripped:
        candidates.append(head)
    for cand in candidates:
        code = LEVEL_CODES.get(level_key(cand))
        if code:
            return canonical_level(code)
    return None


def heading_of(line: str) -> str | None:
    """Classify a line as a section heading, by pattern rather than exact match.

    Returns one of banner | chain | reflexes | cognates | related | related_names |
    construction, or None for ordinary content. Headings are set in caps, so a line
    with more than a couple of lowercase letters is content — this keeps bare content
    lines like `Proto Polynesian` or `Kawariki` from being read as headings.
    """
    s = line.rstrip(" :.").strip()
    if not (6 < len(s) < 90):
        return None
    # Headings are normally in caps; the untemplated pages set a few in title case
    # ("Etymology:"), which is only accepted when the line is exactly that label.
    if sum(c.islower() for c in s) > 2:
        if not (line.rstrip().endswith(":")
                and s.lower() in {"etymology", "etymologies", "related words",
                                  "maori reflex", "māori reflex"}):
            return None
    u = re.sub(r"\s+", " ", s.upper())
    if "UNDER CONSTRUCTION" in u or "EARLY STAGES OF CONSTRUCTION" in u:
        return "construction"
    # `PROTO-POLYNESIAN ETYMOLOGIES` is the page banner; a bare `ETYMOLOGY` is the
    # chain heading on a Māori-name page.
    if "ETYMOLOGIES" in u:
        return "banner"
    if "ETYMOLOGY" in u:
        return "chain"
    if "REFLEX" in u or "COGNATE" in u:
        return "cognates" if "AUSTRONESIAN" in u else "reflexes"
    if "PLANT NAMES" in u or "ALTERNATIVE NAMES" in u or u.endswith("MĀORI NAMES"):
        return "related_names"
    if "RELATED WORDS" in u:
        return "related"
    return None


def split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]], bool]:
    """Split page lines into (preamble, {section: lines}, under_construction)."""
    preamble: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    construction = False
    for line in lines:
        sec = heading_of(line)
        if sec is not None:
            if sec == "construction":
                construction = True
                continue
            current = None if sec == "banner" else sec
            if current:
                sections.setdefault(current, [])
            continue
        if current is None:
            preamble.append(line)
        else:
            sections[current].append(line)
    return preamble, sections, construction


def parse_banners(lines: list[str]) -> list[dict]:
    """Extract every `*Form [Level] ~ Reflex [Māori]` declaration on a page."""
    out, seen = [], set()
    for line in lines:
        for form, lvl, reflex in BANNER_RE.findall(line):
            form = form.strip(" *,;.")
            lvl = re.sub(r"\s+", " ", lvl).strip()
            if not form or not LEVEL_BRACKET_RE.search(lvl):
                continue
            if (form.lower(), lvl.lower()) in seen:
                continue
            seen.add((form.lower(), lvl.lower()))
            out.append({
                "form": form,
                "level_name": lvl,
                "level_code": level_code(lvl),
                "maori_reflex": (reflex or "").strip(" *,;.") or None,
            })
    if out:
        return out
    # Fall back to a bare `*Futu` declaration, level left for the chain to supply.
    for line in lines:
        bm = BARE_BANNER_RE.match(line)
        if bm:
            return [{"form": f.strip(" *~,;."), "level_name": None,
                     "level_code": None, "maori_reflex": None}
                    for f in bm.groups() if f and f.strip(" *~,;.")]
    return out


def parse_chain(lines: list[str]) -> list[dict]:
    """Extract ordered reconstruction steps from an ETYMOLOGY / `From …` block."""
    chain: list[dict] = []
    seen: set = set()
    for line in lines:
        m = CHAIN_RE.match(line)
        if not m:
            continue
        level_name = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",")
        form = m.group(2).strip().strip(',;."')
        rest = m.group(3).strip()
        quoted = QUOTED_RE.search(rest)
        gloss = quoted.group(1).strip() if quoted else None
        if not form:
            continue
        code = level_code(level_name)
        # A page restates its own protoform after the chain (`Proto Polynesian: *Aka`).
        # Drop a repeat that adds no gloss, but keep genuine same-level homonyms, which
        # the source distinguishes by giving each its own gloss.
        key = (code or level_key(level_name), form.lower())
        if key in seen and not gloss:
            continue
        seen.add(key)
        chain.append({
            "level_name": level_name,
            "level_code": code,
            "form": form,
            "proto_key": normalise_proto_key(form),
            "gloss": gloss,
            "raw": line,
        })
    return chain


def parse_langs(lines: list[str], kind: str) -> list[dict]:
    """Extract per-language reflex rows.

    Following the Tregear precedent, one row per (page, language): `form` is the lead
    comparative form and `gloss` keeps the full comparative text, rather than
    over-splitting multi-sense lines like `aka "root"; aka "kudzu vine" (…)`. Image
    captions interleaved in these blocks carry no `Language:` prefix and fall through.
    """
    out = []
    for line in lines:
        m = LANG_RE.match(line)
        if not m:
            continue
        langs = [l.strip() for l in m.group(1).split(",") if l.strip()]
        qualifier = (m.group(2) or "").strip().strip("()") or None
        value = m.group(3).strip()
        if not value or len(langs) > 6:
            continue
        lead = QUOTED_RE.split(value)[0].strip() if QUOTED_RE.search(value) else value
        form = re.split(r"[;(]", lead)[0].strip().strip(",.") or None
        for lang in langs:
            if not is_language(lang):
                continue
            lang = LANGUAGE_ALIASES.get(lang.lower(), lang)
            out.append({
                "language": lang,
                "qualifier": qualifier,
                "form": form,
                "gloss": value,
                "kind": kind,
            })
    return out


def parse_related_names(lines: list[str]) -> list[dict]:
    """Extract the `Name [Literal meaning] (Species, Family)` plant names from prose.

    Only lines matching that shape are taken; surrounding discussion is left alone.
    These are prose-attested names, not headwords with pages of their own, so they
    become relations on the parent entry rather than entries in their own right.
    """
    out = []
    for line in lines:
        m = RELATED_RE.match(line)
        if not m:
            continue
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        literal = m.group(2).strip()
        rest = m.group(3).strip()
        if not names or len(names) > 6:
            continue
        out.append({
            "names": names,
            "literal_meaning": literal,
            "species": find_species(rest),
            "note": rest[:600] or None,
        })
    return out


def parse_further_info(lines: list[str]) -> str | None:
    for line in lines:
        if line.lower().startswith("further information"):
            return line.split(":", 1)[-1].strip() or None
    return None


def parse_detail_page(path: Path) -> dict | None:
    region = content_region(path.read_text(encoding="utf-8"))
    if not region:
        return None
    lines = [l for l in join_wrapped(to_lines(region)) if not SITE_TITLE_RE.match(l)]
    if not lines:
        return None

    preamble, sections, construction = split_sections(lines)
    is_ppn = path.name.upper().startswith("PPN")

    # Banners are declared in the first few content lines, before any prose.
    banners = parse_banners(preamble[:8])

    # The chain lives under ETYMOLOGY on TMR pages, but sits unheaded in the preamble
    # on PPN pages (introduced by a bare `From`), so scan both.
    chain = parse_chain(sections.get("chain", [])) or parse_chain(preamble)

    reflexes = parse_langs(sections.get("reflexes", []), "polynesian")
    cognates = parse_langs(sections.get("cognates", []), "austronesian")

    # Prose = preamble minus banner and chain lines, so neither can be read as a gloss.
    chain_raw = {c["raw"] for c in chain}
    prose = [l for l in preamble
             if l not in chain_raw and not CHAIN_RE.match(l)
             and not BANNER_RE.search(l)
             and l.lower().rstrip(":.") not in {"from", "through"}]

    # On a PPN page the banner form is the headword; on a TMR page the Māori name is
    # the first prose line, falling back to the banner's `~ Reflex [Māori]` part and
    # finally to the page stem, so a stub page still yields a usable headword.
    if is_ppn:
        headword = banners[0]["form"] if banners else None
        gloss = prose[0] if prose else None
        note = " ".join(prose[1:3]) or None
    else:
        # A name page heads with its Māori name, sometimes annotated the same way the
        # index annotates one (`Koromiko [Word originating in Aotearoa]`), so it goes
        # through clean_name too. A first line that is a definition, or a stage
        # description rather than a name, falls through to the banner reflex.
        # Scan the first few prose lines rather than only the first: TMR-Karo.html
        # has a malformed template marker that leaves the literal text "Mara Reo
        # Contents" ahead of the name.
        cleaned, at = None, 0
        for i, line in enumerate(prose[:3]):
            if len(line) <= 60 and (cleaned := clean_name(line)):
                at = i
                break
        headword = cleaned["name"] if cleaned else None
        head_note = cleaned.get("note") if cleaned else None
        if headword:
            gloss = prose[at + 1] if len(prose) > at + 1 else None
            note = " ".join(filter(None, [head_note, *prose[at + 2:at + 4]])) or None
        else:
            headword = (next((b["maori_reflex"] for b in banners if b["maori_reflex"]), None)
                        or path.stem.split("-", 1)[-1])
            gloss = prose[0] if prose else None
            note = " ".join(prose[1:3]) or None

    # A bare `*Futu` banner states no level; the page's own chain does, so adopt the
    # level of the chain step that reconstructs the same form rather than guessing.
    for banner in banners:
        if banner["level_code"] or banner["level_name"]:
            continue
        key = normalise_proto_key(banner["form"])
        match = next((c for c in chain if c["proto_key"] == key), None)
        if match:
            banner["level_name"] = match["level_name"]
            banner["level_code"] = match["level_code"]

    # A name page often heads with the two or three related names it covers
    # ("Wharawhara, Pūwharawhara, Kōwharawhara"). Each is a real plant name, so the
    # list is split out; `headword` stays the first for callers that want just one.
    headwords = []
    if headword and not is_ppn:
        headwords = [i["name"] for i in split_names(headword)]
    if headwords:
        headword = headwords[0]

    return {
        "page": path.name,
        "url": f"{BASE_URL}/{path.name}",
        "kind": "protoform" if is_ppn else "name",
        "headword": headword,
        "headwords": headwords or ([headword] if headword else []),
        "protoforms": banners,
        "gloss": gloss,
        "note": note or None,
        "species": find_species(" ".join(prose[:3])),
        "chain": chain,
        "reflexes": reflexes,
        "cognates": cognates,
        "related_names": parse_related_names(sections.get("related_names", [])),
        "related_words": " ".join(sections.get("related", []))[:4000] or None,
        "further_info": parse_further_info(lines),
        "under_construction": construction,
    }


# --- index table ----------------------------------------------------------

CELL_RE = re.compile(r"(?is)<td\b[^>]*>(.*?)</td>")
ROW_RE = re.compile(r"(?is)<tr\b[^>]*>(.*?)</tr>")
# `1. P. Austronesian origin` / `12. Words shared exclusively by …` / `14 Acquired`.
# The dot is optional — stage 14 is written without one.
STAGE_RE = re.compile(r"^\s*(\d+)\s*\.?\s+(\D.*?)\s*$")
LINK_RE = re.compile(r'(?is)<a\b[^>]*href="([^"#]+)[^"]*"[^>]*>(.*?)</a>')


def cell_text(cell: str) -> str:
    return " ".join(to_lines(cell))


# A name in the index may carry a trailing annotation — a homonym marker
# (`parapara [1]`), a provenance note (`Koromiko [Word originating in Aotearoa]`)
# or an alternative spelling (`tī (tii)`).
NAME_ANNOT_RE = re.compile(r"^(.*?)\s*\[([^\]]*)\]\s*$")
NAME_VARIANT_RE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")
# Words that mark a stage description rather than a plant name — the index puts a
# couple of these in the name column ("Word endemic to Aotearoa").
NOT_A_NAME = re.compile(r"\b(word|words|endemic|originating|via|from|local|"
                        r"english|polynesian|aotearoa|borrowed|acquired|"
                        r"contents|mara reo)\b", re.I)


def split_names(raw: str) -> list[dict]:
    """Split a name cell into its individual names.

    The index puts related names in one cell, separated by a comma, a semicolon, a
    tilde or a dash ("aka, aka-", "pōhue; pōhuehue, pōpōhue", "Aruhe ~ Rauaruhe");
    each is a name in its own right, so each becomes its own entry.
    """
    out, seen = [], set()
    for part in re.split(r"[,;~/]|\s--+\s", raw or ""):
        item = clean_name(part)
        if item and item["name"] not in seen:
            seen.add(item["name"])
            out.append(item)
    return out


def clean_name(raw: str) -> dict | None:
    """Split an index name into its headword, homonym number, variant and note.

    Returns None for a cell that is a stage description rather than a name.
    """
    name = re.sub(r"\s+", " ", raw).strip().lstrip("*").strip()
    homonym = None
    note = None
    variant = None

    m = NAME_ANNOT_RE.match(name)
    if m:
        name, annot = m.group(1).strip(), m.group(2).strip()
        if annot.isdigit():
            homonym = int(annot)
        elif annot:
            note = annot

    m = NAME_VARIANT_RE.match(name)
    if m and m.group(2).strip():
        name, variant = m.group(1).strip(), m.group(2).strip()

    if not name or len(name.split()) > 3 or NOT_A_NAME.search(name):
        return None
    return {"name": name, "homonym_no": homonym, "variant": variant, "note": note}


def parse_index(path: Path) -> list[dict]:
    """Parse TMR-Ingoa.html into one row per Proto-Polynesian form.

    Rows whose first cell is a `N. Stage name` heading set the stage carried by every
    following row. Column 3 species are kept as an unordered list — see the module
    docstring on why they are NOT paired with column 2 names.
    """
    region = content_region(path.read_text(encoding="utf-8")) or path.read_text(encoding="utf-8")

    rows = []
    stage_no, stage_name, stage_note = None, None, None
    for row_html in ROW_RE.findall(region):
        cells = CELL_RE.findall(row_html)
        if len(cells) != 3:
            continue
        texts = [cell_text(c) for c in cells]
        first = texts[0]

        # Stage heading row: `N. Stage name` in column 1 and an empty species column.
        # Column 2 is NOT required to be empty — stages 6/9/10/11 carry a scope note
        # there ("[Incl. Marquesas]"), and requiring it empty silently left their rows
        # inheriting the previous stage.
        sm = STAGE_RE.match(first)
        if sm and not texts[2] and not LINK_RE.search(cells[0]):
            stage_no = int(sm.group(1))
            stage_name = sm.group(2)
            stage_note = texts[1] or None
            continue
        if first.lower().startswith("proto-polynesian name"):
            continue
        if not first or not (texts[1] or texts[2]):
            continue

        ppn_links = LINK_RE.findall(cells[0])
        mi_links = LINK_RE.findall(cells[1])
        ppn_form = cell_text(ppn_links[0][1]) if ppn_links else first
        # `*aka [1,3]` — the bracketed digits are stage cross-references.
        stages = re.findall(r"\d+", "".join(re.findall(r"\[([\d,\s]+)\]", first)))

        names, seen = [], set()
        for href, label in mi_links:
            for item in split_names(cell_text(label)):
                if item["name"] in seen:
                    continue
                seen.add(item["name"])
                names.append({**item, "page": href.strip()})
        # Names not wrapped in a link still belong to the row.
        for extra in to_lines(re.sub(r"(?is)<a\b.*?</a>", " ", cells[1])):
            if not re.fullmatch(r"[A-Za-zāēīōūĀĒĪŌŪ’'\-()\[\]0-9 ,;]{2,60}", extra):
                continue
            for item in split_names(extra):
                if item["name"] in seen:
                    continue
                seen.add(item["name"])
                names.append({**item, "page": None})

        # Column 3 mixes binomials with free prose ("The original meaning of 'a root'
        # later became merged with…"). A species line is a short label carrying a
        # binomial; the notes are full sentences, so length separates them reliably.
        species, notes = [], []
        for line in to_lines(cells[2]):
            is_species = bool(find_species(line)) and len(line.split()) <= 8
            (species if is_species else notes).append(line)

        rows.append({
            "stage_no": stage_no,
            "stage_name": stage_name,
            "stage_note": stage_note,
            "ppn_form": ppn_form.lstrip("*").strip(),
            "ppn_page": ppn_links[0][0].strip() if ppn_links else None,
            "stage_refs": [int(s) for s in stages],
            "maori_names": names,
            "species": species,
            "note": " ".join(notes) or None,
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Te Māra Reo parser")
    ap.add_argument("--page", metavar="FILE", help="Parse one page and print its JSON.")
    args = ap.parse_args()

    if args.page:
        path = RAW_DIR / args.page
        data = parse_index(path) if path.name == INDEX_PAGE else parse_detail_page(path)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    index_rows = parse_index(RAW_DIR / INDEX_PAGE)

    protoforms, names, skipped = [], [], []
    for path in sorted(RAW_DIR.glob("*.html")):
        if path.name == INDEX_PAGE:
            continue
        rec = parse_detail_page(path)
        if rec is None or not rec["headword"]:
            skipped.append(path.name)
            continue
        (protoforms if rec["kind"] == "protoform" else names).append(rec)

    out = {"index": index_rows, "protoforms": protoforms, "names": names}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    pages = protoforms + names
    n_chain = sum(len(p["chain"]) for p in pages)
    n_reflex = sum(len(p["reflexes"]) + len(p["cognates"]) for p in pages)
    n_related = sum(len(p["related_names"]) for p in pages)
    idx_names = {n["name"] for r in index_rows for n in r["maori_names"]}
    unmapped = sorted({s["level_name"] for p in pages for s in p["chain"]
                       if not s["level_code"] and s["level_name"]}
                      | {b["level_name"] for p in pages for b in p["protoforms"]
                         if not b["level_code"] and b["level_name"]})

    print(f"Parsed -> {OUT_PATH}")
    print(f"  index rows:        {len(index_rows):,}  "
          f"({len(idx_names):,} distinct Māori names, "
          f"{len({r['stage_no'] for r in index_rows}):,} stages)")
    print(f"  protoform pages:   {len(protoforms):,}")
    print(f"  name pages:        {len(names):,}")
    print(f"  chain steps:       {n_chain:,}")
    print(f"  language reflexes: {n_reflex:,}")
    print(f"  related names:     {n_related:,}")
    print(f"  under construction:{sum(1 for p in pages if p['under_construction']):,}")
    if skipped:
        print(f"  SKIPPED (no headword): {len(skipped)} -> {', '.join(skipped[:8])}")
    if unmapped:
        print(f"  UNMAPPED levels ({len(unmapped)}): {'; '.join(unmapped[:12])}")


if __name__ == "__main__":
    main()
