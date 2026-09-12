"""Evidence rules for concept membership. Pure strings and dicts; no DB.

See docs/superpowers/specs/2026-09-12-concept-layer-design.md.

Within a source, identity is STATED — each source groups its own senses into
words. Across sources it must be inferred from circumstantial evidence and
judged. These functions keep those two things apart.
"""
import re

# Grouping by headword inside a source is right for Ngata's 14 'hoatu' rows,
# but it would merge two genuine Ngata homographs and nothing in the source's
# structure would say otherwise. Everything else is 'certain'.
SEED_CONFIDENCE = {"ngata": "probable", "papakupu": "probable"}

_WORD_ID = re.compile(r"word_id=(\d+)")

# Sources whose senses are split across rows sharing one headword.
_GROUP_BY_HEADWORD = {"ngata", "papakupu"}


def lexeme_key(source_id, source_entry_id, headword_search, locator):
    """Which lexeme a sense belongs to WITHIN its own source.

    He Pātaka Kupu scatters one lemma over several rows and names the grouping
    in entry.locator ('word_id=930'). Ngata and Papakupu split by headword.
    Williams and Te Aka give one entry per word.
    """
    if source_id == "hepatakakupu":
        m = _WORD_ID.search(locator or "")
        if m:
            return (source_id, "word", m.group(1))
    if source_id in _GROUP_BY_HEADWORD:
        return (source_id, "hw", (headword_search or "").strip().lower())
    return (source_id, "entry", str(source_entry_id))


# Ordered strongest first. The confidence a membership earns is the strongest
# kind present, so these are tiers rather than a sum.
#
# There is no 'shared_cognate_set' kind. Every row in pollex_entry_links (and
# every ETY_entry_link row that reached a sense) carries match_method
# 'headword_exact' — matched on spelling, never on meaning. So two senses
# 'share a cognate set' precisely because they share a headword_search, which
# would launder same-headword into a 'probable' evidence kind when
# same-headword is the one thing this design says is NEVER evidence (see
# positive_evidence's docstring). Removed after the Task 10 fix-round audit
# found it merging ten distinct 'hoi' words into one concept.
EVIDENCE_WEIGHT = {
    "cites_source":       1.0,   # Te Matatiki citing 'himoemoe W.50'
    "shared_example":     0.9,   # two sources printing the same sentence
    "attributed_quote":   0.7,   # Te Aka citing 'W 1971:54'
    "gloss_overlap":      0.5,
    "gloss_overlap_weak": 0.3,
}

EVIDENCE_CONFIDENCE = {
    "cites_source":       "certain",
    "shared_example":     "certain",
    "attributed_quote":   "probable",
    "gloss_overlap":      "probable",
    # gloss_overlap resting on exactly one shared content word is the
    # corpus's weakest signal, not an ordinary case of it: measured at
    # 94% of all cross-source attachment (69,268 memberships) with 74%
    # of THAT (51,318) resting on a single shared word — himoemoe-style
    # terse glosses ('Acidic' / 'Acid, sour.') that agree by coincidence
    # as often as by genuine correspondence. A distinct kind, not a size
    # check inside confidence_for, so it shows up by name in the sweep
    # batch instead of forcing a reviewer to infer why a membership is
    # weak. Two or more shared words stays ordinary gloss_overlap.
    "gloss_overlap_weak": "uncertain",
}

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "is", "be", "or", "and", "for", "with",
    "as", "by", "at", "from", "on", "into", "it", "that", "this", "any", "some",
    "one", "used", "esp", "etc", "see", "also", "n", "v", "adj", "vt", "vi",
})

