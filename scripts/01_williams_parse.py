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
    r"|part\."
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


# A sub-headword is a lowercase Māori token (optionally a comma-separated
# variant list) printed bold at the very start of a paragraph, delimited by a
# POS abbreviation ("piriahi, a. ...") or a numbered-sense run
# ("whakapiri. 1. v.t. ...").
_SUB_TOKEN = r"[a-zāēīōū][a-zāēīōū\-]*"
SUBHEAD_RE = re.compile(rf"^{_SUB_TOKEN}(?:, {_SUB_TOKEN})*$")
# Typesetting slip in ~14 places: the POS abbrev is bolded together with the
# sub-headword, e.g. '<b>whakahenumi, v.t</b>.' — capture the headword part.
SUBHEAD_POS_RE = re.compile(
    rf"^({_SUB_TOKEN}(?:, {_SUB_TOKEN})*), "
    r"(?:v\.t\.i|v\.t|v\.i|v|n|a|adv|ad|part|conj|prep|int|pron|num|suf|pref|loc)\.?$"
)
_POS_ALT = (r"(?:v\.t\.i|v\.t|v\.i|v|n|a|adv|ad|part|conj|prep|int|pron|num"
            r"|suf|pref|loc)")
# Bucket C: sub-head set as plain paragraph text — '<p>rainga, n. Undulation.'
PLAIN_SUBHEAD_RE = re.compile(
    rf"^({_SUB_TOKEN}(?:, {_SUB_TOKEN})*), ({_POS_ALT}\.) ")
# Bucket D: POS and the first sense number both inside the bold —
# '<b>māwhitiwhiti, n. 1</b>.'
SUBHEAD_POS_NUM_RE = re.compile(
    rf"^({_SUB_TOKEN}(?:, {_SUB_TOKEN})*), {_POS_ALT}\.? 1$")


def _headword_span(hang_p):
    """First span.foreign.bold[lang=mi] in a hang paragraph, or None."""
    for elem in hang_p.iter("span"):
        if elem.get("class") == "foreign bold" and elem.get("lang") == "mi":
            return elem
    return None


def _sub_headword(p):
    """Return (headword, bold_elem) if this paragraph opens a sub-entry, else None."""
    if clean_text(p.text or ""):
        return None                       # e.g. '‖ <b>xref</b>.' paragraphs
    b = next(iter(p), None)
    if b is None:
        return None
    # Sub-headwords are usually <b>, but a handful are set like main headwords:
    # <span class="foreign bold" lang="mi">ahatanga</span>, n. ...
    if b.tag != "b" and not (b.tag == "span" and b.get("class") == "foreign bold"
                             and b.get("lang") == "mi"):
        return None
    word = clean_text(b.text_content())
    # POS-in-bold first: '<b>whawhango, a</b>.' must read as headword+POS, not
    # as a variant list ('a'/'n' alone are valid-looking tokens).
    pm = SUBHEAD_POS_RE.match(word)
    if pm:
        return (pm.group(1), b)
    pm = SUBHEAD_POS_NUM_RE.match(word)
    if pm:
        return (pm.group(1), b)
    if not SUBHEAD_RE.match(word):
        return None                       # numbered senses, phrases, capitals
    tail = (b.tail or "").lstrip()
    if tail.startswith(","):
        return (word, b) if POS_RE.match(tail) else None
    if tail.startswith("."):
        rest = tail[1:].lstrip()
        if rest:
            return (word, b) if POS_RE.match(rest) else None
        nxt = b.getnext()
        if nxt is not None and nxt.tag == "b" and clean_text(nxt.text_content()) == "1":
            return (word, b)
    return None


