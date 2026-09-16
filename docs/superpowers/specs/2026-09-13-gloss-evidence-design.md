# Gloss evidence: coverage and distinctiveness

**Status:** design, 2026-09-13
**Supersedes:** the `GLOSS_OVERLAP_MIN` rule in `scripts/concept_evidence.py`
**Companion to:** `2026-09-12-concept-layer-design.md`, which this amends in one
place (§4, "Evidence kinds") and leaves untouched everywhere else.

---

## 1. The defect

Two senses attach to one concept when their English glosses share content
words. Today the strength of that evidence is `len(overlap)`:

```python
overlap = _content_words(a["gloss_en"]) & _content_words(b["gloss_en"])
if len(overlap) == GLOSS_OVERLAP_MIN:      # exactly 1
    found.append(("gloss_overlap_weak", ...))     # -> uncertain
elif len(overlap) > GLOSS_OVERLAP_MIN:
    found.append(("gloss_overlap", ...))          # -> probable
```

A count cannot see how much of each gloss the overlap represents, so a
one-word gloss can never score above the floor no matter how exactly the two
sources agree. Measured on the corpus, the tier called "the corpus's weakest
signal" contains this:

```
coverage  df(set)   gloss A          gloss B
1.00      2         'supersonic.'  | 'Supersonic'
1.00      27        'Insurance'    | 'insurance.'
1.00      43        'Spoon'        | 'spoon.'
1.00      272       'Three'        | 'three (3)'
```

These are identical glosses, tiered `uncertain`, and dropped at export.

