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
