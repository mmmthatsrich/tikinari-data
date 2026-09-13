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
    # A pair is gloss_overlap_weak precisely when it fails BOTH measures
    # below (gloss_coverage and GlossIndex.df — see COVERAGE_FLOOR /
    # DISTINCT_CEILING): the shared word(s) are a small fraction of each
    # gloss AND common across the corpus. Shared-word count alone no longer
    # decides it: 'Spoon'/'spoon.' is one shared word and grades ordinary
    # because coverage is total, and a three-word overlap can still grade
    # weak if it is diluted across two long, common glosses. A distinct
    # kind, not a size check inside confidence_for, so it shows up by name
    # in the sweep batch instead of forcing a reviewer to infer why a
    # membership is weak.
    #
    # Motivation (measured before this design, under the old single-count
    # rule this replaced): gloss_overlap was 94% of all cross-source
    # attachment (69,268 memberships), with 74% of THAT (51,318) resting on
    # a single shared word — himoemoe-style terse glosses ('Acidic' /
    # 'Acid, sour.') that agree by coincidence as often as by genuine
    # correspondence. That volume is why a distinct weak kind exists at
    # all; it no longer determines membership in it.
    "gloss_overlap_weak": "uncertain",
}

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "is", "be", "or", "and", "for", "with",
    "as", "by", "at", "from", "on", "into", "it", "that", "this", "any", "some",
    "one", "used", "esp", "etc", "see", "also", "n", "v", "adj", "vt", "vi",
})

# SUPERSEDED by COVERAGE_FLOOR / DISTINCT_CEILING below. Kept because its
# findings are why this design exists: the himoemoe and huripari cases
# recorded here are the ones a single count threshold cannot hold together.
#
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

# Set by grid search against the recorded calibration answers — see
# docs/superpowers/specs/2026-09-13-gloss-evidence-design.md §2 and §5,
# scripts/tune_gloss_thresholds.py, and the full grid output in
# docs/superpowers/specs/2026-09-13-gloss-threshold-grid.txt. A pair earns
# ordinary gloss_overlap when it is strong on EITHER axis; weak on both makes
# it gloss_overlap_weak.
#
# One of these two numbers is evidence and the other is a promise. Read on
# before changing either.
#
# THE FIRST THING TO KNOW: they do not decide membership. Across the whole
# grid — COVERAGE_FLOOR over (0.3, 0.4, 0.5, 0.6, 0.7) x DISTINCT_CEILING over
# (5, 10, 20, 40, 80), each point a form_concepts run in memory over all
# 55,765 headword keys — every point yields the same 95,116 concepts, and
# every point satisfies all four recorded calibration answers identically
# (hiwi 9 concepts, hia never joined to hīa, himoemoe unified over 4 sources,
# paekupu:hoi single-source). A pair with a non-empty overlap attaches either
# way, because gloss_overlap and gloss_overlap_weak are BOTH evidence and
# form_concepts attaches a seed on any evidence at all. These two numbers
# choose only which KIND, and the kind feeds only confidence_for. So what they
# set is the confidence a grouping carries and therefore whether
# 60_export_app_db ships it. They cannot over-merge. They can only withhold.
#
# That is why the four recorded answers cannot discriminate between grid
# points on their own, and why an earlier version of this search — 'satisfy
# the four, maximise what ships' — was a broken rule rather than a
# measurement: what ships rises monotonically as either axis loosens, so
# maximising it can only ever name the loose corner of whatever grid was run.
# What replaced it: a fifth criterion the recorded answers CAN discriminate
# on, and then the TIGHTEST point satisfying everything rather than the
# loosest. The owner of this dictionary, asked which error costs more,
# answered that a wrong merge is worse than a missed one — showing two
# different words as one misinforms about the language, while a missed merge
# shows a user two entries where one would do, which is what every existing
# dictionary already does. Concepts are a pure overlay (§4: all 175,101 senses
# reach the app regardless, and 27% already belong to no concept), so a
# withheld concept degrades to separate search results rather than to missing
# data. Loose is the expensive direction.
#
# DISTINCT_CEILING = 10 is the evidence. The fifth criterion is that a
# recorded-correct grouping must not merely form, it must reach users: getting
# himoemoe's sources into one concept and then tiering it 'uncertain' denies
# the recorded answer as surely as fragmenting it would, because the export
# withholds it and nobody sees the unification.
#
# What himoemoe actually produces, at every point on the grid, is TWO
# concepts, not the single six-source one the superseded comment above calls
# 'the one it is': {hepatakakupu, te_aka, te_matatiki, williams} and
# {kimikupu_hou, paekupu}. hepatakakupu's gloss_en is NULL and it seeds first,
# so the split is not a gloss-grading outcome and no threshold on this grid
# closes it. The recorded answer is >= 4 sources unified (the acceptance test
# asserts exactly that), and the first concept satisfies it.
#
# Stepping the ceiling one at a time at floor 0.5 — measured, not from the
# 5/10/20/40/80 grid:
#
#     ceil   himoemoe shipping span    ships
#        5                        0   89,311
#        6                        0   89,569
#        7                        4   89,803   <- the cliff
#       10                        4   90,418   <- SET
#
# So 10 is NOT the tightest ceiling that ships himoemoe: 7 is, and the
# tightest-satisfying rule would pick 7 on the measurement alone. 10 is three
# steps of deliberate clearance above the cliff, and it costs 615 concepts of
# tightness given up knowingly.
#
# The clearance is there because the pin is thin. The whole ceiling constraint
# is ONE membership in ONE cluster: te_matatiki joins on a single
# gloss_overlap at coverage 0.20 with df 7, the word being 'acidic', which
# occurs in exactly 7 glosses corpus-wide. (williams joins the same concept on
# cites_source and is certain whatever the ceiling; te_aka on a shared
# example.) A ceiling set at the cliff flips the first time that df moves —
# one new source glossing something 'acidic' is enough — and it flips
# silently, withholding a cluster whose recorded answer says it belongs
# together. It also holds only while te_matatiki reaches the concept before
# williams in seed order. A step above a measured cliff is engineering, not
# slack; disagree with it from here if you want to, the numbers are all above.
#
# The criterion is applied to himoemoe alone: the other three recorded answers
# are answers about SEPARATION, and demanding that every fragment of a
# separation answer also ship would assert something no reviewer recorded.
#
# COVERAGE_FLOOR = 0.5 is the promise. No measurement pins it — himoemoe is
# rescued by df, not by coverage, so the fifth criterion is silent here and
# every floor on the grid satisfies every criterion. What pins it is §2 of the
# design, which lists hoatu 'Give' / 'Give forth.' at coverage 0.50 / df 270
# as CORRECT, and cites it as one of the two rows the coverage axis exists to
# rescue ('coverage alone yes, df alone no'); huripari sits on the same 0.50
# in that table. A floor above 0.5 grades both weak, and the thresholds would
# then contradict the document they implement. So 0.5 is the tightest floor
# COMPATIBLE WITH THE SPEC rather than the tightest floor measured — the
# tightest-satisfying-point rule still, with §2 supplying the constraint that
# the corpus does not. It is also the inclusive '>=' in positive_evidence
# doing real work: at 0.5 the boundary case is rescued, and it is the boundary
# case the spec names.
#
# That commitment is pinned by a test rather than by this comment:
# GlossGrading.test_the_specs_own_half_coverage_example_is_ordinary_evidence
# goes red at a floor of 0.6, and the answer to that redness is to revisit §2,
# not to loosen the test.
#
# What the tightening costs, measured and accepted: 4,698 concepts are
# withheld as uncertain, against 3,481 at the provisional 0.5 / 20 — 26.4% of
# the 17,829 multi-source concepts rather than 19.5%. That is the missed-merge
# side of the trade being paid on purpose, and those concepts are not lost
# work: they stay in staging carrying their coverage and distinctiveness per
# evidence row, which is what makes a later re-tune a re-tier plus a rebuild
# of 54 rather than a recomputation (§6). It also keeps the sweep's review
# queue fed, which is the mechanism §6 depends on — a threshold too tight
# censors the very evidence that would show it was too tight, so the queue
# starving is the failure mode to watch, not the queue being large.
COVERAGE_FLOOR = 0.5
DISTINCT_CEILING = 10


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


