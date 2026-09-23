"""Read the derived forms — passive and nominalisation — that the sources
record, and classify them. Pure strings and lists; no DB.

See docs/superpowers/specs/2026-09-17-suffix-forms-design.md.

The vocabulary below was measured, not recalled. It is the complete set of
well-formed suffix types across hepatakakupu's 22,911 raw tokens, the largest
sample in the corpus; the eight malformed tokens across seven types that
measurement also found (-bga, -pukenga and friends) are why an unrecognised
suffix is refused here rather than coerced to the nearest real one.

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

    **Counted by kind**, because one counter was carrying four structurally
    different events and the spec's 1% tripwire consequently fired on four
    of six sources without once meaning what it says:

      suffix  a token the source wrote as suffix notation. THE tripwire
              kind — a refusal here is the '-hina' signal, a real suffix
              outside the vocabulary.
      pair    two spellings tested by derived_pair against ngata's runs. A
              refusal means they are not base + suffix, which is the
              discriminator working, not a vocabulary gap. Reported because
              a refusal could in principle name a suffix we lack.
      base    a headword _hepataka_bases cannot compose onto, because it
              carries a parenthesis. Nothing to do with the vocabulary.
      whole   a whole irregular form stored verbatim (paekupu's 'hau
              ~hāua'). These are WRITTEN, and counting them as refusals was
              the whole of paekupu's 0.89% against a 1% threshold.
      reduplication
              a tilde token that repeats its headword rather than suffixing
              it (papakupu's 'ue ~ue'). Also WRITTEN, and likewise moved out
              of the suffix refusals rather than counted against them.
    """

    KINDS = ("suffix", "pair", "base", "whole", "reduplication")

    def __init__(self):
        self._seen = {k: 0 for k in self.KINDS}
        self._refused = {k: [] for k in self.KINDS}
        self._order = []

    def _touch(self, kind):
        if kind not in self._seen:
            raise ValueError(f"unknown tally kind: {kind!r}")
        if kind not in self._order:
            self._order.append(kind)

    def keep(self, kind="suffix"):
        self._touch(kind)
        self._seen[kind] += 1

    def refuse(self, token, kind="suffix"):
        self._touch(kind)
        self._seen[kind] += 1
        self._refused[kind].append(token)

    def reclassify(self, token, kind):
        """Move one refused suffix token into *kind*, as a kept one.

        paekupu refuses '-hāua' through read_tilde_suffixes and then writes
        'hāua' whole through read_whole_forms. A move, never an add: an
        earlier version of read_whole_forms took no tally at all precisely
        to avoid counting the token twice, and that reasoning still holds
        against adding — it just does not hold against relocating.

        A token that was never refused is a no-op rather than an invention.
        """
        self._touch(kind)
        if token not in self._refused["suffix"]:
            return
        self._refused["suffix"].remove(token)
        self._seen["suffix"] -= 1
        self._seen[kind] += 1

    def seen_of(self, kind):
        return self._seen[kind]

    def refused_of(self, kind):
        return self._refused[kind]

    def refusal_rate(self, kind):
        """Refusals as a share of tokens seen, or None if the kind is unused."""
        total = self._seen[kind]
        return len(self._refused[kind]) / total if total else None

    def kinds(self):
        """The kinds that actually occurred, in KINDS order."""
        return [k for k in self.KINDS if k in self._order]

    @property
    def seen(self):
        """Every kind together — what the pre-kind report printed."""
        return sum(self._seen.values())

    @property
    def refused(self):
        return [t for k in self.KINDS for t in self._refused[k]]


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
            tally.keep(kind="pair")
        return affix
    if tally is not None:
        # 'pair', not 'suffix': this is two spellings we TESTED, not a token
        # the source wrote as suffix notation. A refusal here usually means
        # the discriminator correctly rejected a compound, so it must not
        # feed the vocabulary tripwire.
        tally.refuse(affix, kind="pair")
    return None


def compose(headword, suffix):
    """'kake' + '-a' -> 'kakea'. Straight concatenation, macrons preserved."""
    return (headword or "").strip() + (suffix or "").lstrip("-")


