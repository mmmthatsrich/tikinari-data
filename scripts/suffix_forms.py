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


# A suffix token as the sources write it: a hyphen or tilde, then letters.
# Macrons are allowed because papakupu occasionally marks one.
_TOKEN = r"[-~]\s*([a-zāēīōū]+)"

_PAREN_GROUP = re.compile(r"\(\s*((?:" + _TOKEN + r"\s*,?\s*)+)\)", re.I)
_TILDE_TOKEN = re.compile(r"~\s*([a-zāēīōū]+)", re.I)
_BRACKET_GROUP = re.compile(r"\[\s*((?:-\s*[a-zāēīōū]+\s*,?\s*)+)\]", re.I)
_HYPHEN_TOKEN = re.compile(r"-\s*([a-zāēīōū]+)", re.I)


def _keep_known(raw_tokens):
    """Normalise to '-xxx' and drop everything outside the vocabulary.

    Dropping is the point. kimikupu_hou's '(-waro)' is a chemical component,
    temarareo's '~ kainga' means 'reflects as', and neither is a suffix. The
    vocabulary is the only thing separating them from '-tia'.
    """
    out = []
    for token in raw_tokens:
        suffix = "-" + token.strip().lower()
        if classify(suffix):
            out.append(suffix)
    return out


def read_paren_suffixes(text):
    """['-a', '-hia'] from '(-a,-hia) to be able' or 'āmine (-tia)'."""
    for group in _PAREN_GROUP.finditer(text or ""):
        found = _keep_known(_HYPHEN_TOKEN.findall(group.group(1)))
        if found:
            return found
    return []


def read_tilde_suffixes(text):
    """['-tia', '-tanga'] from '~tia, ~tanga (1) beget' or 'ahu ~nga'.

    Separators vary: paekupu spaces them, papakupu uses commas and at least
    once a semicolon ('~a, ~ria, ~ngia; ~nga'). Reading every tilde token and
    filtering by vocabulary handles all of them without a separator rule.
    """
    return _keep_known(_TILDE_TOKEN.findall(text or ""))


def read_bracket_suffixes(text):
    """['-tia'] from 'tāpiri [-tia]'. '[Tāne]' is a domain and yields []."""
    for group in _BRACKET_GROUP.finditer(text or ""):
        found = _keep_known(_HYPHEN_TOKEN.findall(group.group(1)))
        if found:
            return found
    return []


def strip_suffix_notation(headword):
    """The bare headword, with any suffix notation removed.

    'ahu ~nga' -> 'ahu'. This is what headword_search must be built from:
    keying 1,407 paekupu entries on 'ahu ~nga' severs them from the plain
    'ahu' four other sources hold (spec §5).
    """
    text = (headword or "").strip()
    if not text:
        return text
    text = _PAREN_GROUP.sub(" ", text)
    text = _BRACKET_GROUP.sub(" ", text)
    # Only strip a tilde run that the vocabulary recognises, so a stray tilde
    # in an unrelated headword does not truncate it.
    for match in reversed(list(_TILDE_TOKEN.finditer(text))):
        if classify("-" + match.group(1).lower()):
            text = text[:match.start()] + text[match.end():]
    return re.sub(r"\s+", " ", text).strip()
