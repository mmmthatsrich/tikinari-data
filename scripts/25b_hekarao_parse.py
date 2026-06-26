"""
Parse He Karao OCR TSV files into JSON dictionary entries.

Reads sources/hekarao/ocr/page_NN.tsv (pages 15-27, 50-58).
Writes sources/hekarao/parsed/hekarao_entries.json.

Each row in the two-column layout is one entry:
  left column  → headword (Māori)
  right column → definition (English gloss)

Column boundary detected dynamically per row: the first inter-word gap
greater than MIN_COL_GAP pixels marks the split between Māori and English.

Page 15 is a transition page — the syllable index occupies the top half
and the vocabulary starts from y > img_height * PAGE15_VOCAB_FRAC.

Each entry:
  headword, definition, pdf_page, section, ocr_conf

Usage:
  py scripts/25b_hekarao_parse.py
"""

import sys, re, json
import csv as _csv
from io import StringIO
from pathlib import Path
from statistics import mean

sys.stdout.reconfigure(encoding="utf-8")

OCR_DIR = Path(__file__).parent.parent / "sources" / "hekarao" / "ocr"
OUTPUT  = Path(__file__).parent.parent / "sources" / "hekarao" / "parsed" / "hekarao_entries.json"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# Pages 15-27 = vocabulary_1; pages 50-58 = vocabulary_2
SECTION_MAP = {p: "vocabulary_1" for p in range(15, 28)}
SECTION_MAP.update({p: "vocabulary_2" for p in range(50, 59)})

# On page 15 the top half is a syllable index; vocabulary starts below this fraction
PAGE15_VOCAB_FRAC = 0.50

# Minimum pixel gap between consecutive words to signal a column boundary
MIN_COL_GAP = 150

# Minimum confidence to include a word token (excludes explicit conf=0 noise)
MIN_CONF = 1.0

# Minimum number of alphabetic chars in headword to consider it valid
MIN_HW_ALPHA = 2

# Row grouping: words within this many pixels vertically are the same row
ROW_BIN = 25


def read_tsv(path: Path) -> tuple[int, int, int, list[dict]]:
    """
    Return (pdf_page, img_width, img_height, words).
    words: list of dicts with keys left, top, width, conf, text.
    Only level-5 (word) rows with conf >= MIN_CONF are returned.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Header comment: # PDF_PAGE=N IMG_WIDTH=W IMG_HEIGHT=H
    pdf_page = img_width = img_height = 0
    if lines and lines[0].startswith("#"):
        hdr = re.search(r"PDF_PAGE=(\d+)\s+IMG_WIDTH=(\d+)\s+IMG_HEIGHT=(\d+)", lines[0])
        if hdr:
            pdf_page  = int(hdr.group(1))
            img_width = int(hdr.group(2))
            img_height= int(hdr.group(3))
        data_lines = "\n".join(lines[1:])
    else:
        data_lines = "\n".join(lines)

    reader = _csv.DictReader(StringIO(data_lines), delimiter="\t",
                            quoting=_csv.QUOTE_NONE, quotechar="\x00")
    words = []
    for row in reader:
        try:
            if int(row["level"]) != 5:
                continue
            conf = float(row["conf"])
            if conf < MIN_CONF:
                continue
            words.append({
                "left":  int(row["left"]),
                "top":   int(row["top"]),
                "width": int(row["width"]),
                "conf":  conf,
                "text":  row["text"].strip(),
            })
        except (ValueError, KeyError):
            continue
    return pdf_page, img_width, img_height, words


def group_into_rows(words: list[dict]) -> list[list[dict]]:
    """Group words into horizontal rows by binning on top-position."""
    if not words:
        return []
    bins: dict[int, list[dict]] = {}
    for w in words:
        bin_key = (w["top"] // ROW_BIN) * ROW_BIN
        bins.setdefault(bin_key, []).append(w)
    return [sorted(row, key=lambda w: w["left"]) for row in sorted(bins.values(), key=lambda r: r[0]["top"])]


def split_row(row: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split a row into (left_col, right_col) at the first inter-word gap > MIN_COL_GAP.
    Returns ([], []) if no clear column gap is found.
    """
    if len(row) < 2:
        return row, []
    for i in range(len(row) - 1):
        gap = row[i + 1]["left"] - (row[i]["left"] + row[i]["width"])
        if gap >= MIN_COL_GAP:
            return row[:i + 1], row[i + 1:]
    return [], []  # no gap found — not a two-column row


def clean_headword(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words if w["text"])


def clean_gloss(words: list[dict]) -> str:
    # Join, then collapse whitespace and strip leading punctuation/noise
    text = " ".join(w["text"] for w in words if w["text"])
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r'^[^A-Za-z]+', "", text)
    return text


def is_valid_headword(hw: str) -> bool:
    alpha = re.sub(r"[^A-Za-zāēīōūĀĒĪŌŪéàáíóū]", "", hw)
    return len(alpha) >= MIN_HW_ALPHA


def headword_flags(hw: str) -> list[str]:
    flags = []
    if re.search(r"\d", hw):
        flags.append("headword_has_digits")
    if re.search(r"[^A-Za-zāēīōūĀĒĪŌŪéàáíóū '\-]", hw):
        flags.append("headword_has_punct")
    return flags


# ── Main pass ────────────────────────────────────────────────────────────────

entries: list[dict] = []

for tsv_path in sorted(OCR_DIR.glob("page_*.tsv")):
    fn_match = re.search(r"page_(\d+)\.tsv$", tsv_path.name)
    if not fn_match:
        continue
    fn_page = int(fn_match.group(1))
    section = SECTION_MAP.get(fn_page)
    if section is None:
        continue

    pdf_page, img_width, img_height, words = read_tsv(tsv_path)
    if pdf_page == 0:
        pdf_page = fn_page

    # Page 15: skip top half (syllable index)
    if fn_page == 15 and img_height > 0:
        cutoff = img_height * PAGE15_VOCAB_FRAC
        words = [w for w in words if w["top"] >= cutoff]

    rows = group_into_rows(words)

    for row in rows:
        left_col, right_col = split_row(row)
        if not left_col:
            continue

        hw = clean_headword(left_col)
        if not is_valid_headword(hw):
            continue

        gloss = clean_gloss(right_col) if right_col else None

        all_confs = [w["conf"] for w in left_col + right_col]
        ocr_conf = round(mean(all_confs), 1) if all_confs else 0.0

        flags = headword_flags(hw)

        entries.append({
            "headword":   hw,
            "definition": gloss,
            "pdf_page":   pdf_page,
            "section":    section,
            "ocr_conf":   ocr_conf,
            "ocr_flags":  flags,
        })

# ── Write output ─────────────────────────────────────────────────────────────

OUTPUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

total     = len(entries)
no_gloss  = sum(1 for e in entries if not e["definition"])
flagged   = sum(1 for e in entries if e["ocr_flags"])
sec1      = sum(1 for e in entries if e["section"] == "vocabulary_1")
sec2      = sum(1 for e in entries if e["section"] == "vocabulary_2")
low_conf  = sum(1 for e in entries if e["ocr_conf"] < 40)

print(f"Entries written  : {total}")
print(f"  vocabulary_1   : {sec1}  (pages 15-27)")
print(f"  vocabulary_2   : {sec2}  (pages 50-58)")
print(f"No gloss         : {no_gloss}")
print(f"Flagged (OCR)    : {flagged}")
print(f"Low confidence   : {low_conf}  (ocr_conf < 40)")
print(f"Output           : {OUTPUT}")