# Directional and manner particles. These FOLLOW a verb and cannot carry a
# passive or nominalisation themselves, so a phrase ending in one takes its
# suffix on the word in front: 'mahi anō' ("redo") passivises to 'mahia
# anō', never 'mahi anōtia'.
#
# Deliberately short. 'kau' is excluded although it trails two phrases here:
# in 'hopu kau' ("dry record (audio)") and 'whana kau' ("punt kick") the
# glosses show it modifying the verb rather than following it, so the tail
# may well be right and this rule has no business claiming them.
_TRAILING_PARTICLES = frozenset(("ano", "ake", "atu", "mai", "iho"))

# A suffix mark the source placed after the element that takes it —
# paekupu's 'heke (~nga) atu', papakupu's 'tau [-ria] mai'.
_MARK = re.compile(r"\(?~\s*[a-zāēīōū]+\)?|\[\s*-[a-zāēīōū,\s-]+\]", re.I)


def compose_phrase(base, suffix, marked_headword=None):
    """Append *suffix* to the word of *base* that actually takes it.

    compose() puts it on the end, which is right for a single word and for
    a fixed compound whose last word is the one inflected ('tangata whenua'
    -> 'tangata whenuatia'). Two shapes break that, and this function is
    the rule for both.

    First, the source may MARK the element, by writing the notation after
    it. 'heke (~nga) atu' is 'hekenga atu', and composing on the tail gave
    'heke atunga', which is not a word. Pass the original notation-bearing
    headword as *marked_headword* and the mark's position decides.

    Second, a phrase may end in a directional or manner particle, which
    cannot be inflected at all. Where the source marked nothing, the suffix
    goes on the last word that is not one of those.

    The mark wins when both apply: it is the source's statement, while the
    particle list is our grammar.

    A base of one word is returned exactly as compose() would return it,
    which is the overwhelming majority of the corpus.
    """
    base = (base or "").strip()
    words = base.split()
    if len(words) < 2:
        return compose(base, suffix)

    index = None
    if marked_headword:
        index = _marked_index(marked_headword, words)
    # A mark landing on a particle is not a claim about that particle —
    # 'mahi anō ~tia' has the notation at the end of the whole phrase, and
    # 'anō' cannot be inflected. Fall through to the word that can be.
    if index is None or fold(words[index]) in _TRAILING_PARTICLES:
        index = _last_inflectable(words)

    words[index] = compose(words[index], suffix)
    return " ".join(words)


def _marked_index(marked_headword, words):
    """Which word of *words* the source's notation sits after, or None.

    Counts the words before the FIRST mark in the original headword; that
    count is the index of the word the suffix joins. A mark at the very end
    yields the last word, which is what composing on the tail already did.
    """
    match = _MARK.search(marked_headword or "")
    if not match:
        return None
    before = len(marked_headword[:match.start()].split())
    if not 1 <= before <= len(words):
        return None
    return before - 1


def _last_inflectable(words):
    """The index of the last word that is not a trailing particle.

    Steps over a run of them ('haere atu anō'), and never returns past the
    start: a base that is nothing but particles has no better answer than
    its own last word.
    """
    index = len(words) - 1
    while index > 0 and fold(words[index]) in _TRAILING_PARTICLES:
        index -= 1
    return index


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
# The same token with no space allowed, for a reader working in prose. A
# spaced '~' there is not notation: papakupu writes 'puri ~ puru' for "puri
# OR puru" and 'Te ~ He hapū' with the tilde standing in for the headword.
_TILDE_TIGHT = re.compile(r"~([a-zāēīōū]+)", re.I)
# A token the source itself doubts — papakupu's '~iatia (?)'. te_aka writes
# the same hedge as '(-tia?)', which read_paren_suffixes already refuses.
_TILDE_HEDGED = re.compile(r"~([a-zāēīōū]+)\s*\(\s*\?\s*\)", re.I)
_BRACKET_GROUP = re.compile(r"\[\s*((?:-\s*[a-zāēīōū]+\s*,?\s*)+)\]", re.I)
_HYPHEN_TOKEN = re.compile(r"-\s*([a-zāēīōū]+)", re.I)