# The one tuning parameter in the design. Set by measuring against the judged
# calibration clusters (Task 10, first real build against the full corpus).
#
# 2 was too tight: himoemoe's six sources gloss the same word as terse single
# words ('Acidic', 'Acid, sour.') that only ever share ONE content word with
# each other, so a floor of 2 fragmented it into four unconnected concepts
# instead of the one it is. Lowered to 1.
#
# Re-checked at 1 vs 2 after shared_cognate_set was removed (see
# EVIDENCE_WEIGHT), against a wider set of hand-judged clusters (hiwi, hoi,
# huatea, himoemoe, huripari, hoatu, itinga): 1 matches or beats 2 on every
# one of them. Raising to 2 buys nothing on the cluster that motivated the
# audit (hoi's mis-merge was shared_cognate_set, not gloss_overlap — at
# either threshold te_aka's own entry 1331 still bundles 'ear lobe' together
# with 'far off, distant' under one lexeme, because te_aka encodes them as
# one entry and the design trusts a source's own entry-per-lexeme structure)
# and it actively breaks two correct unifications: huripari (ngata + paekupu
# + te_aka + williams, one word, only ever sharing ONE content word like
# 'tornado' or 'wind' per pair) and hoatu (same pattern with 'give'/'hand
# over'), both of which fragment into 3-4 pieces at threshold 2 for no
# corresponding gain elsewhere. hiwi's raw count happens to hit its judged
# total (10) at threshold 2, but only because it splits an evidently correct
# merge (te_aka 'to pull back, jerk' + williams 'jerk a fishing line') apart
# — a coincidence, not a fix; hiwi's real remaining errors (williams' entries
# 1251 and 1252 each bundle 2-4 of the judged eight words under one entry
# number) are a source-structure limit neither value touches.
GLOSS_OVERLAP_MIN = 1


def _content_words(text):
    return frozenset(w for w in re.findall(r"[a-z]+", (text or "").lower())
                     if w not in _STOPWORDS and len(w) > 2)


class GlossIndex:
    """How many glosses contain EVERY word of a set.

    Built from an iterable of gloss strings, never from a connection: this
    module holds no DB code (see the module docstring) and 54_build_concepts
    does the query.

    The measure is deliberately the document frequency of the SET, not of its
    words. 'throw' is in 214 glosses and 'away' in 371, but {throw, away} is
    in 15 — a per-word measure would call that pair common when it is
    specific. See the spec, §2.
    """

    def __init__(self, glosses):
        self._postings = {}
        self._n = 0
        for gloss in glosses:
            i = self._n
            self._n += 1
            for word in _content_words(gloss):
                self._postings.setdefault(word, set()).add(i)

    def __len__(self):
        return self._n

    def df(self, words):
        """Glosses containing every word. 0 for an empty or unknown set.

        A word absent from the index is in no gloss, so the answer is 0 — an
        honest reading, and unreachable in production, where the index is
        built from the same sense.gloss_en column the compared glosses came
        from. It is reachable in tests using a small inline corpus.
        """
        try:
            postings = [self._postings[w] for w in words]
        except KeyError:
            return 0
        if not postings:
            return 0
        postings.sort(key=len)          # intersect the smallest first
        hits = postings[0]
        for other in postings[1:]:
            hits = hits & other
            if not hits:
                return 0
        return len(hits)


def gloss_coverage(a_words, b_words):
    """Jaccard of two content-word sets: |A∩B| / |A∪B|.

    The axis a word count cannot see. Two sources both glossing a word as
    exactly 'name' agree completely, however common 'name' is elsewhere in
    the corpus; two long glosses that happen to share 'form' do not.

    0.0 when either side has no content words, so a gloss of nothing but
    stopwords links to nothing.
    """
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)


