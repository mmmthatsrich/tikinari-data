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

Amended once: `-hina` was missing because the vocabulary above was measured
from hepatakakupu alone. te_aka's own suffix groups use it — `uru
'(-a,-hina)'`, `taiapo '(-hia,-hina,-tia)'` — five times, refused as
unrecognised until this fix. PASSIVE now holds 14 (NOMINALISATION still 9).
"""
import re
import unicodedata

from word_formation import describe_derivation

PASSIVE = ("-tia", "-hia", "-ina", "-ngia", "-ria", "-mia", "-kia", "-whia",
           "-na", "-a", "-ia", "-kina", "-whina", "-hina")
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


class Tally:
    """Per-source bookkeeping for the refusal report spec §6 requires: tokens
    seen and tokens refused, values included — "a silent drop would hide the
    day a real suffix falls outside the list," which is exactly how `-hina`
    stayed hidden.

    Pure bookkeeping only: no printing, no DB, so this module stays pure. A
    caller (50_build_unified.py) owns one Tally per source, passes it into
    the reader calls below, and prints the summary itself once the source is
    built.
    """

    def __init__(self):
        self.seen = 0
        self.refused = []

    def keep(self):
        self.seen += 1

    def refuse(self, token):
        self.seen += 1
        self.refused.append(token)


def derived_pair(base, candidate, tally=None):
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
    if affix in _CLASS:
        if tally is not None:
            tally.keep()
        return affix
    if tally is not None:
        tally.refuse(affix)
    return None


def compose(headword, suffix):
    """'kake' + '-a' -> 'kakea'. Straight concatenation, macrons preserved."""
    return (headword or "").strip() + (suffix or "").lstrip("-")


# A suffix token as the sources write it: a hyphen or tilde, then letters.
# Macrons are allowed because papakupu occasionally marks one.
_TOKEN = r"[-~]\s*([a-zāēīōū]+)"

# A token may carry a trailing '?' (te_aka hedging that the form is not
# attested: '(-tia?)') and tokens may be joined by ',' or by '/' (te_aka
# listing attested alternatives: '(-tia / -ngia)'). A parenthetical whose
# content does not start with '-' or '~' — a qualifier like '(whaka)' or
# '(rorohiko)' — never matches this pattern at all, hedge-tolerant or not,
# because the first required character is the marker itself.
_PAREN_GROUP = re.compile(
    r"\(\s*((?:" + _TOKEN + r"\??\s*[,/]?\s*)+)\)", re.I)
_TILDE_TOKEN = re.compile(r"~\s*([a-zāēīōū]+)", re.I)
_BRACKET_GROUP = re.compile(r"\[\s*((?:-\s*[a-zāēīōū]+\s*,?\s*)+)\]", re.I)
_HYPHEN_TOKEN = re.compile(r"-\s*([a-zāēīōū]+)", re.I)


def _keep_known(raw_tokens, tally=None):
    """Normalise to '-xxx' for the vocabulary LOOKUP only; drop everything
    outside the vocabulary; return the ORIGINAL spelling, macrons and all.

    Dropping is the point. kimikupu_hou's '(-waro)' is a chemical component,
    temarareo's '~ kainga' means 'reflects as', and neither is a suffix. The
    vocabulary is the only thing separating them from '-tia'.

    Folding is for the lookup only. classify() itself never folds (a standing
    rule — an earlier version of this function folded the return value too,
    so paekupu's 'hanga ~ia ~hangā ~nga' shipped the composed form
    'hangahanga' — a real but different word ('trifling') — instead of
    'hangahangā'. The string appended to *out* is '-' plus the token exactly
    as the source wrote it, so a caller composing or noting it never loses
    the macron.
    """
    out = []
    for token in raw_tokens:
        original = token.strip()
        if classify("-" + fold(original)):
            out.append("-" + original)
            if tally is not None:
                tally.keep()
        elif tally is not None:
            tally.refuse("-" + original)
    return out


def read_paren_suffixes(text, tally=None):
    """['-a', '-hia'] from '(-a,-hia) to be able' or 'āmine (-tia)'.

    A '?' inside the group is te_aka hedging that it is not sure the form is
    attested ('hakarameta (-tia?)'): the group still counts as suffix
    notation for stripping the search key (strip_suffix_notation removes it
    either way), but no form is asserted here — this module reports only
    what the source shows, and a hedge is not a claim. A '/' separates
    alternatives the source DOES assert ('kihi (-tia / -ngia)'), and both
    are returned.

    A headword can carry more than one group — te_aka's 'inihua (-tia)
    (-ngia)' — so every group is read and the results accumulated, rather
    than stopping at the first group that yields a known suffix. Stopping
    early once cost the corpus 'inihuangia': only '-tia' was ever read.
    """
    out = []
    for group in _PAREN_GROUP.finditer(text or ""):
        if "?" in group.group(1):
            continue
        out.extend(_keep_known(_HYPHEN_TOKEN.findall(group.group(1)), tally))
    return out


def read_tilde_suffixes(text, tally=None):
    """['-tia', '-tanga'] from '~tia, ~tanga (1) beget' or 'ahu ~nga'.

    Separators vary: paekupu spaces them, papakupu uses commas and at least
    once a semicolon ('~a, ~ria, ~ngia; ~nga'). Reading every tilde token and
    filtering by vocabulary handles all of them without a separator rule.
    """
    return _keep_known(_TILDE_TOKEN.findall(text or ""), tally)


def read_bracket_suffixes(text, tally=None):
    """['-tia'] from 'tāpiri [-tia]'. '[Tāne]' is a domain and yields [].

    Accumulates across every bracket group in *text*, the same contract
    read_paren_suffixes and read_tilde_suffixes both follow — stopping at the
    first matching group would silently drop a second one.
    """
    out = []
    for group in _BRACKET_GROUP.finditer(text or ""):
        out.extend(_keep_known(_HYPHEN_TOKEN.findall(group.group(1)), tally))
    return out


def strip_suffix_notation(headword):
    """The bare headword, with any suffix notation removed.

    'ahu ~nga' -> 'ahu'. This is what headword_search must be built from:
    keying 1,407 paekupu entries on 'ahu ~nga' severs them from the plain
    'ahu' four other sources hold (spec §5).

    A tilde can also introduce an IRREGULAR alternative form rather than a
    suffix — 'hau ~hāua ~tanga' names 'hāua' as a whole irregular derivation
    of 'hau', not 'hau' plus a suffix, and 'tiki atu ~tīkina atu' names
    'tīkina atu' as a whole alternative phrase. Neither '~hāua' nor
    '~tīkina' is in the suffix vocabulary, so the strip loop below leaves
    them standing; deleting just the tilde token would still glue a
    trailing word from the alternative onto the base ('tiki atu ~tīkina
    atu' -> 'tiki atu atu', wrong). Truncating at the first tilde still
    standing, once every recognised suffix has already been removed,
    keeps the base only.
    """
    text = (headword or "").strip()
    if not text:
        return text
    text = _PAREN_GROUP.sub(" ", text)
    text = _BRACKET_GROUP.sub(" ", text)
    # Only strip a tilde run that the vocabulary recognises, so a stray tilde
    # in an unrelated headword does not truncate it.
    for match in reversed(list(_TILDE_TOKEN.finditer(text))):
        if classify("-" + fold(match.group(1))):
            text = text[:match.start()] + text[match.end():]
    text = re.sub(r"\s+", " ", text).strip()
    tilde_idx = text.find("~")
    if tilde_idx != -1:
        text = text[:tilde_idx].strip()
    return text


# 'Pass. arohaina' / '; pass. arahina.' — Williams's marker, then the word.
_PASSIVE_MARKER = re.compile(r"\bpass\.\s*([a-zāēīōū]+)", re.I)

# A trailing '...' ("and so on") on a paekupu counting-word base, with
# whatever whitespace the tilde-stripping above left in front of it —
# 'pūtoru ~tia ...' strips to 'pūtoru ...' and this removes the rest.
_TRAILING_ELLIPSIS = re.compile(r"\s*\.\.\.\s*$")


def derived_from_list(forms, tally=None):
    """(base, derived, suffix) for every base+derived pair in *forms*.

    ngata prints one comma-separated run per record holding derived forms and
    synonyms together: 'whakaranu, whakaranua, tūkino, tūkinotia' is two
    pairs, and 'whakaranu, pūhui' is a synonym. Only the spellings separate
    them, so every ordered pair is tested and only known suffixes are kept.

    The run is NOT assumed to be ordered base-then-derived, because ngata
    interleaves pairs; each earlier form is tested against each later one.

    A shorter, unrelated base can still accidentally fit a later candidate:
    in 'patu, patua, pātuki, pātukia' (WR-HMN, 'Assault'), 'patu' + '-kia'
    also matches 'pātukia', but that word is really 'pātuki' + '-a' — a
    derivation the source never recorded. When more than one base matches
    the same candidate, only the LONGEST base is kept, the same
    longest-match principle the module already applies to suffixes. Bases
    tied in length ('kī' and 'ki', the same word spelled two ways) are both
    kept rather than picking one arbitrarily.
    """
    out = []
    items = [f for f in (forms or []) if isinstance(f, str) and f.strip()]
    by_candidate = {}
    for i, base in enumerate(items):
        for j in range(i + 1, len(items)):
            candidate = items[j]
            suffix = derived_pair(base, candidate, tally)
            if suffix:
                by_candidate.setdefault(j, []).append((base, candidate, suffix))
    for group in by_candidate.values():
        longest = max(len(base) for base, _, _ in group)
        out.extend(triple for triple in group if len(triple[0]) == longest)
    return out


def composition_bases(headword):
    """The base form(s) a suffix composes onto, for a headword that may hold
    more than one.

    paekupu's headword field mixes three shapes that all end in suffix
    notation but need different handling:
      - a single word ('ahu ~nga') -> one base.
      - a comma-joined pair of spellings ('hae, hahae ~a ~nga') -> the
        entry has two base spellings, each taking each suffix.
      - a compound ('ārai hapū ~tanga') -> ONE base that happens to contain
        a space; Māori compounds take the suffix on the whole compound, not
        on its last word alone, so the internal space must survive.
      - a parenthetical qualifier ('tāhono (rorohiko) ~a') or note
        ('āhukahuka (ki te kupu) ~tia') -> not part of the base at all, and
        removed outright rather than filtered against the suffix vocabulary
        the way strip_suffix_notation filters tildes.
      - a counting-word run trailing a literal '...' meaning "and so on"
        ('pūrua ~tia, pūtoru ~tia ...') -> the '...' is not part of the
        trailing base ('pūtoru'), though the earlier base in the same run
        ('pūrua') is already clean and untouched.

    Order matters: strip the suffix notation first (so a tilde/paren/bracket
    suffix marker is gone), then drop any remaining '(...)' qualifier, then
    split what is left on commas, then drop a trailing ellipsis from each
    base in turn.
    """
    text = strip_suffix_notation(headword)
    text = re.sub(r"\([^)]*\)", " ", text)
    bases = []
    for base in text.split(","):
        base = _TRAILING_ELLIPSIS.sub("", base)
        base = re.sub(r"\s+", " ", base).strip()
        if base:
            bases.append(base)
    return bases


def read_williams_passives(headword, definition, tally=None):
    """(base, derived, suffix) for each 'Pass. <form>' in *definition*.

    The marker alone is not enough. Williams's prose also ends sentences with
    the English verb 'pass', so 'to pass. Be' offers 'Be' as a passive; of 85
    naive matches in the corpus only 35 survive the morphological test. The
    base may be any comma-separated part of the headword ('Amu, amuamu').
    """
    bases = [p.strip() for p in re.split(r"[,;]", headword or "") if p.strip()]
    out = []
    for match in _PASSIVE_MARKER.finditer(definition or ""):
        candidate = match.group(1)
        for base in bases:
            suffix = derived_pair(base, candidate, tally)
            if suffix:
                out.append((base, candidate, suffix))
                break
    return out
