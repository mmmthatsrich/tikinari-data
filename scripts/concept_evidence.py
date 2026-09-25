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


def lexeme_key(source_id, source_entry_id, headword, locator):
    """Which lexeme a sense belongs to WITHIN its own source.

    He Pātaka Kupu scatters one lemma over several rows and names the grouping
    in entry.locator ('word_id=930'). Ngata and Papakupu split by headword.
    Williams and Te Aka give one entry per word.

    The headword-seeded sources group on the headword AS WRITTEN, never on
    `headword_search`. That column strips macrons, and a macron is a phoneme
    here, not an accent: seeding on it merged ngata's 'manawa' (heart) with
    'mānawa' (mangrove), and papakupu's 'koti' (coat) with 'kōti' (court) —
    wrong merges inside a single source, which no cross-source rule can see
    or undo. It also let one misspelled row veto its whole seed: seven ngata
    rows spelling 'āhuaatua' were isolated from three other sources by an
    eighth row missing the macron, because a block against any member refuses
    the seed. Case is folded, since capitalisation is typography rather than
    a word boundary.
    """
    if source_id == "hepatakakupu":
        m = _WORD_ID.search(locator or "")
        if m:
            return (source_id, "word", m.group(1))
    if source_id in _GROUP_BY_HEADWORD:
        return (source_id, "hw", (headword or "").strip().lower())
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
#
# 'shared_cognate_set_unique' is the narrow form that survived measurement
# (D43). The objection above is about AMBIGUITY, not about etymology: a
# cognate set reaches 5.3 distinct words on average from a stranded
# hepatakakupu sense, and ten or more for 2,391 of them, which is exactly how
# hoi collapsed. It is not an objection to a set that reaches ONE word from
# each side. See cognate_unique_pairs.
EVIDENCE_WEIGHT = {
    "cites_source":       1.0,   # Te Matatiki citing 'himoemoe W.50'
    "shared_example":     0.9,   # two sources printing the same sentence
    "attributed_quote":   0.7,   # Te Aka citing 'W 1971:54'
    "shared_cognate_set_unique": 0.6,
    "gloss_overlap":      0.5,
    "gloss_overlap_weak": 0.3,
}

