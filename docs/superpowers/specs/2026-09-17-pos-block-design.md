# The part-of-speech block: which categories are a word boundary

**Status:** design, 2026-09-17
**Amends:** `blocks()` in `scripts/concept_evidence.py` — the POS clause only
**Companion to:** `2026-09-12-concept-layer-design.md` §"Negative evidence
blocks a membership", which this narrows in one place and leaves otherwise intact.

---

## 1. The defect

`blocks()` refuses to let two senses share a concept when each source gives a
single, different part of speech:

```python
atoms_a, atoms_b = _pos_atoms(a["pos"]), _pos_atoms(b["pos"])
if atoms_a and atoms_b and len(atoms_a) == 1 and len(atoms_b) == 1:
    base_a = _extract_base(next(iter(atoms_a)))
    base_b = _extract_base(next(iter(atoms_b)))
    if base_a and base_b and base_a != base_b:
        reasons.append(f"incompatible part of speech: …")
```

The rule already carries the right principle in its own comment — *"A source
listing several parts of speech is describing a word that functions several
ways; that is not a claim excluding another source's single tag."* It applies
that principle only when one side is multi-valued. When both sides are single,
it treats two partial views as a contradiction.

For Māori that is wrong for the open content categories. Found on the
`kahurangi` cluster: te Aka tags `kahurangi` **Modifier** ("be blue,
precious"), Papakupu tags it **Noun** ("blue, sky-blue"). Neither is claiming
exclusivity. The block fired, and because the anti-chaining rule refuses a
seed that blocks against *any* member, te Aka's entire seven-sense entry was
excluded from the concept holding the other four sources.

### The corpus contradicts the rule in its own tagging

The decisive evidence is not linguistic argument, it is what the sources do.
Where one source tags one entry with several parts of speech, it is stating
those are the same word. Counting those co-tags across 23,227 entries:

| co-tagged on one entry | entries |
|---|---|
| noun + verb | 15,957 |
| noun + stative | 12,843 |
| stative + verb | 11,311 |
| modifier + noun | 2,656 |
| modifier + verb | 2,203 |
| adverb + stative | 523 |
| adverb + noun | 519 |
| adverb + verb | 505 |
| modifier + stative | 85 |
| adverb + modifier | 46 |
| **noun + proper noun** | **30** |

Set that against what the block actually rejects, measured over a random
4,000 multi-source headword keys (180,316 cross-source pairs):

| blocked pair | pairs | corpus says |
|---|---|---|
| Noun vs Verb | 3,098 | 15,957 entries are both |
| Modifier vs Noun | 3,060 | 2,656 entries are both |
| Noun vs Verb (transitive) | 2,433 | both, as above |
| Noun vs Proper noun (person) | 1,821 | only 30 entries are both |
| Noun vs Verb (intransitive) | 1,814 | both, as above |
| Noun vs Stative | 798 | 12,843 entries are both |
| Modifier vs Verb | 537 | 2,203 entries are both |

POS blocks fire on **18,897 of 180,316 cross-source pairs — 10.5%**. The
open-category pairs above are the bulk of them, and the corpus states those
are one word tens of thousands of times over. `noun + proper noun`, by
contrast, is co-tagged 30 times: that block is doing real work, and `Hene`
the given name beside `hene` the body part is why.

---

## 2. The rule

Two changes to the POS clause. Nothing else in `blocks()` moves.

**Open content categories never block each other.**

```
OPEN_POS = {noun, verb, stative, modifier, adverb}
```

These are the categories Māori content words move between freely, and which
the sources co-tag on one entry 46,000 times over. A difference within this
set is two partial descriptions, not a word boundary.

**A provenance tag never blocks at all.**

```
PROVENANCE_POS = {loan word}
```

`loan word` is not a syntactic category — it records where a word came from.
The corpus co-tags it with noun (2,335), proper noun (570), locative (452),
verb (284), modifier (157) and stative (25), i.e. with whatever the word
grammatically is. Comparing it against a category is a type error, and it
should be excluded from the comparison rather than given a place in
`OPEN_POS`.

This clause is not co-equal with `OPEN_POS` in effect, only in the code —
it is worth keeping on principle (comparing a provenance tag against a
category is a type error regardless of volume) but it barely moves the
corpus. Isolated (run with `OPEN_POS` emptied), `PROVENANCE_POS` alone moves
the count from 95,051 to 95,045 concepts, +5 multi-source: `loan word`
blocks only when it is a source's *sole* tag on the entry, which is true on
126 entries corpus-wide. Kept for correctness, not for weight.

Every other base pair keeps blocking, on the existing both-sides-single-valued
condition.

### What this does

Simulated over the same 4,000-key sample:

```
POS blocks now        18,897
under the new rule     5,894
released              13,003   (69%)
```

The blocks it keeps are the ones with no co-tagging behind them:

| kept | pairs |
|---|---|
| Noun vs Proper noun (person) | 1,821 |
| Noun vs Universal | 509 |
| Noun vs Proper noun (place) | 480 |
| Noun vs Proper noun | 359 |
| Noun vs Particle | 220 |
| Locative vs Noun | 202 |

---

## 3. The risk, stated plainly

Negative evidence is called "the safety mechanism of the whole design" in the
concept-layer spec, and this loosens it by 69% of its POS component. The
failure it exists to prevent is real and has happened: `shared_cognate_set`
once merged ten distinct `hoi` words into one concept, and the anti-chaining
rule — a block against **any** member rules the whole concept out — is what
stops a third source compatible with each of two separated words quietly
joining them.

Releasing a block therefore does not merely permit one pair; it permits a
chain. The mitigation is that POS was never the only guard: a source's own
homograph numbering still blocks (`williams` files Hiwi as 1250/1251/1252),
macron disagreement still blocks (`hia` vs `hīa`), and positive evidence is
still required — releasing a block does not create a merge, it only stops
forbidding one.

**This is why §5 makes the recorded calibration answers a hard gate rather
than a report.** `hiwi` must stay ≥6 concepts and `hia` must never join `hīa`
after the change, or the change is wrong.

---

## 4. What this does not change

- The both-sides-single-valued condition. A multi-valued tag still never
  blocks, for the reason the existing comment gives.
- Every other clause of `blocks()`: same-source lexeme separation, macron
  disagreement.
- Positive evidence, thresholds, election, the export filter. A released
  block produces a merge only where evidence already justified one.
- `part_of_speech_en` normalisation. `_extract_base` and `_pos_atoms` are
  unchanged; this design only decides which bases may differ harmlessly.

---

## 5. Setting and validating

**Hard gate — the recorded calibration answers.** All four must hold after
the rebuild, and they are the reason to reject the change rather than tune it:

- `hiwi` ≥ 6 concepts (eight words plus two loans)
- `hia` never shares a concept with `hīa`
- `himoemoe` unifies ≥ 4 sources
- `paekupu:hoi` 'soy' stays single-source

**Second gate — chaining.** `hoi` is the cluster that proved chaining is
real: `shared_cognate_set` once merged ten distinct `hoi` words into one
concept. Baseline measured 2026-09-17, before any change: **`hoi` holds 7
concepts**, and the corpus holds **18,127 multi-source concepts**. `hoi` must
not collapse below 7.

**Reported, not gating:** total concepts, tier distribution, how many
concepts reach the app, and the count of concepts spanning more than one
source. A large rise in multi-source concepts is the intended effect; a
large *fall* in total concepts means merging is chaining and the change
should be reconsidered.

### Measured outcome (2026-09-17, after the rebuild)

| | before | after | |
|---|---|---|---|
| concepts | 95,051 | 91,684 | −3,367 |
| — certain | 67,236 | 63,206 | −4,030 |
| — probable | 23,709 | 24,465 | +756 |
| — uncertain | 4,106 | 4,013 | −93 |
| multi-source concepts | 18,127 | 18,794 | **+667** |
| app concepts | 90,946 | 87,673 | −3,273 |
| `hoi` | 7 | **7** | held |

**All four recorded answers hold**, with headroom: `hiwi` 8 concepts against a
floor of 6, `hia` still apart from `hīa`, `himoemoe` still unifying ≥4 sources,
`paekupu:hoi` still single-source. All 18 sweep judgements survived.

**The reconsider-signal fired and was judged benign. The reasoning, so a later
reader can disagree with it.** This section said a large fall in total concepts
means merging is chaining. Total fell by 3,367 while multi-source rose by only
667, which is exactly the shape that would worry: if merges were clean pairings
the two numbers would be close.

They are not close because most merges are not pairings. Single-source concepts
fell by 4,034; about 1,334 of those paired off into the 667 new multi-source
concepts, and the remaining ~2,700 were absorbed into concepts that were
*already* multi-source — which lowers the total without moving the multi-source
count at all. That is the intended effect (a te Aka `Modifier` entry joining a
concept that already held the `Noun` reading), not accretion.

Three checks support that reading over the chaining one:

- **No runaway concept, checked against where each one started.** The
  largest concepts did grow materially — an absolute with no before-figure is
  a description, not a check:

  | concept | before | after | |
  |---|---|---|---|
  | `tohu` | 75 | 88 | |
  | `mate` | 41 | 67 | +63% |
  | `rere` | 36 | 65 | +80% |
  | `pai` | 41 | 54 | |
  | `ora` | 23 | 35 | |
  | `hanga` | 29 | 41 | |
  | `mahi` | 59 | 71 | |

  `tohu`'s 88 members across 7 sources are one genuinely polysemous word —
  sign/mark/token, to preserve/spare, to instruct/advise. Decomposing the two
  largest movers, `rere` and `mate`, both merges are correct: the new members
  are the same word under another source's tag, not a chain. The failure mode
  this scale of growth does produce is not a blob, it is the `houhere` case in
  §6 — a source's own bad grouping admitted whole once its block releases,
  the amplification §3 names, playing out at the scale these numbers show.
  The source distribution stays smooth: 72,890 concepts hold one source,
  11,825 two, 4,711 three, tapering to 7 at eight sources.
- **`hoi` is unaffected by this change, which is worth being honest about.**
  Run under both the old and new rules, the `hoi` partition is identical,
  concept for concept — same 7 concepts, same lexeme membership. Its
  separations are held by Williams' own homograph numbering, not by the POS
  clause this design touches, so holding at 7 is not evidence about chaining
  *from this change* — it could not have moved either way. `hoi` earns its
  place as `test_hoi_does_not_chain_into_fewer_concepts`
  (`tests/test_concept_acceptance.py`) for a different reason: it is the
  cluster on which `shared_cognate_set` once actually chained ten distinct
  words together, so it stays as a guard against *future* drift in `blocks()`
  or the seeding step, not as a measurement of *this* one.
- **The certain→probable shift is arithmetic, not decay.** A concept absorbing
  a `probable` member takes `min` over its members, so +756 probable against
  −4,030 certain is consistent with ~3,367 certain concepts merging away and
  ~756 being demoted by what they absorbed.

**The cost this measures, and the honest number for it.** §3 names the risk
directly: releasing a block "does not merely permit one pair; it permits a
chain." The quantity that measures that risk is the transitive-join rate —
cross-seed pairs that end up sharing a concept with no direct positive
evidence between them, resting purely on both having attached to a shared
third member — and it was absent from this section entirely. Measured over
every concept:

```
OLD: 18,127 multi-seed concepts, 35,966 cross-seed pairs, 2,482 without direct evidence (6.90%), 1,516 concepts affected
NEW: 18,794 multi-seed concepts, 44,109 cross-seed pairs, 3,803 without direct evidence (8.62%), 2,204 concepts affected
```

84% of the newly-created cross-seed adjacencies are directly evidenced; the
undirected share rose from 6.90% to 8.62%. Reading a sample of 14 transitive
joins by hand: 11 are right (`kiato` compact/density, `pūmau` invariant,
`pupuri` hold/save, `pūkenga` scholar/lecturer, `anga` shell/structure) and 3
are doubtful (`hīrea` whiff vs obscure, `mataara` alert vs witness, `putu`
foot-length vs heap). A later reader pulling a fresh sample has 8.62% to
compare against, rather than nothing.

**Membership in `OPEN_POS` is set by co-tagging, not by taste.** A base
belongs if the sources themselves co-tag it with another member on one
entry, at a volume that cannot be transcription noise. `adverb` qualifies on
523/519/505; `locative` does not — it co-tags with noun 58 times and
modifier 39, and is left blocking. That threshold is a judgement, and it is
recorded here so a later reader can disagree with the line rather than guess
where it was. It is argued per base pair, but membership is transitively
closed and applies per concept: `adverb`+`modifier` releases at 46 co-tags
while `locative`+`noun` still blocks at 58 — a kept pair outranking a
released one — because the line is drawn on each base's overall behaviour,
not on the volume of any one pairing within `OPEN_POS`.

---

## 6. What this does not fix

- **`unsure` as a part of speech.** 140 blocked pairs in the sample pit a
  real category against a literal `unsure` tag. Blocking on an explicit
  admission of not knowing is its own defect, and a separate one.
- **Proper-noun subdivisions.** `Proper noun (person)` and `Proper noun
  (place)` reduce to the same base, so they never blocked each other and
  still do not. Whether they should is untouched here.
- **The anti-chaining rule itself.** Refusing a whole seed because one member
  blocks is a strong rule that this design leaves exactly as it is; it is
  what makes a released block matter, and it deserves its own examination.
- **A confirmation can carry later arrivals it never judged.**
  `54_build_concepts.py` marks a whole concept `confirmed` if *any* member is
  confirmed, and `60_export_app_db.py` ships a concept when
  `status = 'confirmed' OR confidence IN (certain, probable)`. So a human
  confirmation made about one grouping can carry a later arrival into the app
  on its back. Concept 1332172 (`hikunga`) is `confirmed` **and**
  `uncertain`: it holds two human-confirmed te Aka senses, and under this
  branch williams `1114701` newly joined it — that member now reaches the app
  riding a confirmation that was never made about it. The machinery is
  pre-existing (both scripts predate this branch); this branch is what made
  it fire. Checked against all eight confirmed concepts and all 18 judged
  rows in the sweep: `hikunga` is the only one whose partition changed, and
  that merge is itself correct. No user-visible harm today — recorded here as
  a limit, not fixed.
- **A source's own bad grouping, exposed rather than caused.** He Pātaka Kupu
  files `word_id=1073` across five entries — 'industrious' (source_entry_id
  2369) and four lacebark-tree entries (810/820/826/832) — and the design
  trusts a source's own grouping completely. Te Aka 41352 tags `houhere`
  `Modifier`; HPK's four lacebark entries tag it `Noun`. Under the old rule
  that difference blocked, so te Aka 41352 and williams 1466 ('Industrious')
  formed their own concept, kept apart from HPK's five. `modifier`/`noun` is
  in `OPEN_POS` under this rule, so it no longer blocks and the two join
  HPK's blob instead — confirmed against the live corpus: `houhere`
  'lacebark' now appears in two different concepts. Root cause is HPK's
  `word_id`, not `blocks()` — but it is the clearest live example of the
  amplification §3 describes: releasing a block admits a *whole seed*,
  including senses that are semantically remote from the one that earned the
  release.

---

## 7. Testing

- **Unit, against `blocks()` directly:** each `OPEN_POS` pair returns no POS
  reason; `noun` vs `proper noun` still does; `loan word` against every
  category returns none; a multi-valued tag still never blocks; the
  same-source and macron clauses are untouched by any of it.
- **The `kahurangi` case, named:** te Aka `Modifier` and Papakupu `Noun` on
  one headword must not block. It is the case that found this and it should
  fail loudly if the rule regresses.
- **Acceptance, against the real database:** the four recorded answers of §5,
  unchanged and not weakened. If one fails, the rule is wrong.
- **A chaining guard:** `hoi` keeps its concept count. Written as a floor so
  ordinary drift is quiet and a collapse is loud.