# A tilde run reaching to the next tilde or the end of the string. The whole
# form may be several words ('~kawea atu') or hyphenated ('~tāpiritia-atu'),
# so _TILDE_TOKEN — which stops at the first non-letter — cannot express it.
_TILDE_RUN = re.compile(r"~\s*([^~]+)")
# papakupu separates its runs with commas and at least once a semicolon; a
# run must never swallow the word after the separator.
_RUN_TAIL = re.compile(r"\s*[,;].*$", re.S)


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


def read_tilde_suffixes(text, tally=None, tight=False):
    """['-tia', '-tanga'] from '~tia, ~tanga (1) beget' or 'ahu ~nga'.

    Separators vary: paekupu spaces them, papakupu uses commas and at least
    once a semicolon ('~a, ~ria, ~ngia; ~nga'). Reading every tilde token and
    filtering by vocabulary handles all of them without a separator rule.

    *tight* refuses a tilde with a space after it, and belongs to a reader
    working in PROSE. papakupu's notation sits in the definition, where '~'
    also does two other jobs — 'puri ~ puru' means "puri or puru", and
    'Te ~ He hapū' uses it to stand in for the headword. Every one of those
    is spaced and every genuine token is tight, so across papakupu the
    spaced form yields no real suffix and five artefacts.

    paekupu is left loose on purpose. Its notation lives in the headword, a
    structured field rather than prose, where a space is untidy typography
    and not a different meaning: 'āhei ~nga ~ tanga' is '~tanga' spelled
    with a stray space, and 33 real tokens are written that way.

    A token the source hedges is refused either way. papakupu writes
    '~iatia (?)' where te_aka writes '(-tia?)'; a doubt is not a claim, and
    read_paren_suffixes already declines the te_aka form.
    """
    text = text or ""
    hedged = set(_TILDE_HEDGED.findall(text))
    pattern = _TILDE_TIGHT if tight else _TILDE_TOKEN
    tokens = [t for t in pattern.findall(text) if t not in hedged]
    return _keep_known(tokens, tally)


def redup_kind(headword, token):
    """How *token* repeats *headword*, or None if it does not.

    papakupu's tilde means "append this to the headword". Usually the token
    is a suffix — '~a' on 'uku' gives the passive 'ukua' — but sometimes it
    is the headword again, and 'ue ~ue' gives 'ueue', a word five other
    dictionaries hold.

    This is NOT the inference 2026-09-21-reduplication-design.md §2 rejects.
    There the base would be picked out of the lexicon and guessed: of 871
    headwords that are a stem written twice, a sample of twelve found ONE
    genuine pair. Here papakupu supplies BOTH strings and the relation
    between them is arithmetic on what it wrote.

    Three shapes, all measured against the whole source:

        ue         ~ue    ueue           the token IS the headword
        ui         ~uia   uiuia          the headword plus a known suffix
        whakamātau ~tau   whakamātautau  the headword's final foot

    The tail rule needs two characters and a headword longer than the
    token, so a one-letter ending ('uku' ~ 'u') is not a reduplication.
    Callers test this only AFTER classify() has declined the token, so a
    real suffix never reaches here.
    """
    head, tok = fold(headword), fold(token)
    if not head or not tok:
        return None
    if tok == head:
        return "doubling"
    for suffix in sorted(PASSIVE + NOMINALISATION, key=len, reverse=True):
        if tok == head + suffix[1:]:
            return "doubling+suffix"
    if len(tok) >= 2 and len(head) > len(tok) and head.endswith(tok):
        return "final foot"
    return None


