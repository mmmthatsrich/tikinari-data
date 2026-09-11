"""Split a Williams raw definition into per-sense dicts with per-sense POS.

Pure string -> list[dict]; no DB. Williams packs all senses into one definition,
numbered inline ("1. n. ... 2. ... 3. v.i. ...") with POS stated once and carried
over until it changes. See docs/superpowers/specs/2026-06-27-williams-multisense-pos-design.md
"""
import re

# Closed Williams POS-abbrev set. pass./fig. are register, NOT POS -> excluded.
POS_ABBREVS = [
    "def.art.", "v.t.", "v.i.", "l.n.", "ad.", "pt.", "pl.", "pos.", "int.",
    "num.", "pron.", "def.", "indef.", "prefix.", "conj.", "prep.", "interj.",
    "n.", "a.", "v.",
]
_POS_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in sorted(POS_ABBREVS, key=len, reverse=True)) + r")\s"
)
# The separator before a sense number is matched but NOT consumed: a ')' there
# closes the previous sense's citation, and eating it truncated 148 senses
# ('...(Ngā Mōteatea 124'). Lookbehind keeps the character with the text it
# belongs to.
_MARKER_RE = re.compile(r"(?:^|(?<=[.)])\s)(\d+)\.\s")
_LEAD_MARKER_RE = re.compile(r"^\s*\d+\.\s")


def _sense_spans(text):
    """(content_start, marker_start) list for the longest strict 1,2,3,… run; [] if <2."""
    spans, expected = [], 1
    for m in _MARKER_RE.finditer(text):
        if int(m.group(1)) == expected:
            spans.append((m.end(), m.start()))
            expected += 1
    return spans if len(spans) >= 2 else []


def _split_pos(chunk):
    """Return (pos|None, gloss) by peeling an optional leading POS abbrev."""
    m = _POS_RE.match(chunk)
    if m:
        return m.group(1), chunk[m.end():].strip()
    return None, chunk.strip()


def split_senses(definition):
    if not definition:
        return []
    text = definition.strip()
    spans = _sense_spans(text)

    if not spans:
        chunk = _LEAD_MARKER_RE.sub("", text, count=1).strip()
        pos, gloss = _split_pos(chunk)
        return [{"sense_number": 1, "part_of_speech": pos,
                 "gloss_en": gloss, "definition_raw": chunk}]

    # content runs from each sense's content_start to the next marker_start
    content_starts = [cs for cs, _ in spans]
    next_marker = [ms for _, ms in spans][1:] + [len(text)]
    out, prev_pos = [], None
    for i, cs in enumerate(content_starts):
        chunk = text[cs:next_marker[i]].strip()
        pos, gloss = _split_pos(chunk)
        if pos is None:
            pos = prev_pos           # carry-over
        prev_pos = pos
        out.append({"sense_number": i + 1, "part_of_speech": pos,
                    "gloss_en": gloss, "definition_raw": chunk})
    return out