def positive_evidence(a, b, index):
    """[{kind, detail, weight, coverage, distinctiveness}] linking two senses,
    strongest first.

    coverage and distinctiveness are set on gloss kinds (gloss_overlap,
    gloss_overlap_weak) and None on every other kind — see GlossGrading.

    Cross-source only. Within-source grouping is the seeding step's job, and
    counting it here would let one source's internal repetition masquerade as
    corroboration from another.

    Same headword_search is deliberately absent: it generates candidates, and
    is never itself evidence.

    `index` is a GlossIndex over the corpus the two senses came from. It is
    required rather than optional: a default would silently give two
    different grading rules depending on the call site.
    """
    if a["source_id"] == b["source_id"]:
        return []

    found = []

    if b["entry_id"] in a["cites"] or a["entry_id"] in b["cites"]:
        found.append(("cites_source",
                      f"{a['source_id']} cites the {b['source_id']} entry",
                      None, None))

    shared_ex = a["examples"] & b["examples"]
    if shared_ex:
        found.append(("shared_example",
                      f"both print {sorted(shared_ex)[0][:60]!r}",
                      None, None))

    shared_cit = a["citations"] & b["citations"]
    if shared_cit:
        found.append(("attributed_quote",
                      f"both cite {sorted(shared_cit)[0][:40]!r}",
                      None, None))

    # No shared_cognate_set check: see the comment above EVIDENCE_WEIGHT.
    # cognate_sets is still carried on the sense-view for possible later
    # display use, but it is deliberately not consulted here.

    a_words, b_words = _content_words(a["gloss_en"]), _content_words(b["gloss_en"])
    overlap = a_words & b_words
    if overlap:
        coverage = gloss_coverage(a_words, b_words)
        distinct = index.df(overlap)
        shown = ", ".join(sorted(overlap)[:4])
        if coverage >= COVERAGE_FLOOR or distinct <= DISTINCT_CEILING:
            found.append(("gloss_overlap", f"glosses share {shown}",
                          coverage, distinct))
        else:
            # Weak on both axes: a common word incidental to two long
            # glosses. Its own kind so a reviewer sees WHY it is weak.
            found.append(("gloss_overlap_weak",
                          f"glosses share only {shown}", coverage, distinct))

    return [{"kind": k, "detail": d, "weight": EVIDENCE_WEIGHT[k],
             "coverage": c, "distinctiveness": n}
            for k, d, c, n in found]


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
