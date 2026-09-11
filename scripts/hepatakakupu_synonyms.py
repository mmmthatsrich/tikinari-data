"""Read He Pātaka Kupu's `synonyms` marker. Pure string -> dict|None; no DB.

The source wraps a synonym it does not itself define:

    ["parewhero", "tārukenga", "whakapiko", "(whārona awatea )"]

Across the whole source the marker separates cleanly — 728 of the wrapped
values are not headwords in He Pātaka Kupu against 6 that are, and 13,922 of
the plain ones are headwords against 4 that are not — so the parentheses mean
"no entry here", not "phrase" and not "uncertain". They are furniture about
the reference, the same kind of thing as Paekupu's `he kupu mino` (D27), and
belong out of the term itself.
"""


def parse_synonym(raw):
    """Return {'headword': str, 'has_entry': bool} or None if there is no term.

    `has_entry` False means the source says it defines no entry under this
    word — the relation is still real, but its target legitimately does not
    exist and is not something for the sweep to resolve.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None

    has_entry = True
    # Only a balanced outer pair is the marker; '(tū atu' has no closing paren
    # and is text, while '(tahi (i te) tahua )' must keep its inner pair.
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
        has_entry = False

    if not text:
        return None
    return {"headword": text, "has_entry": has_entry}


def pair_synonyms(synonyms, senses):
    """Pair each synonym with the sense of its target that the source named.

    He Pātaka Kupu writes 'hikoki (2)' — sense 2 of hikoki. Because the source
    splits every sense into its own entry row, that pointer identifies the exact
    entry rather than merely narrowing it, which is the difference between a
    reference that resolves and one that stays ambiguous.

    The two lists arrive from JSON and are only as parallel as the parser made
    them, so a sense list that is absent, short or long is tolerated rather than
    trusted. A blank synonym takes its sense with it.
    """
    names = list(synonyms or [])
    marks = list(senses or [])
    marks += [None] * (len(names) - len(marks))
    return [(n.strip(), m) for n, m in zip(names, marks) if n and n.strip()]
