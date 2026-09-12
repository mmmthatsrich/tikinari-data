"""Describe how a derived form relates to its base. Pure strings; no DB.

See docs/WORD_FORMATION_DESIGN.md. The `process` and `affix` fields describe
the two spellings — that `whakaae` is `whaka-` plus `ae` is visible in the
strings — and never assert that a derivation exists. What asserts that is the
source: Williams's layout (D36), Te Matatiki's bracketed components, or
Paekupu's component notes.

So these functions report only what the spellings show and return nothing
where they show nothing. A row with a base and no process is honest; a guessed
process would be the invention the rubric forbids.
"""
import re

_SEPARATOR = re.compile(r"\s+-\s+")


def describe_derivation(child, base):
    """(process, affix) for a derived form and its base, or (None, None).

    'reduplication' is reserved for an exact doubling. A base at the front is a
    suffix and a base at the end is a prefix; a base sitting in the middle, or
    absent, yields nothing.
    """
    child = (child or "").strip().lower()
    base = (base or "").strip().lower()
    if not child or not base or child == base or base not in child:
        return (None, None)

    if child == base + base:
        return ("reduplication", None)
    if child.startswith(base):
        return ("suffix", "-" + child[len(base):])
    if child.endswith(base):
        return ("prefix", child[:-len(base)] + "-")
    return (None, None)


def parse_component_note(note):
    """('form', 'gloss'|None) from a Paekupu component note, or None.

    'wete - to release, set free' is form and meaning together, the richest
    shape in the corpus for word formation. The separator is a spaced hyphen,
    so a hyphen inside a term ('ia-tuku - artery') is not mistaken for one.
    """
    text = (note or "").strip()
    if not text:
        return None
    # 'He kupu mino.' is a loan marker about the entry, not a component (D27).
    if re.match(r"^\s*he\s+kupu\s+mino", text, re.IGNORECASE):
        return None

    parts = _SEPARATOR.split(text, maxsplit=1)
    form = parts[0].strip()
    if not form:
        return None
    gloss = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return (form, gloss)


def dedupe_components(parts):
    """Collapse components naming the same base, keeping the first and its order.

    Paekupu resolves a cross-reference per sense, so a term built on a word with
    two senses names that word twice — 'aeharua' arrived as aeha, aeha, rua.
    Position is meaning in a compound, so a spurious repeat does not merely add
    a row, it renumbers every component after it.

    `parts` is [(base_entry_id, form, gloss), ...] in the order the source
    printed them.
    """
    seen, out = set(), []
    for part in parts or []:
        key = part[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(part)
    return out