def positive_evidence(a, b):
    """[{kind, detail, weight}] linking two senses, strongest first.

    Cross-source only. Within-source grouping is the seeding step's job, and
    counting it here would let one source's internal repetition masquerade as
    corroboration from another.

    Same headword_search is deliberately absent: it generates candidates, and
    is never itself evidence.
    """
    if a["source_id"] == b["source_id"]:
        return []

    found = []

    if b["entry_id"] in a["cites"] or a["entry_id"] in b["cites"]:
        found.append(("cites_source",
                      f"{a['source_id']} cites the {b['source_id']} entry"))

    shared_ex = a["examples"] & b["examples"]
    if shared_ex:
        found.append(("shared_example",
                      f"both print {sorted(shared_ex)[0][:60]!r}"))

    shared_cit = a["citations"] & b["citations"]
    if shared_cit:
        found.append(("attributed_quote",
                      f"both cite {sorted(shared_cit)[0][:40]!r}"))

    # No shared_cognate_set check: see the comment above EVIDENCE_WEIGHT.
    # cognate_sets is still carried on the sense-view for possible later
    # display use, but it is deliberately not consulted here.

    overlap = _content_words(a["gloss_en"]) & _content_words(b["gloss_en"])
    if len(overlap) == GLOSS_OVERLAP_MIN:
        # Exactly the floor: one shared content word, the corpus's weakest
        # signal (see the comment on EVIDENCE_CONFIDENCE). Its own kind, so
        # a reviewer sees why the membership is weak instead of a plain
        # gloss_overlap that looks the same as a two-or-more-word match.
        found.append(("gloss_overlap_weak",
                      "glosses share only " + ", ".join(sorted(overlap)[:4])))
    elif len(overlap) > GLOSS_OVERLAP_MIN:
        found.append(("gloss_overlap",
                      "glosses share " + ", ".join(sorted(overlap)[:4])))

    return [{"kind": k, "detail": d, "weight": EVIDENCE_WEIGHT[k]}
            for k, d in found]


_MACRONS = str.maketrans("āēīōūĀĒĪŌŪ", "aeiouAEIOU")

_CONFIDENCE_ORDER = ("uncertain", "probable", "certain")


def _macron_shape(headword):
    """Which vowels a spelling marks long — the claim it makes about length."""
    text = (headword or "").strip().lower()
    return tuple(ch in "āēīōū" for ch in text)


def _pos_atoms(pos):
    return frozenset(p.strip().lower()
                     for p in re.split(r"[,/|]", pos or "") if p.strip())


def _extract_base(atom):
    """Extract the base word from a PoS atom before parenthetical qualifiers.

    'Verb (transitive)' and 'Verb (intransitive)' both extract to 'verb'.
    """
    return re.split(r'\s*\(', atom)[0].strip()


def blocks(a, b):
    """Reasons these two senses must NOT share a concept.

    Negative evidence is first-class and is the safety mechanism of the whole
    design: it is what stops a third source, compatible with each of two
    separated words, quietly joining them.
    """
    reasons = []

    # A source's own structure separating them outranks any inference.
    if a["source_id"] == b["source_id"] and a["lexeme"] != b["lexeme"]:
        reasons.append(
            f"{a['source_id']} files these as different words "
            f"({a['lexeme'][-1]} vs {b['lexeme'][-1]})")

    # headword_search strips macrons, so two spellings can share a key while
    # making opposite claims about vowel length: hia vs hīa.
    ha, hb = (a["headword"] or "").strip().lower(), (b["headword"] or "").strip().lower()
    if ha and hb and ha != hb:
        if ha.translate(_MACRONS) == hb.translate(_MACRONS):
            if _macron_shape(ha) != _macron_shape(hb):
                reasons.append(f"macron disagreement: {ha!r} vs {hb!r}")

    # POS block fires only when BOTH sides are single-valued and their bases differ.
    # A source listing several parts of speech is describing a word that functions
    # several ways; that is not a claim excluding another source's single tag.
    atoms_a, atoms_b = _pos_atoms(a["pos"]), _pos_atoms(b["pos"])
    if atoms_a and atoms_b and len(atoms_a) == 1 and len(atoms_b) == 1:
        base_a = _extract_base(next(iter(atoms_a)))
        base_b = _extract_base(next(iter(atoms_b)))
        if base_a and base_b and base_a != base_b:
            reasons.append(f"incompatible part of speech: {a['pos']!r} vs {b['pos']!r}")

    return reasons


def confidence_for(evidence, blocked):
    """Strongest positive kind present, downgraded to uncertain by any block."""
    if blocked or not evidence:
        return "uncertain"
    best = max(_CONFIDENCE_ORDER.index(EVIDENCE_CONFIDENCE[e["kind"]])
               for e in evidence)
    return _CONFIDENCE_ORDER[best]
