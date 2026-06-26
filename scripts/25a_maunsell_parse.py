"""
Parse Maunsell OCR text files into JSON dictionary entries.

Reads sources/maunsell/ocr/page_NNN.txt (pages 147-244; 145-146 are pre-vocabulary).
Writes sources/maunsell/parsed/maunsell_entries.json.

Each entry:
  headword, part_of_speech, definition, usage_examples,
  pdf_page, book_page, is_name_only, ocr_flags

Usage:
  py scripts/25a_maunsell_parse.py
"""

import sys, re, json, glob
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

OCR_DIR    = Path(__file__).parent.parent / "sources" / "maunsell" / "ocr"
OUTPUT     = Path(__file__).parent.parent / "sources" / "maunsell" / "parsed" / "maunsell_entries.json"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# Pre-vocabulary pages (Lord's Prayer + Table of Abbreviations)
SKIP_PAGES = {145, 146}

# Normalise curly/smart quotes to ASCII apostrophe so regex character classes work
def normalise_quotes(line: str) -> str:
    return line.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')

# Strip leading OCR noise chars from a line
_NOISE_PREFIX = re.compile(r"^[\|_\-:\'` .]+")

def strip_noise(line: str) -> str:
    return _NOISE_PREFIX.sub("", normalise_quotes(line)).strip()

# Lines that are just noise (pipes, dashes, whitespace)
_PURE_NOISE = re.compile(r"^[\|_\-: .\'`]+$")

# Page number line: ( 130 ) or variants with noise chars
_PAGE_NUM = re.compile(r"^[\|_\-: ]*\(\s*\d+\s*\)[\|_\-: ]*$")

# Letter section headers: "A.", "Oo.", "NG.", "W." etc. on their own line
_SECTION_HDR = re.compile(r"^[A-Z][A-Za-z]*\.\s*$")

# Lines that should NOT start a new entry even if capitalised
_EXCLUDE_STARTS = re.compile(
    r"^(?:NOTE|NoTE|TABLE|THE\s|Causative|Also[,;\s]|APPENDIX|"
    r"Substantive|Adjective|Pronoun|Verbal|Adverb|Preposition|Conjunction|Interjection)",
    re.IGNORECASE,
)

# Entry start: capital letter + comma or semicolon within 65 chars
_ENTRY_START = re.compile(r"^([A-Z\'][A-Za-z\'\- éàáíóū.]{0,64}?)\s*[,;]")

# POS abbreviations recognised in Maunsell's vocabulary
_POS_PATTERN = re.compile(
    r"^((?:(?:s|a|p|c|int|ad|prep|v\.n|v\.t|v\.n\.|v\.t\.|v\.2|7\.n|7\.2|v\.7|ven|w\.n)\."
    r"(?:\s+(?:and\s+)?(?:s|a|p|c|int|ad|prep|v\.n|v\.t|v\.n\.|v\.t\.|v\.2|7\.n|7\.2|v\.7|ven|w\.n)\.)*"
    r"))\s+"
)

_POS_NORMALISE = [
    (re.compile(r"\bv\.2\."), "v.n."),
    (re.compile(r"\b7\.n\."), "v.n."),
    (re.compile(r"\b7\.2\."), "v.n."),
    (re.compile(r"\bv\.7\."), "v.n."),
    (re.compile(r"\bven\."),  "v.n."),
    (re.compile(r"\bw\.n\."), "v.n."),
    (re.compile(r"\b2\."),    "a."),
]

def normalise_pos(s: str) -> str:
    for pat, repl in _POS_NORMALISE:
        s = pat.sub(repl, s)
    return s.strip()

# Name-only entries: definition is just a proper-name note
_NAME_ONLY = re.compile(
    r"^(?:(?:Also\s+)?(?:the\s+)?(?:proper\s+)?)?[Nn]ame\s+of\s+(?:a|the)\s+"
    r"(?:certain\s+)?(?:person|place|fish|bird|tree|plant|shrub|river|hill|god|village)\b",
    re.IGNORECASE,
)

# Usage examples: anything inside double quotes
_EXAMPLES = re.compile(r'"([^"]{4,120})"')

