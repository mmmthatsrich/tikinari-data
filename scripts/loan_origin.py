"""Read a borrowing's origin where a source states it. Pure strings; no DB.

See docs/LOAN_ORIGIN_DESIGN.md. The corpus records that 22,832 entries are
borrowed and almost never from what. Two sources say more, and they are the
only places in 153,543 entries where a borrowing's origin is stated as data:

    paekupu   entry.loan_marker  'he kupu mino (reo Wīwī)'
    papakupu  sense.gloss_en     'Eng. shirt'

Both are parsed exactly. Nothing is inferred: a bare 'He kupu mino.' yields a
row that says borrowed and nothing else, which is what the source said.
"""
import re

# 'he kupu mino' with optional trailing punctuation and an optional bracket.
_MINO = re.compile(r"^\s*he\s+kupu\s+mino\b", re.IGNORECASE)
_BRACKET = re.compile(r"\(([^()]+)\)")
# Paekupu names a language as 'reo X'; anything else in the bracket is the word
# the term was borrowed from ('he kupu mino (hammer)').
_REO = re.compile(r"^\s*reo\s+\S", re.IGNORECASE)
# Te Aka states borrowing without ever naming a language.
_TE_AKA_MARKER = re.compile(r"loan\s*word", re.IGNORECASE)
# Scrape residue seen on two paekupu rows: 'He kupu mino.&nbsp'.
_HTML_RESIDUE = re.compile(r"&[a-z]+;?", re.IGNORECASE)

_ENG = re.compile(r"^\s*Eng\.\s*(.+)$")
# A bare part-of-speech token can sit between the marker and the word:
# 'Eng. n cheque'.
_LEADING_POS = re.compile(r"^(?:n|v|a|adj|adv|vt|vi)\.?\s+(?=\S)", re.IGNORECASE)


def parse_loan_marker(marker):
    """{'source_lang', 'source_word', 'attested'} for a loan marker, else None.

    `attested` is always True here — the caller only reaches this with a value
    the source wrote — and is kept so the field is explicit in the row rather
    than implied by the table.
    """
    text = _HTML_RESIDUE.sub("", (marker or "")).strip()
    if not text:
        return None
    if not (_MINO.match(text) or _TE_AKA_MARKER.search(text)):
        return None

    lang = word = None
    m = _BRACKET.search(text)
    if m:
        inner = m.group(1).strip()
        if _REO.match(inner):
            lang = inner
        elif inner:
            word = inner
    return {"source_lang": lang, "source_word": word, "attested": True}


def parse_papakupu_loan_gloss(gloss):
    """{'source_lang', 'source_word', 'gloss'} for an 'Eng. …' gloss, else None.

    The marker must lead: 'score, cf. Eng.' mentions English without claiming
    the headword came from it.
    """
    m = _ENG.match(gloss or "")
    if not m:
        return None
    rest = _LEADING_POS.sub("", m.group(1).strip()).strip()
    if not rest:
        return None
    return {"source_lang": "English", "source_word": rest, "gloss": rest}
