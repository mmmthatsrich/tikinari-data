"""Route Paekupu's `alternative_words` to the right relation.

Pure string -> dict; no DB.

All 11,875 of these were written to `form` as `alt_spelling` — about 90% of
every form row in the corpus — and none of them is an alternative spelling. The
field holds two different things:

    "ngawhere - break up, crumble"   a component of the coined term, and what
                                     it means. The same shape as Te Matatiki's
                                     bracket derivations, which are already
                                     cross_ref relations carrying the gloss.

    "aroaro", "papamua"              other terms for the same concept.
                                     `ahanoa` and `tūhanga` list each other and
                                     are both glossed 'object (computing)'.

The separator is ' - ' with spaces on both sides, never a bare hyphen: `ā-tau`
and `ā-kākā` are single words and splitting them would invent components that
do not exist.

A trailing bracket on the component — 'hāpara (hāparapara)', 'Poa (kupu mino)' —
is a variant or a loanword marker rather than part of the word, so the relation
targets the bare form while the note keeps the value exactly as the source wrote
it. Nothing is discarded.
"""
import re

_SEP = " - "
_QUALIFIER = re.compile(r"\s*\([^)]*\)\s*$")
# "he kupu mino" is "it is a loan word" — a marker, not another term. 411 of
# them, sometimes naming the source language: (reo Hapanihi), (reo Wiwi),
# (reo Itariana), (reo Hiperu). They belong in entry.loan_marker alongside Te
# Aka's own marker, which is also what makes them visible to the etymology
# filter: a borrowed word cannot descend from Proto-Polynesian.
_LOAN_NOTE = re.compile(r"^\s*he\s+kupu\s+mino", re.I)


def parse_alternative(value: str | None) -> dict | None:
    """{'target', 'rel_type', 'note'} for one alternative_words item, or None."""
    if not value or not value.strip():
        return None
    text = " ".join(value.split())
    if text.startswith("-"):
        # A gloss with no component in front of it names nothing to point at.
        return None

    if _LOAN_NOTE.match(text):
        return {"target": None, "rel_type": "loan_marker", "note": text}

    if _SEP in text:
        word = text.split(_SEP, 1)[0].strip()
        target = _QUALIFIER.sub("", word).strip()
        if not target:
            return None
        return {"target": target, "rel_type": "cross_ref", "note": text}

    return {"target": text, "rel_type": "synonym", "note": None}
