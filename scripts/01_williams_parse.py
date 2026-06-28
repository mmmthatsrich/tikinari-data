#!/usr/bin/env python3
"""Parse Williams Dictionary HTML files into structured JSON entries."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from williams_xref import extract_xrefs

try:
    from lxml import html as lhtml
except ImportError:
    print("ERROR: lxml not installed. Run: py -m pip install lxml", file=sys.stderr)
    sys.exit(1)

RAW_DIR = Path(__file__).parent.parent / "sources" / "williams" / "raw"
PARSED_DIR = Path(__file__).parent.parent / "sources" / "williams" / "parsed"

SECTION_MAP = [
    ("section_A.html", "A"),
    ("section_E.html", "E"),
    ("section_H.html", "H"),
    ("section_I.html", "I"),
    ("section_K.html", "K"),
    ("section_M.html", "M"),
    ("section_N.html", "N"),
    ("section_Ng.html", "Ng"),
    ("section_O.html", "O"),
    ("section_P.html", "P"),
    ("section_R.html", "R"),
    ("section_T.html", "T"),
    ("section_U.html", "U"),
    ("section_W.html", "W"),
]

ROMAN_RE = re.compile(r"^\s*\(([ivxlcdm]+)\)", re.IGNORECASE)

POS_RE = re.compile(
    r"^[,\s]*"
    r"(v\.t\.i\.|v\.t\.|v\.i\.|v\."
    r"|n\."
    r"|a\."
    r"|ad\.|adv\."
    r"|conj\."
    r"|prep\."
    r"|int\."
    r"|pron\."
    r"|particle"
    r"|art\."
    r"|num\."
    r"|suf\."
    r"|pref\."
    r"|loc\."
    r")"
)


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def parse_section_div(div, source_section, page_number):
    """Parse one <div class="section"> into an entry dict, or None to skip."""
    # Must have p.hang as a direct child
    hang_p = None
    for child in div:
        if child.tag == "p" and child.get("class") == "hang":
            hang_p = child
            break
    if hang_p is None:
        return None

    # Headword = text of first span.foreign.bold[lang=mi] in the hang paragraph
    hw_span = None
    for elem in hang_p.iter("span"):
        if elem.get("class") == "foreign bold" and elem.get("lang") == "mi":
            hw_span = elem
            break
    if hw_span is None:
        return None

    headword = clean_text(hw_span.text_content())
    if not headword:
        return None

    # Sense number and POS live in the tail of the headword span
    tail = hw_span.tail or ""

    sense_number = ""
    roman_m = ROMAN_RE.match(tail)
    if roman_m:
        sense_number = roman_m.group(1).lower()
        tail = tail[roman_m.end():]

    pos_m = POS_RE.match(tail)
    part_of_speech = pos_m.group(1) if pos_m else ""

    # Usage examples = non-bold foreign mi spans. Cross-refs are NOT taken from
    # bold spans any more — that capture was ~73% noise (sub-headwords, example
    # fragments). Williams' real cross-ref notation is the '‖' marker, extracted
    # from the definition text below via williams_xref.extract_xrefs.
    usage_examples = []
    for elem in div.iter("span"):
        if elem.get("class") == "foreign" and elem.get("lang") == "mi":
            ex = clean_text(elem.text_content())
            if ex:
                usage_examples.append(ex)

    # Build definition from all direct-child <p> elements
    para_texts = []
    for child in div:
        if child.tag == "p":
            txt = clean_text(child.text_content())
            if txt:
                para_texts.append(txt)
    full_text = " ".join(para_texts)

    # Strip headword prefix that appears at the start of the first paragraph
    if full_text.startswith(headword):
        full_text = full_text[len(headword):].strip()
        # Strip sense marker
        roman_m2 = ROMAN_RE.match(full_text)
        if roman_m2:
            full_text = full_text[roman_m2.end():].strip()
        # Strip leading punctuation
        full_text = full_text.lstrip(",.() ").strip()
        # Strip POS if it's right at the start
        if part_of_speech and full_text.startswith(part_of_speech):
            full_text = full_text[len(part_of_speech):].strip()

    definition = clean_text(full_text)
    definition, cross_refs = extract_xrefs(definition)
    if not definition:
        # Pure pointer entry: the whole gloss was a ‖ cross-ref. Keep it with a
        # readable "Cf." gloss synthesised from the targets ('‖' = compare in
        # Williams); drop only if there is genuinely nothing left.
        targets = [r["target"] for r in cross_refs]
        if targets:
            definition = "Cf. " + ", ".join(targets) + "."
        else:
            return None

    return {
        "headword": headword,
        "sense_number": sense_number,
        "part_of_speech": part_of_speech,
        "definition": definition,
        "usage_examples": usage_examples,
        "cross_refs": cross_refs,
        "page_number": page_number,
        "source_section": source_section,
    }


def parse_file(filepath, source_section):
    """Parse one Williams HTML file and return a list of entry dicts."""
    with open(filepath, "rb") as f:
        content = f.read()

    tree = lhtml.fromstring(content)
    entries = []
    current_page = 1

    # Collect all section divs and page-break spans in document order.
    # lxml proxy objects must NOT be stored across iter() boundaries (id() reuse bug),
    # so we snapshot the element data we need while iterating.
    items = []  # list of ('pb', page_num) | ('entry', lxml_element)
    for elem in tree.iter():
        tag = elem.tag
        if not isinstance(tag, str):
            continue

        if tag == "span" and elem.get("class") == "pb":
            m = re.search(r"page\s+(\d+)", elem.text_content())
            if m:
                items.append(("pb", int(m.group(1))))

        elif tag == "div" and elem.get("class") == "section":
            has_direct_hang = any(
                c.tag == "p" and c.get("class") == "hang" for c in elem
            )
            if has_direct_hang:
                items.append(("entry", elem))

    # Process the collected items; parse_section_div is called after iter() completes
    # so there's no proxy-reuse risk.
    for kind, payload in items:
        if kind == "pb":
            current_page = payload
        else:
            entry = parse_section_div(payload, source_section, current_page)
            if entry:
                entries.append(entry)

    return entries


def main():
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    all_entries = []

    for filename, section_letter in SECTION_MAP:
        filepath = RAW_DIR / filename
        if not filepath.exists():
            print(f"  MISSING: {filename}", file=sys.stderr)
            continue
        entries = parse_file(filepath, section_letter)
        all_entries.extend(entries)
        print(f"  {section_letter:2s}: {len(entries):4d} entries")

    output_path = PARSED_DIR / "williams_entries.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    print(f"\nTotal: {len(all_entries)} entries -> {output_path}")
    return all_entries


if __name__ == "__main__":
    main()
