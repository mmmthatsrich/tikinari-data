"""
Extract Papakupu o Tai Tokerau entries from PDF.
Produces sources/papakupu/parsed/papakupu_entries.json

Licence note: PDF marked "For Private Use Only". Local use only; do not distribute.
"""

import fitz
import re
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PDF_PATH = ROOT / "w2B-Papakupu-o-Tai-Tokerau.pdf"
OUT_DIR = ROOT / "sources" / "papakupu" / "parsed"
OUT_PATH = OUT_DIR / "papakupu_entries.json"

# Doc indices (0-based) for dictionary entry pages
FIRST_PAGE = 27   # "Page27" — first A entries
LAST_PAGE = 610   # "Page610" — last WH entries

# Page header pattern to strip
HEADER_RE = re.compile(
    r"[ \t]*\n"
    r"Te Papakupu o Te Taitokerau[^\n]*\n"
    r"Not to be copied[^\n]*\n"
    r"[ \t]*\n"
    r"Page\d+[ \t]*\n",
    re.MULTILINE,
)

# Headword chars: Māori letters (with macrons), space, comma, tilde, period, hyphen
# This rejects lines like 'class"; see...When a [2]' that have quotes/semicolons
_HW_CHARS = r"[A-Za-zĀāĒēĪīŌōŪū]"
_HW_BODY = r"[A-Za-zĀāĒēĪīŌōŪū\s,~.'`‘’-]"

# Entry start: headword (Māori chars only, max 60) then [N]
# Applied to individual lines only when preceded by a blank line (see main loop)
ENTRY_START_RE = re.compile(
    rf"^({_HW_CHARS}{_HW_BODY}{{0,59}}?)\s+\[(\d+)\][ \t]*",
    re.MULTILINE,
)

# Fields within entry body
VARIANT_RE = re.compile(r"<([^>]+)>")
SOURCE_RE = re.compile(r"\{([^}]+)\}")
LOAN_RE = re.compile(r"\[(Eng\.?|English)\]")
# POS: capital then lowercase (not a source ref like [NKU] or [TWK/MHR])
POS_RE = re.compile(r"\[([A-Z][a-z][^\]]*)\]")
SEE_ALSO_RE = re.compile(r"\b(?:See also|See|Cf\.?)[\s:]+([^\n.()]+)")

# Source reference codes: [TTU], [TWK/MHR], [NGH3], [K1:31:45], etc.
SRC_REF_RE = re.compile(r"\[[A-Z][A-Z0-9/:.-]+\]")

# Usage example: sentence text + [SOURCE_REF] where ref is uppercase+digits/slash/colon
EXAMPLE_RE = re.compile(r"([^.!?][^.!?]*[.!?])\s*(\[[A-Z][A-Z0-9/:.-]+\])")


def strip_header(text: str) -> str:
    return HEADER_RE.sub("\n", text)


def clean_headword(raw: str) -> str:
    """Strip passive/related-form suffix notations: ', ...tia', '~tia', '...a'."""
    cleaned = re.sub(r",?\s*[~.]?\.\.\.\w+", "", raw)
    cleaned = re.sub(r",?\s*~\w+", "", cleaned)
    return cleaned.strip().strip(",").strip()


def extract_see_also(definition: str) -> list[str]:
    """Extract cross-reference words from See/Cf. markers or trailing word list."""
    m = SEE_ALSO_RE.search(definition)
    if m:
        raw = m.group(1)
        items = [w.strip().rstrip(".)").strip() for w in raw.split(",") if w.strip()]
        return [item for item in items if item]

    # Trailing cross-refs: words that appear AFTER the last [SOURCE_REF] code.
    # This prevents definition-ending prose from being treated as cross-refs.
    src_refs = list(SRC_REF_RE.finditer(definition))
    if not src_refs:
        return []
    after_last = definition[src_refs[-1].end():].strip()
    if (after_last
            and "." not in after_last
            and not re.search(r"[\[\"()]", after_last)
            and len(after_last) <= 50):
        words = [w.strip() for w in re.split(r"[,\s]+", after_last)
                 if w.strip() and len(w.strip()) > 1]
        if words:
            return words
    return []


