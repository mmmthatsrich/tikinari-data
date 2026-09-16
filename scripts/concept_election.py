"""Elect a concept's canonical form from its witnesses. Pure; no DB.

The elected value is ALWAYS a string some member actually wrote. Never
composed. That is what lets the corpus state a canonical form while keeping
the rubric's first rule — never invent lexicographic content.
"""

import re

_MACRON_VOWELS = "āēīōū"

# D18's counts: te_aka can supply 1,943 of the 2,297 contested spellings,
# then hepatakakupu (1,530) and ngata (1,075).
HEADWORD_PRECEDENCE = (
    "te_aka", "hepatakakupu", "paekupu", "papakupu", "taikupu",
    "te_matatiki", "kimikupu_hou", "ngata", "temarareo", "williams",
    "tregear_exceptions",
)

# Ngata is LAST on purpose, and excluded entirely below: its gloss is the
# English lemma the word was listed under, not a definition. 'huripari', a
# hurricane, is glossed 'Wind' because it sits in a list of fifteen winds.
GLOSS_EN_PRECEDENCE = (
    "te_aka", "williams", "papakupu", "paekupu", "te_matatiki",
    "taikupu", "kimikupu_hou", "tregear_exceptions", "ngata",
)

_NO_GLOSS_EN = frozenset({"ngata"})

GLOSS_MI_PRECEDENCE = ("hepatakakupu", "paekupu", "te_aka")


def _has_macron(headword):
    return any(ch in _MACRON_VOWELS for ch in (headword or "").lower())


def _rank(source_id, order):
    return order.index(source_id) if source_id in order else len(order)


def elect_headword(members, derived_long):
    """(value, member_key, reason) — the canonical spelling, or (None,)*3.

    `derived_long` is True when the `derivation` table says this word is formed
    on a base whose vowel is long, which settles the macron outright.
    """
    if not members:
        return (None, None, None)

    macronised = [m for m in members if _has_macron(m["headword"])]

    if derived_long and macronised:
        best = min(macronised, key=lambda m: _rank(m["source_id"],
                                                   HEADWORD_PRECEDENCE))
        return (best["headword"], best["member_key"],
                "derivation: the base carries a long vowel")

    pool = macronised or members
    reason = ("a source marking vowel length makes a claim; one omitting it "
              "may simply not mark it") if macronised else \
             "no member marks vowel length"
    best = min(pool, key=lambda m: _rank(m["source_id"], HEADWORD_PRECEDENCE))
    return (best["headword"], best["member_key"], reason)


# A gloss that is nothing but a pointer at another headword: Williams writes
# 'Variant of wahine.', 'Cf. akakaikū.', '= kaitoa.' as a whole gloss. The
# target is exactly ONE word — that is what separates a pointer from prose
# that merely opens the same way ('A form of net used at the mouths of
# rivers.'), and from a pointer with a real gloss after it ('= pehea. How.'),
# neither of which is demoted.
_XREF_GLOSS = re.compile(
    r"^\s*(?:cf\.|see|=|same as|a form of|var\.|variant of)\s+"
    r"[\wāēīōūĀĒĪŌŪ'\-]+\s*[.,;]?\s*$", re.I)


def _is_cross_reference(gloss):
    return bool(_XREF_GLOSS.match(gloss or ""))


def elect_gloss(members, lang):
    """(value, member_key) for 'en' or 'mi', or (None, None).

    A bare cross-reference loses to any real gloss, whatever its source's
    precedence. Measured before this rule existed, 778 concepts reached the
    app with one elected as their meaning, so a reader looking up Ahine was
    told it means 'Variant of wahine.' It is demoted rather than banned: when
    nothing else is on offer the pointer is still worth showing, because it
    tells the reader where to look.
    """
    if lang == "en":
        order, field = GLOSS_EN_PRECEDENCE, "gloss_en"
        pool = [m for m in members if m["source_id"] not in _NO_GLOSS_EN]
    else:
        order, field = GLOSS_MI_PRECEDENCE, "gloss_mi"
        pool = list(members)

    pool = [m for m in pool if (m.get(field) or "").strip()]
    if not pool:
        return (None, None)
    if field == "gloss_en":
        real = [m for m in pool if not _is_cross_reference(m[field])]
        pool = real or pool          # fall back when pointers are all we have
    best = min(pool, key=lambda m: _rank(m["source_id"], order))
    return (best[field], best["member_key"])