EVIDENCE_CONFIDENCE = {
    "cites_source":       "certain",
    "shared_example":     "certain",
    "attributed_quote":   "probable",
    # Probable, never certain. The cognate link is stated by the etymology
    # and the uniqueness is proved against the bucket, but no source says
    # these two entries are one word — that remains inference.
    "shared_cognate_set_unique": "probable",
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


# Macrons are folded BEFORE tokenising, never stripped after. `[a-z]+` stops
# at a macron, so a Māori word quoted inside an English gloss used to come
# apart: 'pōuri' became 'uri', 'kūmara' became 'mara', 'tī kōuka' became
# 'uka'. That is worse than dropping the word — it invents a different one —
# and it stopped the macronised and bare spellings of one word matching each
# other, which is how te Aka's "used with pōuri" failed to meet Williams'
# "used with pouri." on the wetangotango cluster. 3,689 English glosses, 2.5%
# of them, contain a macronised word.
#
# Folding is right HERE and wrong in a headword, where a macron is a phoneme
# and 'manawa' is not 'mānawa' (see lexeme_key). Inside an English gloss the
# macron is a citation of a Māori word, and both spellings of it mean the
# same thing.
_GLOSS_MACRONS = str.maketrans("āēīōūĀĒĪŌŪ", "aeiouaeiou")


def _content_words(text):
    folded = (text or "").translate(_GLOSS_MACRONS).lower()
    return frozenset(w for w in re.findall(r"[a-z]+", folded)
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


def positive_evidence(a, b, index, unique_cognates=frozenset()):
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

    `unique_cognates` is cognate_unique_pairs() over this pair's headword
    bucket. It DOES default, and to the empty set, because uniqueness cannot
    be decided from a pair alone: a caller holding only two senses has no
    bucket to prove it against, and the honest answer there is that the axis
    does not fire.
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

    # A shared cognate set counts ONLY where it named one word from each
    # side; cognate_unique_pairs decided that against the whole bucket, and
    # the bare set is still not evidence. See the comment above
    # EVIDENCE_WEIGHT.
    if frozenset({a["member_key"], b["member_key"]}) in unique_cognates:
        shared_cog = sorted(a["cognate_sets"] & b["cognate_sets"])
        found.append(("shared_cognate_set_unique",
                      f"one cognate set, naming one word each way: "
                      f"{', '.join(str(c) for c in shared_cog[:3])}",
                      None, None))

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


# Māori content words move between these roles freely, and the sources state
# it themselves: where one source tags ONE entry with several parts of speech
# it is declaring those the same word, and it does so for noun+verb on 15,957
# entries, noun+stative on 12,843, stative+verb on 11,311, modifier+noun on
# 2,656, modifier+verb on 2,203, adverb+stative on 523. A difference inside
# this set is two partial descriptions of one word, not a boundary between
# two words.
#
# The line is drawn on those co-tagging counts, not on taste. 'adverb' is in
# on 523/519/505; 'locative' is out, co-tagged with noun 58 times and modifier
# 39, and keeps blocking. 'proper noun' is emphatically out: noun+proper noun
# is co-tagged 30 times corpus-wide, which is why 'Hene' the given name stays
# apart from 'hene' the body part.
OPEN_POS = frozenset({"noun", "verb", "stative", "modifier", "adverb"})

# Not a syntactic category at all — it records where a word came from. The
# corpus co-tags it with noun (2,335), proper noun (570), locative (452),
# verb (284), modifier (157) and stative (25): with whatever the word
# grammatically IS. Comparing it against a category is a type error, so it
# is excluded from the comparison rather than given a place in OPEN_POS.
PROVENANCE_POS = frozenset({"loan word"})

# One source of truth: `seed_blocks` recognises this reason to suppress it, so
# the wording lives here rather than being matched twice.
_POS_REASON = "incompatible part of speech"


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

    # POS block fires only when BOTH sides are single-valued and their bases
    # differ. A source listing several parts of speech is describing a word
    # that functions several ways; that is not a claim excluding another
    # source's single tag.
    #
    # Nor is a single tag, when both sit inside OPEN_POS: te Aka calling
    # kahurangi a Modifier and Papakupu calling it a Noun are two partial
    # views, and the corpus co-tags those categories on one entry tens of
    # thousands of times. See the gloss of OPEN_POS above and
    # docs/superpowers/specs/2026-09-17-pos-block-design.md.
    atoms_a, atoms_b = _pos_atoms(a["pos"]), _pos_atoms(b["pos"])
    if atoms_a and atoms_b and len(atoms_a) == 1 and len(atoms_b) == 1:
        base_a = _extract_base(next(iter(atoms_a)))
        base_b = _extract_base(next(iter(atoms_b)))
        interchangeable = base_a in OPEN_POS and base_b in OPEN_POS
        provenance = base_a in PROVENANCE_POS or base_b in PROVENANCE_POS
        if (base_a and base_b and base_a != base_b
                and not interchangeable and not provenance):
            reasons.append(
                f"{_POS_REASON}: {a['pos']!r} vs {b['pos']!r}")

    return reasons


def seed_blocks(seed, existing):
    """Reasons a whole seed may not join a concept (D44).

    `blocks()` is the sense-to-sense rule and stays exactly that. This is the
    seed-to-concept rule, and it differs in one respect: the part-of-speech
    block reads the seed's whole inventory rather than one sense's tag.

    That is the rule `blocks()` already states — it fires only when BOTH sides
    are single-valued, because "a source listing several parts of speech is
    describing a word that functions several ways; that is not a claim
    excluding another source's single tag". `_pos_atoms` splits on `[,/|]`, so
    one sense tagged 'Noun, Verb' is already exempt. What could not be seen is
    the same claim spread over sense rows instead of commas: te_aka files
    `auahitūroa` as sense 1 `Proper noun (person)`, the personified being, and
    sense 2 `Noun`, the comet, and sense 1's tag was keeping the whole entry
    out of every concept sense 2 belonged in.

    The asymmetry is deliberate and load-bearing. A seed is a lexeme, a
    grouping the source STATED, so the union of its senses' tags is that
    source's own claim about the word. A concept is a grouping this pipeline
    INFERRED, so its members' tags are not one word's inventory and get no
    such treatment.

    Only the part-of-speech reason is ever suppressed. A source filing two
    entries apart is a claim about WORDS — it is the anti-chaining rule's own
    instrument — and a macron disagreement is a claim about a spelling.
    Neither is answered by an inventory of parts of speech, and measurement
    bears this out: of the 148 attachments this unblocks, every one was the
    part-of-speech block and none involved either of the others.
    """
    inventory = set()
    for s in seed:
        inventory |= _pos_atoms(s["pos"])
    stated_several_ways = len(inventory) > 1

    reasons = []
    for s in seed:
        for e in existing:
            for r in blocks(s, e):
                if stated_several_ways and r.startswith(_POS_REASON):
                    continue
                reasons.append(r)
    return reasons


def cognate_unique_pairs(views):
    """Pairs in one headword bucket whose shared cognate set names one word.

    A cognate set links HEADWORDS. It carries no sense discrimination and it
    was matched on spelling, so on its own it says only what the headword key
    already said — which is why there is no plain 'shared_cognate_set' kind
    (see the comment above EVIDENCE_WEIGHT, and the `hoi` canary in
    tests/test_concept_acceptance.py, where it merged ten distinct words).

    Measured over the corpus, a stranded He Pātaka Kupu sense reaches 5.3
    distinct words on average through its cognate sets and ten or more in
    2,391 cases. But 916 reach exactly ONE, and there the ambiguity that
    sank `hoi` is absent: the set names a single word and no other.

    So this applies the discipline D32 and D34 already use — act only where
    exactly one candidate survives — and requires it from BOTH sides. `a`'s
    unblocked cognate-sharing candidates must be one lexeme, `b`'s must be
    one lexeme, and they must therefore name each other. Mutual uniqueness
    costs 1,057 of the 5,737 one-sided pairs and buys a symmetric claim,
    which matters because positive_evidence is scored in both directions.

    Blocked candidates are not candidates. A macron disagreement or an
    incompatible part of speech already rules a pair out, so letting one
    veto the bucket's uniqueness would let a single misspelling refuse every
    merge around it.

    Yields 4,680 pairs corpus-wide, and moves He Pātaka Kupu from 5.4% of
    memberships joining a cross-source concept to 8.7%.

    It names the D43 proof case — hepatakakupu:4287, a comet described in
    Māori, and te_aka:516#2 'Comet' — but naming it is not enough to merge
    it: te_aka files sense 1 of that entry as a proper noun, a seed is a
    whole lexeme, and form_concepts refuses a concept any of whose members
    blocks. That remaining cause is pinned in
    tests/test_concept_cognate_unique.py and is not this axis's to override.

    Takes one headword_search bucket — the same list form_concepts is given —
    because uniqueness is a property of the candidate set, not of a pair.
    """
    candidates = {}
    for a in views:
        survivors = [b for b in views
                     if b["source_id"] != a["source_id"]
                     and a["cognate_sets"] & b["cognate_sets"]
                     and not blocks(a, b)]
        if survivors and len({b["lexeme"] for b in survivors}) == 1:
            candidates[a["member_key"]] = survivors

    return {frozenset({key, b["member_key"]})
            for key, survivors in candidates.items()
            for b in survivors
            if b["member_key"] in candidates}


def confidence_for(evidence, blocked):
    """Strongest positive kind present, downgraded to uncertain by any block."""
    if blocked or not evidence:
        return "uncertain"
    best = max(_CONFIDENCE_ORDER.index(EVIDENCE_CONFIDENCE[e["kind"]])
               for e in evidence)
    return _CONFIDENCE_ORDER[best]