# Headword artifact flags
def ocr_flags(headword: str) -> list[str]:
    flags = []
    if re.search(r"\d", headword):
        flags.append("headword_has_digits")
    if len(headword) > 40:
        flags.append("headword_too_long")
    return flags


def is_entry_start(line: str) -> bool:
    clean = strip_noise(line)
    if not clean or not clean[0].isupper():
        return False
    if _EXCLUDE_STARTS.match(clean):
        return False
    if _SECTION_HDR.match(clean):
        return False
    return _ENTRY_START.match(clean) is not None


def parse_first_line(line: str) -> tuple[str, str | None, str]:
    """Return (headword, part_of_speech, definition_start)."""
    clean = strip_noise(line)
    m = re.match(r"^([A-Z\'][A-Za-z\'\- éàáíóū.]{0,64}?)\s*[,;]\s*(.*)", clean, re.DOTALL)
    if not m:
        return clean, None, ""
    headword = m.group(1).strip().rstrip(".")
    rest = m.group(2).strip()
    # Try to peel off POS abbreviation(s) from the start of rest
    pos_m = _POS_PATTERN.match(rest)
    if pos_m:
        pos = normalise_pos(pos_m.group(1))
        definition = rest[pos_m.end():].strip()
    else:
        pos = None
        definition = rest
    return headword, pos, definition


def finalise(entry: dict) -> dict:
    lines = entry.pop("_def_lines", [])
    defn = " ".join(lines)
    defn = re.sub(r"\s+", " ", defn).strip()
    # Strip trailing noise chars
    defn = defn.rstrip("|_-: ").rstrip()
    entry["definition"] = defn
    entry["is_name_only"] = bool(_NAME_ONLY.match(defn))
    entry["usage_examples"] = _EXAMPLES.findall(defn)
    return entry


# ── Main pass ────────────────────────────────────────────────────────────────

entries: list[dict] = []
current: dict | None = None

txt_files = sorted(OCR_DIR.glob("page_*.txt"))

for txt_path in txt_files:
    # Extract PDF page number from filename
    fn_match = re.search(r"page_(\d+)\.txt$", txt_path.name)
    if not fn_match:
        continue
    pdf_page_fn = int(fn_match.group(1))
    if pdf_page_fn in SKIP_PAGES:
        continue

    lines = txt_path.read_text(encoding="utf-8").splitlines()

    # Parse header line
    pdf_page = pdf_page_fn
    book_page = None
    if lines and lines[0].startswith("#"):
        hdr = re.search(r"PDF_PAGE=(\d+)\s+BOOK_PAGE=(\S+)", lines[0])
        if hdr:
            pdf_page = int(hdr.group(1))
            bp = hdr.group(2)
            book_page = int(bp) if bp.isdigit() else None
        lines = lines[1:]

    for line in lines:
        line = normalise_quotes(line.rstrip("\r\n"))

        # Skip page-number noise
        if _PAGE_NUM.match(line):
            continue
        # Skip pure-noise lines
        if not line.strip() or _PURE_NOISE.match(line):
            continue

        if is_entry_start(line):
            if current:
                entries.append(finalise(current))
            hw, pos, def_start = parse_first_line(line)
            current = {
                "headword": hw,
                "part_of_speech": pos,
                "_def_lines": [def_start] if def_start else [],
                "usage_examples": [],
                "pdf_page": pdf_page,
                "book_page": book_page,
                "is_name_only": False,
                "ocr_flags": ocr_flags(hw),
            }
        elif current is not None:
            clean = strip_noise(line)
            if clean:
                current["_def_lines"].append(clean)

# Flush last entry
if current:
    entries.append(finalise(current))

# ── Write output ─────────────────────────────────────────────────────────────

OUTPUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

total   = len(entries)
flagged = sum(1 for e in entries if e["ocr_flags"])
named   = sum(1 for e in entries if e["is_name_only"])
no_def  = sum(1 for e in entries if not e["definition"])

print(f"Entries written : {total}")
print(f"Flagged (OCR)   : {flagged}")
print(f"Name-only       : {named}")
print(f"No definition   : {no_def}")
print(f"Output          : {OUTPUT}")