def extract_examples(definition: str) -> list[str]:
    """Extract Māori example sentences with their [SOURCE] refs.
    Collapses newlines first so multi-line sentences are captured whole.
    """
    flat = " ".join(line.strip() for line in definition.split("\n") if line.strip())
    examples = []
    for m in EXAMPLE_RE.finditer(flat):
        ex = m.group(1).strip() + " " + m.group(2)
        if len(ex) > 15:
            examples.append(ex)
    return examples


def parse_entry(block: str, pdf_page: int) -> dict | None:
    """Parse a single entry block. Returns None if the block is not a valid entry."""
    m = ENTRY_START_RE.match(block)
    if not m:
        return None

    headword = clean_headword(m.group(1))
    if not headword:
        return None
    sense_number = m.group(2)
    # [041126] and similar are source-reference codes (all-digit), not sense numbers
    if int(sense_number) > 20:
        return None
    body = block[m.end():]

    # Search within a window for structured fields; order varies between entries
    window = body[:400]

    vm = VARIANT_RE.search(window)
    variant_forms = [v.strip() for v in vm.group(1).split(",") if v.strip()] if vm else []

    scm = SOURCE_RE.search(window)
    source_code = scm.group(1).strip() if scm else None

    lm = LOAN_RE.search(window)
    loan_marker = lm.group(1) if lm else None

    posm = POS_RE.search(window)
    part_of_speech = posm.group(1).strip() if posm else None

    definition = body.strip()
    see_also = extract_see_also(definition)
    usage_examples = extract_examples(definition)

    return {
        "headword": headword,
        "sense_number": sense_number,
        "variant_forms": variant_forms,
        "source_code": source_code,
        "loan_marker": loan_marker,
        "part_of_speech": part_of_speech,
        "definition": definition,
        "usage_examples": usage_examples,
        "see_also": see_also,
        "pdf_page": pdf_page,
    }


def main() -> None:
    if not PDF_PATH.exists():
        sys.exit(f"PDF not found: {PDF_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(PDF_PATH))

    # Build (line_text, page_num) list across all entry pages
    all_lines: list[tuple[str, int]] = []
    for pg in range(FIRST_PAGE, LAST_PAGE + 1):
        text = strip_header(doc[pg].get_text())
        for line in text.split("\n"):
            all_lines.append((line, pg))

    # Group lines into entry blocks.
    # Rule: a new entry starts only when:
    #   (a) the previous non-whitespace-only line was empty (blank line precedes it), AND
    #   (b) the current line matches ENTRY_START_RE
    # This prevents mid-entry text like 'class"; see... When a [2]' from being
    # treated as an entry start, since they don't follow a blank line.
    entries: list[dict] = []
    current_lines: list[str] = []
    current_page: int = FIRST_PAGE
    prev_blank = True  # treat start-of-stream as "after blank"

    def flush_entry() -> None:
        if not current_lines:
            return
        block = "\n".join(current_lines)
        entry = parse_entry(block.strip(), current_page)
        if entry:
            entries.append(entry)

    for line, pg in all_lines:
        stripped = line.strip()
        is_blank = not stripped

        if not is_blank and prev_blank and ENTRY_START_RE.match(stripped):
            # Confirmed new entry: follows a blank line and matches pattern
            flush_entry()
            current_lines = [stripped]
            current_page = pg
        elif current_lines:
            # Continuation (or blank line within entry)
            current_lines.append(line)
        # else: pre-entry content (TOC, intro) — discard

        prev_blank = is_blank

    flush_entry()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(entries)} entries -> {OUT_PATH}")


if __name__ == "__main__":
    main()
