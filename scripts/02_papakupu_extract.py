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

# Sentence boundary: whitespace following a terminator.
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Māori orthography. A Māori word uses only these letters (vowels incl. macrons +
# consonants h k m n p r t w; g appears only in the digraph 'ng'). The presence of
# any English-only consonant marks a token as English — used to split the Māori half
# of an example off the English gloss/translation prose it is glued to.
_MAORI_CHARS = set("aāeēiīoōuūhkmnprtwg")
_ENGLISH_ONLY = set("bcdfjlqsvxyz")


def _is_maori_token(token: str) -> bool | None:
    """True if token is Māori, False if clearly English, None if neutral (digits/punct)."""
    letters = [c for c in token.lower() if c.isalpha()]
    if not letters:
        return None
    if any(c in _ENGLISH_ONLY for c in letters):
        return False
    return all(c in _MAORI_CHARS for c in letters)


def _maori_tail(text: str) -> str:
    """Return the maximal trailing run of Māori tokens.

    Papakupu's first example per entry is glued onto the English gloss with no
    separating period, so the Māori sentence cannot be found by position alone.
    Walking right-to-left and stopping at the first clearly-English token recovers
    it; neutral tokens (punctuation, digits) are kept and walked through.
    """
    kept = []
    for token in reversed(text.split()):
        if _is_maori_token(token) is False:
            break
        kept.append(token)
    return " ".join(reversed(kept)).strip()


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


def extract_examples(definition: str) -> list[dict]:
    """Extract bilingual examples as {text_mi, text_en, source_abbrev} dicts.

    Papakupu examples follow `<Māori sentence>. <English translation>. [SRC]`.
    Splitting on the [SRC] refs yields one segment per example; within a segment
    the last sentence is the English translation and the sentence before it the
    Māori original. The first example's segment also carries the English gloss
    prose, so the Māori half is recovered with `_maori_tail` rather than by
    sentence position alone. Collapses newlines first so multi-line sentences are
    captured whole.
    """
    flat = " ".join(line.strip() for line in definition.split("\n") if line.strip())
    examples = []
    last_end = 0
    for m in SRC_REF_RE.finditer(flat):
        segment = flat[last_end:m.start()].strip()
        last_end = m.end()
        source_abbrev = m.group(0).strip("[]")
        if not segment:
            continue
        parts = [p.strip() for p in SENT_SPLIT_RE.split(segment) if re.search(r"\w", p)]
        if not parts:
            continue
        text_en = parts[-1]
        text_mi = _maori_tail(parts[-2]) if len(parts) >= 2 else ""
        # A lone sentence that is itself Māori is a Māori-only example, not a gloss.
        if not text_mi and len(parts) == 1 and _maori_tail(text_en):
            text_mi, text_en = _maori_tail(text_en), None
        if not (text_mi or text_en):
            continue
        if len((text_mi or "") + (text_en or "")) <= 15:
            continue
        examples.append({
            "text_mi": text_mi or None,
            "text_en": text_en or None,
            "source_abbrev": source_abbrev,
        })
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
