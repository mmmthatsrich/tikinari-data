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
# belongs to. '?' and '!' are in the class because Māori example sentences end
# in them constantly ('Te hia ? which in order? 2. An indefinite number'), and
# excluding them hid the marker that follows.
_MARKER_RE = re.compile(r"(?:^|(?<=[.?!)])\s)(\d+)\.\s")
_LEAD_MARKER_RE = re.compile(r"^\s*\d+\.\s")


def _sense_spans(text, start=1):
    """(content_start, marker_start) list for the strict start,start+1,… run."""
    spans, expected = [], start
    for m in _MARKER_RE.finditer(text):
        if int(m.group(1)) == expected:
            spans.append((m.end(), m.start()))
            expected += 1
    return spans


def _numbered_spans(text):
    """(spans, implicit_first) for the entry's sense run.

    Williams numbers the first sense only when it needs to; 136 entries leave
    it bare and open explicit numbering at 2 ('Caterpillar, grub. 2. A
    fresh-water fish.'). Insisting the run begin at 1 meant it never began and
    the entry collapsed to a single sense holding all of them. Falling back to
    a run from 2 recovers those, with the bare head becoming sense 1.
    """
    spans = _sense_spans(text, 1)
    if len(spans) >= 2:
        return spans, False
    spans = _sense_spans(text, 2)
    # marker_start > 0 keeps a leading '2.' — with nothing before it to be
    # sense 1 — from inventing an empty sense.
    if spans and spans[0][1] > 0:
        return spans, True
    return [], False


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
    spans, implicit_first = _numbered_spans(text)
    if implicit_first:
        spans = [(0, 0)] + spans

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