The consequence is structural, not cosmetic. `concept.confidence` is `min`
over members (the concept-layer spec, §4: "A concept never rises above the
weakest of its members"), and `filter_concepts()` drops a concept below
`probable`. So **one spuriously weak attachment demotes an entire grouping**:
10,683 concepts are withheld from the app, and 6,693 individually-`certain`
memberships travel down with them. Every one of those 10,683 is multi-member;
none is uncertain in its own right.

`gloss_overlap_weak` is the only producer of the `uncertain` tier. No source
is seeded uncertain (`SEED_CONFIDENCE` is `probable` for ngata and papakupu,
`certain` otherwise). So this one rule decides everything the export withholds.

### The workaround already in the code

`GLOSS_OVERLAP_MIN` is 1 rather than 2 because of exactly this defect. Its
comment records that `himoemoe`'s six sources gloss one word as `'Acidic'` and
`'Acid, sour.'` — terse strings that share only one content word — and that a
floor of 2 fragmented the cluster into four. The floor was lowered corpus-wide
to rescue it, which admitted the noise alongside:

```
ā    'glosses share only form'        df('form') = 599
ā    'glosses share only indicating'  df('indicating') = 88
```

One global count threshold cannot hold both. That is the problem this design
removes.

---

## 2. The measure

Two quantities per candidate pair, replacing the count.

**Coverage** — Jaccard of the two glosses' content words, `|A∩B| / |A∪B|`.
How much of what the two sources said is the same thing. Catches terse
agreement that a count reads as trivial.

**Distinctiveness** — how many senses in the corpus contain *every* word of
the overlap, computed from an inverted index over `sense.gloss_en`. Catches
rare-but-decisive agreement that a count also reads as trivial. Note this is
the document frequency of the overlap **set**, not of its individual words:
`{throw, away}` occurs in 15 glosses though "throw" alone is in 214 and "away"
in 371.

Evidence is graded on both, as a disjunction:

```
gloss_overlap        if coverage >= COVERAGE_FLOOR or df(set) <= DISTINCT_CEILING
gloss_overlap_weak   otherwise (overlap non-empty but weak on both axes)
no evidence          if the overlap is empty
```

The two kinds and their confidence ratings (`probable` / `uncertain`) survive
unchanged — only the rule that chooses between them is replaced. The two
threshold constants are what §5 sets.

### Why two axes and not one

Neither works alone. Measured against cases with known answers:

| case | coverage | df(set) | truth | coverage alone | df alone |
|---|---|---|---|---|---|
| `hoatu` `'Give'`/`'Give forth.'` | 0.50 | 270 | correct | ✅ | ❌ demoted |
| `ingoa` `'Name'`/`'name.'` | 1.00 | 664 | correct | ✅ | ❌ demoted |
| `huripari` `'fierce wind, tornado'`/`'Fierce wind, hurricane.'` | 0.50 | 2 | correct | ✅ | ✅ |
| `(mate) whakaataata` shares `narcissism` | low | 5 | correct | ❌ demoted | ✅ |
| `(waeine) mahana` shares `fahrenheit` | low | 2 | correct | ❌ demoted | ✅ |
| `ai` `'In the phrase e ai ki...'`/`'In the phrase, or'` | 0.25 | 167 | noise | ✅ rejected | ✅ rejected |

Commonness only dilutes a word when it is incidental to a longer gloss. When
the shared word *is* both glosses, corpus frequency says nothing against it —
"name" appearing in 664 glosses is no argument against "both sources say this
word means exactly: name". That is why the axes are independent and why the
rule is a disjunction.

---

## 3. Validation

All figures measured against `data/staging_dictionary.db` at 95,116 concepts /
175,101 memberships, using the candidate rule `coverage >= 0.5 or df(set) <= 20`
as a stand-in for the thresholds §5 will set properly.

**Recovery.** In a random sample of 400 of the 10,683 uncertain concepts, 317
(79%) clear the bar — extrapolating to roughly 8,466 concepts recovered.

**Measured against the actual rebuild (2026-09-13).** Grouping is
threshold-invariant (§5: every grid point yields the same 95,116 concepts), so
this comparison is exact, not another sample. At the candidate rule used for
this sample (`coverage >= 0.5 or df(set) <= 20`), actual recovery is **7,202**
concepts (67% of the 10,683, not the extrapolated 79%). At the committed
thresholds (`COVERAGE_FLOOR = 0.5`, `DISTINCT_CEILING = 10`), recovery is
**5,985**. The 400-sample estimate over-predicted; it is left above rather than
corrected in place because the discrepancy is itself informative — a
79%-of-400 sample overstating a 67%-of-10,683 population by twelve points is a
sampling-error size worth remembering next time a small sample stands in for a
full rebuild. Either way, the change stands on the measurements in §5 (the
hard constraints and soft scoreboard) and on the re-tuning mechanism in §6,
not on this prediction.

**No over-merging on the clusters with recorded answers.** Counting only pairs
the current rule tiers weak that the candidate rule would promote:

| cluster | recorded answer | promotions | verdict |
|---|---|---|---|
| `hiwi` | eight words plus two loans; ≥6 concepts | **0** | untouched |
| `hia` | must never join `hīa` | **0** | untouched |
| `himoemoe` | one word, six sources | 5, all `'acidic'` (df=7) | the fragmentation, fixed |
| `hoi` | `paekupu:hoi` 'soy' stands alone | 1: `'Variant of heoi.'` vs a gloss of *heoi* | correct |

`himoemoe` is the case that forced the global floor to 1. The candidate rule
fixes it locally, which is why `hiwi` and `hia` see no change.

**The coverage axis does not admit noise.** In a 3,000-key sample, 272 pairs
are promoted by coverage alone on a common word (`df > 100`). Fourteen were
read; all are correct and all have the same shape — both glosses are the bare
word (`ingoa` 'name', `putakari` 'battle', `kianga` 'phrase').

---

## 4. What changes

### `scripts/concept_evidence.py`

- A `GlossIndex` built from `sense.gloss_en`: `build(con)` and a method
  returning the document frequency of a word set. Measured cost on the full
  corpus: **0.6s to build**, 43,441 words, 485,134 postings, ~40 MB;
  **0.5 µs per lookup**, about one second across all 1,152,343 pair
  comparisons in a build. No cache, no persisted table, no staleness — it is
  derived from the same corpus snapshot the build is already reading.
- `positive_evidence(a, b, index)` takes the index **explicitly**. Module-level
  state would make the function untestable without the corpus; passing it in
  lets tests build a three-gloss index inline, which is how the existing
  evidence tests are written. This is a breaking signature change to a function
  with existing callers and tests, and it is deliberate.
- `GLOSS_OVERLAP_MIN` is replaced by two named thresholds. Its comment is
  **superseded, not deleted** — the `himoemoe` and `huripari` findings in it are
  still the evidence, and they are why this design exists.

### `scripts/54_build_concepts.py`

Builds the index once per run and passes it to `positive_evidence`. Nothing
else changes: seeding, blocks, the `min` rollup, and `persist()` are untouched.

### Schema

Two `REAL` columns on `concept_member_evidence`: `coverage`, `distinctiveness`.
Added in `00_init_db.py` plus an `ALTER TABLE` for the existing database. No
backfill — `persist()` already deletes and rebuilds that table wholesale, so
the next build fills them.

### `scripts/60_export_app_db.py`

**No change.** This is a deliberate decision, recorded here because an earlier
draft of this design changed it. Concepts are a pure overlay: all 175,101
senses and 153,440 entries reach the app regardless of concept membership, and
47,614 senses (27%) already belong to no concept. A dropped concept therefore
degrades to separate search results rather than missing data — the normal case
for a quarter of the corpus. Member-level export filtering would additionally
require re-election machinery (6,990 concepts have a `headword_from` pointing
at a member that filtering would delete, and every one of those also has a
surviving member, so the elected headword would be one no member wrote — the
zombie class closed in 9553fae..4ef9a77). Not worth it for a UX polish.

---

## 5. Setting the thresholds

By grid search over (coverage floor, distinctiveness ceiling), scored against a
fixed scoreboard, run against `form_concepts` in memory without persisting so a
grid point costs seconds.

- **Hard constraints — a point failing any is rejected.** The four recorded
  answers in `tests/test_concept_acceptance.py`: `hiwi` ≥6 concepts; `hia`
  never shares a concept with `hīa`; `himoemoe` unifies ≥4 sources;
  `paekupu:hoi` stays single-source.
- **Soft scoreboard.** The four clusters the `GLOSS_OVERLAP_MIN` comment
  records specific behaviour for: `huripari`, `hoatu`, `huatea`, `itinga`.
- **Corpus effects, reported per point.** Tier distribution, total concepts,
  and how many reach the app — so the choice is made with its cost visible.

The chosen point is written into the builder with its reasoning, in the style
of the comment it supersedes.

---

## 6. Re-tuning as judgements accumulate

The sweep's `confirmed`/`rejected` judgements are labelled data: a confirmed
membership says the attachment was right. Because `coverage` and
`distinctiveness` are stored per evidence row, re-fitting is a re-tier plus a
rebuild of 54, not a recomputation, and counterfactuals ("what would a coverage
floor of 0.4 have done to the attachments judged so far?") are a query.

A tuning script reports, for a candidate pair of thresholds, how cleanly it
separates confirmed from rejected, and the shipping delta.

**The censoring hazard, which constrains the design.** Thresholds can only ever
be re-fit against attachments the builder actually made. A threshold that is
too tight excludes pairs that then never reach the sweep, are never judged, and
never produce the evidence that it was too tight. The data is censored by the
parameter being tuned, and it censors in the direction that makes tightening
look free.

Therefore: **weak attachments keep forming in staging.** The weak tier is not
removed and pairs are not refused. Staging is the laboratory; the export is
what protects users. An earlier draft of this design proposed refusing weak
pairs outright, which would have made the corpus unable to teach anything about
its own thresholds.

### Notes for whoever re-tunes these

Written down because they were expensive to learn and live nowhere else.

**The grid is degenerate on grouping.** Both gloss kinds are evidence, so a pair
attaches either way: no threshold on any grid changes which senses share a
concept. Verified by hashing the member-key partition across the grid — identical
at every point. Two consequences. The recorded calibration answers in
`tests/test_concept_acceptance.py` are all about grouping, so **they cannot
discriminate between threshold points at all** — a grid search scored on them
alone returns whatever corner its scoring function points at. And no re-tune can
over-merge; it can only withhold.

**Cap every axis where no criterion binds, or the search returns your grid's
edge.** This is the one that cost the most. The original rule ("the satisfying
point that ships the most") is monotone in both axes, so it just picked the
loosest corner. Replacing it with "the tightest satisfying point" reproduced the
same pathology mirrored — the floor ran straight to 0.7, the tight edge, for no
reason but that the grid stopped there. Only a criterion that actually binds
pins an axis. Today `DISTINCT_CEILING` is pinned by measurement and
`COVERAGE_FLOOR` is pinned by §2's table via `SPEC_COVERAGE_CAP`. Add an axis,
or widen the grid, and you need a new cap or you will get its edge back.

**The shipping criterion, and its limits.** `DISTINCT_CEILING` is pinned by
requiring that a cluster whose recorded answer is *these belong together* must
reach users, not merely group. Only `himoemoe` carries such an answer; `hiwi`,
`hia` and `hoi` record **separation**, and "these are eight different words"
says nothing about whether each of the eight is well enough evidenced to
display. Do not extend the criterion to them without a recorded answer to base
it on.

**That pin is thin.** The whole ceiling constraint is one membership:
`te_aka` × `te_matatiki` on `'acidic'`, in exactly 7 glosses corpus-wide. The
ceiling is 10 — three steps of deliberate clearance, costing 615 concepts,
because one new source glossing something `'acidic'` moves it. The measured
cliff is between 6 and 7. `test_himoemoe_actually_reaches_users_not_just_the_corpus`
exists because nothing else in the suite would notice if drift consumed the
margin; with it in place, a tighter ceiling becomes safe to take.

**Two fixtures are sized to today's constants.** In
`tests/test_concept_evidence.py`, `test_identical_terse_glosses_are_ordinary_evidence`
hardcodes a corpus giving df 21, so it goes red at any `DISTINCT_CEILING` >= 21
(grid points 40 and 80). The fix is one line — build the corpus as
`["a spoon of sorts"] * (DISTINCT_CEILING + 10)`, the way
`test_coverage_at_the_floor_is_rescued_even_when_common` already does. And that
boundary test derives its fixture from `Fraction(COVERAGE_FLOOR).limit_denominator(20)`,
exact for every 0.05 step from 0.3 to 0.75 and **loudly failing** for a floor
needing a larger denominator (0.47, say) — rebuild that fixture, never weaken
the assertion.

**The separation half of the tuning script does not exist yet.** The script
reports the shipping delta but not how cleanly a candidate pair separates
`confirmed` from `rejected`, because at the time of writing nothing was judged.
`_max_sources(shipping=True)` also approximates `filter_concepts()` as
`confidence != 'uncertain'`, which is exact only while no judgements exist; its
docstring names itself the first thing to fix. Both are work for the first
re-tune, not oversights.

**The rebuild-ordering hazard.** `persist()` in `54_build_concepts.py` deletes
all evidence rows unconditionally and re-inserts none for a rejected member —
by design, a rejected membership earns no evidence rows. So a rebuild of 54
destroys the stored `coverage`/`distinctiveness` of every `rejected`
membership along with everything else, leaving only the judgement behind. Any
threshold re-fit that needs the rejected rows' measurements must read them
**before** running 54 again, not after: "a re-tier plus a rebuild of 54" is
only true if the analysis runs first.

---

## 7. What this does not fix

- **Ambiguous single-word glosses.** Two sources glossing different Māori words
  as just `'light'` (illumination vs. not-heavy) score coverage 1.00 and merge
  wrongly. POS and homograph-numbering blocks catch some; the sweep is the
  backstop. The rule is not airtight and this design does not claim it is.
- **Grammatical metalanguage.** Particle senses glossed as descriptions of
  function ("indicating", "denoting", "used to form") attach to each other on
  shared metalanguage. Distinctiveness does not help — `{action, place, time,
  where}` occurs in only 4 glosses, so it scores as *specific*. Treating
  grammatical glosses as a distinct kind of text was considered and deferred;
  it is a separate design.
- **Source-structure limits.** Williams entries 1251/1252 each bundle several
  of `hiwi`'s eight words under one entry number. No gloss rule reaches this.
- **Non-English glosses.** `gloss_mi` is not consulted, as today.

---

## 8. Testing

- **Unit,** against inline three-gloss indexes: coverage and distinctiveness
  computed correctly; the disjunction grading each of the six cases in §2's
  table to the kind the table says; an empty overlap producing no evidence.
- **Acceptance,** against the real database: the four recorded answers in
  `tests/test_concept_acceptance.py` continue to hold — they are the hard
  constraints of §5 and must not be weakened to accommodate this change.
- **Regression:** the concept count recovered is asserted with a floor, not an
  equality, so ordinary drift is quiet.
- **Cost:** index build time asserted under a ceiling, so an accidental rebuild
  inside the pair loop is loud rather than merely slow.

---

## 9. Out of scope

Deliberately not in this design, each already recorded in the ledger:

- `attributed_quote` is inert (1 row in 175,101) — it compares full citation
  strings where the concept-layer spec described a pointer.
- Evidence pooling produces 11,149 duplicate `(member, kind, detail)` rows.
- `counts["concepts"]` includes all-rejected concepts that ship nothing.
- The `min` rollup itself. It is doing what the concept-layer spec says, and
  once attachments stop being spuriously weak it stops withholding anything
  it should not.
