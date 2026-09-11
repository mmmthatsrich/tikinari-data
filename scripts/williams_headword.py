"""Route a Williams headword-attached parenthetical to its proper field.

Pure string -> dict; no DB, no HTML.

Williams qualifies some headwords in brackets:

    Wahine (pl. wāhine), n. ...
    Ahiahitanga (poetical), n. ...
    Tūāahu (less correctly tūāhu), n. ...

_build_entry stripped the headword and then ran `lstrip(",.() ")`, which removed
the OPENING bracket and stranded the closing one at the head of the definition —
'less correctly tūāhu), n. A sacred place...'. 44 senses read that way.

The source carries 2,427 of these brackets, but 2,402 are homograph numerals —
(i), (ii), (iii) — which ROMAN_RE already lifts into sense_number. Only the 25
non-numeral ones were affected, and they are worth more than a tidy-up: eight
are plural forms ('pl. wāhine'), which is a lexical fact the `form` table exists
to hold and which was previously buried in prose.
"""
import re

# 'pl. wāhine', 'pl. sometimes kikino'
_PLURAL = re.compile(r"^pl\.\s+(?:sometimes\s+)?(.+)$", re.I)
# Bare registers Williams uses next to a headword.
_REGISTERS = {"poetical"}


def parse_headword_note(raw: str | None) -> dict:
    """{'plural': [...], 'register': str|None, 'note': str|None}.

    A hedged plural ('pl. sometimes kikino') yields the form AND keeps the full
    text as a note, because the hedge is part of what the source asserts.
    """
    empty = {"plural": [], "register": None, "note": None}
    if not raw:
        return empty
    text = re.sub(r"\s+", " ", raw).strip().strip(",;")
    if not text:
        return empty

    if text.casefold() in _REGISTERS:
        return {"plural": [], "register": text.casefold(), "note": None}

    if (m := _PLURAL.match(text)):
        forms = [f.strip() for f in m.group(1).split(",") if f.strip()]
        hedged = "sometimes" in text.casefold()
        return {"plural": forms, "register": None, "note": text if hedged else None}

    return {"plural": [], "register": None, "note": text}