def read_tilde_reduplications(headword, text, tally=None):
    """['ueue'] for each tilde token of *text* that repeats *headword*.

    Composed and returned whole, because the result is a form of the
    headword rather than a suffix applied to it. Tight tildes only and
    hedges refused, exactly as read_tilde_suffixes does in prose: a spaced
    '~' is papakupu writing "or", and '(?)' is the source doubting itself.

    *tally* RECLASSIFIES rather than counts, the same move
    read_whole_forms makes. read_tilde_suffixes has already seen these
    tokens and refused them as unrecognised suffixes; they are not refusals
    once they are written, but they were counted once already and must not
    be counted twice.
    """
    text = text or ""
    hedged = set(_TILDE_HEDGED.findall(text))
    out = []
    for token in _TILDE_TIGHT.findall(text):
        if token in hedged or classify(fold("-" + token)):
            continue
        if redup_kind(headword, token) is None:
            continue
        if tally is not None:
            tally.reclassify("-" + token, "reduplication")
        out.append(compose(headword, token))
    return out


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


def _classify_whole(word):
    """The longest vocabulary suffix *word* ends with, and its class.

    Unlike _keep_known, which matches a whole token against the vocabulary,
    this asks what a COMPLETE word ends with: 'kūtia' is not the suffix
    '-tia' but a word carrying it. Longest match first, so 'tākina' reads
    '-kina' rather than '-ina'.

    A word that is nothing but the suffix is refused: a bare '~ia' has no
    stem in front of it, so there is no word for it to be a derivation of.
    """
    folded = fold(word)
    for suffix in sorted(PASSIVE + NOMINALISATION, key=len, reverse=True):
        ending = suffix[1:]
        if len(folded) > len(ending) and folded.endswith(ending):
            return suffix, classify(suffix)
    return None, None


def read_whole_forms(headword, tally=None):
    """[(form, suffix, form_type)] for each tilde run naming a WHOLE word.

    paekupu prints a whole irregular derivation after a tilde where no
    fragment could express it — the stem itself changes:

        hau    -> hāua      the vowel lengthens
        kukuti -> kūtia     the stem contracts
        momotu -> motukia   the reduplication is undone

    A run whose first element IS a known suffix is left alone:
    read_tilde_suffixes owns those, and returning '-nga' here would write a
    fragment into the form column as though it were a word.

    The suffix is read off the run's FIRST element, split on whitespace or
    hyphen, because the form may carry a directional particle: 'kawea atu'
    ends in 'tu', which is not a suffix, while its first element 'kawea'
    ends in '-a', which is.

    *tally* RECLASSIFIES rather than counts. Every run here has already been
    seen and refused by read_tilde_suffixes on the same headword —
    _TILDE_TOKEN matches '~hāua' and _keep_known refuses '-hāua' — so
    counting it again would double it. Moving it does not: the token stops
    being a refused suffix and becomes a kept whole form, which is what it
    is. Sixteen rows were otherwise reported as refusals, and they were the
    whole of paekupu's 0.89% against the spec's 1% tripwire.

    (An earlier version took no tally at all, for the double-count reason
    above. That reasoning was right about adding and wrong about moving.)

    The token handed to reclassify is '-' plus the run's first element,
    which is exactly the string _keep_known refused: _TILDE_TOKEN captures
    one run of letters, and the first element here is that same run of
    letters, split on whitespace or hyphen.

    See docs/superpowers/specs/2026-09-19-irregular-whole-forms-design.md.
    """
    out = []
    for match in _TILDE_RUN.finditer(headword or ""):
        # The paren of a '(~…)' group rides along on the token. Strip it from
        # the RUN, not just from the head used for the lookup: the run is what
        # becomes the stored form, and the corpus guard rejects '(' but not
        # ')', so a stray closing paren would reach the form column unseen.
        run = _RUN_TAIL.sub("", match.group(1)).replace(")", " ").strip()
        run = re.sub(r"\s+", " ", run)
        if not run:
            continue
        # '(~nga)' leaves the paren riding on the token; strip it before the
        # vocabulary lookup or a known suffix reads as an unknown word.
        head = re.split(r"[\s\-]", run)[0].strip("().,;")
        if classify("-" + fold(head)):
            continue
        suffix, form_type = _classify_whole(head)
        if form_type:
            if tally is not None:
                tally.reclassify("-" + head, "whole")
            out.append((run, suffix, form_type))
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
