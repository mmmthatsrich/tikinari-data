"""Read the reduplications papakupu states. Pure strings; no DB.

See docs/superpowers/specs/2026-09-21-reduplication-design.md.

This module never decides that a reduplication exists — papakupu does, in a
sentence. Nothing here is inferred from spelling, and that is a deliberate
rejection of the alternative: of 871 headwords in the corpus that are a stem
written twice, a sample of twelve found ONE genuine pair. 'hemihemi' (back
of the head) doubles 'hemi', the transliterated name James. Exact doubling
joins unrelated homographs far more often than it finds a derivation.

What the spellings ARE used for is rejecting a statement that turns out to
be about some other word, which papakupu's prose does three times.
"""
import re
import unicodedata

# 'ekeeke: (Reduplicated form of eke [2])' — the entry is the reduplication.
#
# NOT anchored on the opening bracket: 20 of the 21 forward statements are
# parenthesised and 'wareware' is not ('– reduplicated form of ware [2].)').
# The containment filter, not the punctuation, is what rejects a statement
# about another word, so requiring the bracket only loses a true pair.
#
# Both wordings: papakupu writes 'Reduplication of' as well as 'reduplicated
# form of'. Matching only the longer one silently dropped 'karokaro < karo'
# and 'kakanga < kanga', two clean stated pairs.
#
# 'plus' excluded: 'the agentive prefix kai-, plus reduplication of taki [2]'
# describes kai- AND a reduplication, so 'kaitātaki' is not a reduplication
# OF 'taki' — filing it as one skips a step and names the wrong base.
#
# The base is Māori letters only. Containment alone would accept a function
# word the source never named: papakupu holds 'te' as an entry and 'te' sits
# inside 'matemate', so a gloss reading 'reduplicated form of te kupu mate'
# would otherwise ship 'matemate < te' at confidence 'certain'.
_FORWARD = re.compile(
    r"(?<!plus\s)reduplicat(?:ed\s+forms?|ion)\s+of\s+"
    r"([a-zāēīōū]+)\s*(?:\[\s*(\d+)\s*\])?",
    re.I)
# 'hoko: In the reduplicated forms hohoko and hokohoko...' — the entry is the
# base. The negative lookahead keeps this off the forward shape's 'of'.
_INVERSE = re.compile(
    r"reduplicated\s+forms?,?\s+(?!of\b)([a-zāēīōū]+)"
    r"(?:\s*(?:and|,)\s*([a-zāēīōū]+))?", re.I)


def fold(text):
    """Lowercase and strip macrons, for comparison only.

    Unlike utils.normalise_search_key this does NOT collapse doubled vowels.
    That collapse turns 'ekeeke' into 'ekeke', which is no longer 'eke'
    twice — it destroys the seam that makes a reduplication visible, and it
    is the reason this module folds for itself instead of reusing the search
    key.
    """
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in decomposed
                   if unicodedata.category(c) != "Mn")


# Grammatical words that are also papakupu headwords, so a regex slip could
# resolve one as a base. None of the twenty real bases is here, and the
# shortest of those ('eke', 'nao', 'roa') is three letters, so a length rule
# cannot separate them — 'nga', 'ana', 'atu' and 'mai' are three too.
#
# Defensive: no statement in the corpus today names one. The hazard is a
# refresh writing 'reduplicated form of te kupu mate' on 'matemate', where
# containment alone accepts 'te' and ships the pair at confidence 'certain'.
# Skipping a real reduplication OF a particle is the safer failure.
_NOT_A_BASE = frozenset((
    "te", "nga", "ngā", "he", "a", "e", "o", "i", "ki", "ko", "me",
    "na", "nā", "no", "nō", "ra", "rā", "ai", "au", "ana", "are",
    "atu", "mai", "iho", "ake",
))


def is_plausible(child, base):
    """Could *child* be a reduplication of *base*? A filter, never a test.

    papakupu has already said it is. This only rejects a sentence that names
    a different word: takapau's entry discusses the cognate 'momoe', and
    puri's names 'pupuhi', which comes from 'puhi'.

    Deliberately loose — containment, not a pattern. Māori reduplicates in
    more shapes than a tidy rule admits: 'eke' -> 'ekeeke' (full), 'nui' ->
    'nunui' (initial syllable), 'korero' -> 'korerorero' (final foot),
    'pawera' -> 'pawerawera' (inside a compound), 'aria' -> 'ariaria' (two
    morae). A rule tight enough to name each shape rejected eight genuine
    statements while this was being designed, and throwing away what the
    source said is the worse error: the source's assertion, not our pattern,
    is what licenses the row.
    """
    c = fold(child).strip(".,;:")
    b = fold(base).strip(".,;:")
    if b in _NOT_A_BASE:
        return False
    return bool(c and b and c != b and len(c) > len(b) and b in c)


def read_reduplications(headword, definition):
    """[(child, base, sense_no|None)] for each statement in *definition*.

    Both shapes, forward first. A pair stated from both ends appears once;
    the forward statement is preferred because only it carries the base's
    sense number ('nanao' is stated by its own entry as 'nao [1]' and again
    by nao's entry with no number).
    """
    out, seen = [], set()
    text = definition or ""
    for match in _FORWARD.finditer(text):
        base = match.group(1).strip(".,;:")
        sense = match.group(2)
        if not is_plausible(headword, base):
            continue
        key = (fold(headword), fold(base))
        if key in seen:
            continue
        seen.add(key)
        out.append((headword, base, int(sense) if sense else None))
    for match in _INVERSE.finditer(text):
        for child in [g for g in match.groups()[:2] if g]:
            if not is_plausible(child, headword):
                continue
            key = (fold(child), fold(headword))
            if key in seen:
                continue
            seen.add(key)
            out.append((child, headword, None))
    return out