def _build_entry(headword, head_tail, para_texts, mi_examples, source_section,
                 page_number, kind, parent_headword):
    """Build one entry dict from pre-extracted strings."""
    tail = head_tail or ""

    sense_number = ""
    roman_m = ROMAN_RE.match(tail)
    if roman_m:
        sense_number = roman_m.group(1).lower()
        tail = tail[roman_m.end():]

    pos_m = POS_RE.match(tail)
    part_of_speech = pos_m.group(1) if pos_m else ""

    usage_examples = list(mi_examples)
    full_text = " ".join(t for t in para_texts if t)

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
        "kind": kind,
        "parent_headword": parent_headword,
    }


def _group_payload(g):
    """Convert an element-based group to _build_entry's string inputs."""
    elem = g["elem"]
    head_tail = elem.tail or ""
    para_texts, mi_examples = [], []
    for p in g["paras"]:
        txt = clean_text(p.text_content())
        if txt:
            para_texts.append(txt)
        for sp in p.iter("span"):
            if sp.get("class") == "foreign" and sp.get("lang") == "mi":
                ex = clean_text(sp.text_content())
                if ex:
                    mi_examples.append(ex)
    return g["headword"], head_tail, para_texts, mi_examples


def parse_section_div(div, source_section, page_number):
    """Parse one <div class="section"> into a list of entry dicts.

    A printed section runs several entries together: the first p.hang is the
    main headword ("kind": "main" — its position defines the stable
    williams_entries.id), later p.hang paragraphs are further full headwords
    ("kind": "hang", e.g. Pirikahu inside the Pirihonga div), and bold
    lowercase paragraph-initial words with a POS/numbered-sense delimiter are
    derivative sub-headwords ("kind": "sub", e.g. piriahi/whakapiri under
    Piri). Every group keeps only its own paragraphs, so the parent's last
    sense no longer swallows the sub-entries.
    """
    groups = []          # {"kind","headword","elem","paras","parent"}
    current = None
    main_hw = None
    last_hang_hw = None

    for child in div:
        if child.tag != "p":
            continue
        if child.get("class") == "hang":
            hw_span = _headword_span(child)
            hw = clean_text(hw_span.text_content()) if hw_span is not None else ""
            if hw:
                kind = "main" if main_hw is None else "hang"
                if main_hw is None:
                    main_hw = hw
                last_hang_hw = hw
                current = {"kind": kind, "headword": hw, "elem": hw_span,
                           "paras": [child],
                           "parent": None if kind == "main" else main_hw}
                groups.append(current)
                continue
            if main_hw is None:
                # first hang has no headword span: unparseable div — skip it
                # entirely, exactly as the pre-split parser did (id parity).
                return []
        elif main_hw is not None:
            sub = _sub_headword(child)
            if sub is not None:
                word, b = sub
                current = {"kind": "sub", "headword": word, "elem": b,
                           "paras": [child], "parent": last_hang_hw}
                groups.append(current)
                continue
        if current is not None:
            current["paras"].append(child)

    if not groups or groups[0]["kind"] != "main":
        return []

    entries = []
    for g in groups:
        hw, head_tail, para_texts, mi_examples = _group_payload(g)
        e = _build_entry(hw, head_tail, para_texts, mi_examples, source_section,
                         page_number, g["kind"], g["parent"])
        if e:
            entries.append(e)

    # Id parity: pre-split, a main whose own text was empty still produced an
    # entry (the glued group text made it non-empty). Keep its positional slot
    # with a synthesized pointer gloss to the recovered headwords.
    if len(groups) > 1 and (not entries or entries[0]["kind"] != "main"):
        others = [g["headword"] for g in groups[1:]]
        g0 = groups[0]
        entries.insert(0, {
            "headword": g0["headword"],
            "sense_number": "",
            "part_of_speech": "",
            "definition": "See " + ", ".join(others) + ".",
            "usage_examples": [],
            "cross_refs": [],
            "page_number": page_number,
            "source_section": source_section,
            "kind": "main",
            "parent_headword": None,
        })
    return entries


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
            entries.extend(parse_section_div(payload, source_section, current_page))

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
