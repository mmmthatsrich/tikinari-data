"""Read the derived forms — passive and nominalisation — that the sources
record, and classify them. Pure strings and lists; no DB.

See docs/superpowers/specs/2026-09-17-suffix-forms-design.md.

The vocabulary below was measured, not recalled. It is the complete set of
well-formed suffix types across hepatakakupu's 22,911 raw tokens, the largest
sample in the corpus; the nine malformed tokens that measurement also found
(-bga, -pukenga and friends) are why an unrecognised suffix is refused here
rather than coerced to the nearest real one.

This module decides what a string SAYS. It never decides whether a derived
form exists — the source's own filing does that.
"""
import re
import unicodedata

from word_formation import describe_derivation

PASSIVE = ("-tia", "-hia", "-ina", "-ngia", "-ria", "-mia", "-kia", "-whia",
           "-na", "-a", "-ia", "-kina", "-whina")
NOMINALISATION = ("-nga", "-tanga", "-hanga", "-ranga", "-anga", "-manga",
                  "-kanga", "-inga", "-unga")

# Longest-match needs no ordering here: describe_derivation returns the ENTIRE
# remainder as one affix ('whakamātanga' minus 'whakamā' is '-tanga', never
# '-anga'), and _CLASS is an exact-match lookup. The rule holds structurally.
_CLASS = {s: "passive" for s in PASSIVE}
_CLASS.update({s: "nominalisation" for s in NOMINALISATION})


def fold(text):
    """Lowercase and strip macrons, for comparison only.

    Callers store the ORIGINAL spelling: Williams's 'hīa' is stored 'hīa'.
    Folding exists because the sources are inconsistent about macrons between
    a base and its derived form, not because the macrons are noise.
    """
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def classify(suffix):
    """'passive', 'nominalisation', or None for anything not in the vocabulary."""
    return _CLASS.get((suffix or "").strip().lower())


def derived_pair(base, candidate):
    """The suffix taking *base* to *candidate*, or None.

    Returns None rather than guessing whenever the two spellings do not show
    a known suffix: a synonym, a shared prefix that is not a suffix, an
    irregular form, or the same word twice. This is the discriminator that
    separates ngata's derived forms from the synonyms sitting beside them in
    the same comma-separated run.
    """
    process, affix = describe_derivation(fold(candidate), fold(base))
    if process != "suffix":
        return None
    return affix if affix in _CLASS else None


def compose(headword, suffix):
    """'kake' + '-a' -> 'kakea'. Straight concatenation, macrons preserved."""
    return (headword or "").strip() + (suffix or "").lstrip("-")
