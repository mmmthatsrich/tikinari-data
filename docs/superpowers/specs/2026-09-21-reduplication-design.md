# Reduplication — design

**Date:** 2026-09-21
**Status:** approved, ready for an implementation plan
**Supersedes:** §6 of `2026-09-19-irregular-whole-forms-design.md`, which
deferred reduplication and sized it at 873 candidates. That framing was
wrong in its conclusion, and §2 below records why.

## 1. What this does

Harvests the reduplications papakupu **states**, and corrects 61 derivation
rows whose affix is wrong.

It does not detect reduplication from spelling. That is the central decision
and §2 is the evidence for it.

## 2. Why inference was rejected

The deferral in the previous spec assumed reduplication was a large
harvestable population — 873 headwords that are a stem written twice. The
number is roughly right (871 by folded key, 860 by exact spelling; the
earlier 873 came from a slightly different normalisation). The conclusion
drawn from it was wrong: those candidates are not harvestable at all.

Of 871 full-reduplication candidates, 272 are already in `derivation` from
Williams's own layout. The remaining 599 would be inferred from spelling
alone. A sample of twelve, checked against the first gloss of each word:

| candidate | gloss | base | gloss |
|---|---|---|---|
| `mukumuku` | to wipe, rub, smear | `muku` | to wipe, rub, smear |
| `hemihemi` | back of the head | `hemi` | **James, Jim** |
| `hopihopi` | to soap up, lather | `hopi` | native oven |
| `kurekure` | a species of earthworm | `kure` | cry like a seagull |
| `tokatoka` | a venereal disease | `toka` | overflow |
| `hanihani` | to speak ill of | `hani` | a carved wooden weapon |

One of the twelve shows a relationship. The corpus holds many short words,
so an exact doubling frequently joins unrelated homographs — `hemi` is a
transliterated personal name. (The probe reads only each word's first sense,
so it understates precision; it does not rescue the method.)

Partial reduplication is worse. An initial-syllable rule yields 817
candidates whose precision is lower still, and **4,005 vowel-initial bases
are structurally undetectable** because the copied syllable folds away —
`a` + `ahu` is `aahu`, which normalises back to `ahu`. Any corpus-wide count
built this way would be both wrong and silently skewed toward
consonant-initial words.

So the honest count of reduplications in this corpus is *the ones the
sources state*, exactly as `form_type = 'passive'` means the passives the
sources recorded. Nothing is inferred here.

## 3. What papakupu states

31 papakupu definitions mention reduplication, in two shapes.

**Forward** — the entry is the reduplication and names its base, sometimes
with a sense number:

    ariariā   "...(Reduplicated form of ariā)."
    ekeeke    "sexual movement (Reduplicated form of eke [2])"

**Inverse** — the entry is the base and names its reduplication in prose:

    hoko      "In the reduplicated forms hohoko and hokohoko, the focus
               is on the process..."
    roa       "...the reduplicated form roroa is often used – see
               separate entry"

19 forward and 8 inverse statements survive, 24 distinct pairs after
deduplication (`nanao` and `naonao` are stated from both ends; the forward
statement wins, because only it carries the base's sense number).

Nineteen of the twenty forward statements sit inside a parenthetical —
`'(Reduplicated form of eke [2])'` — and one does not: *wareware* reads
`'– reduplicated form of ware [2].)'`. A first draft of the parser required
the opening parenthesis and silently dropped it. The pattern must not
anchor on the bracket; the containment filter, not the punctuation, is what
rejects a statement about another word.

## 4. The spelling rule is a filter, never a generator

The source has already asserted the derivation. The spelling rule exists
only to reject a statement that turns out to be about a different word, and
three real cases need rejecting:

| entry | names | why it is rejected |
|---|---|---|
| `takapau` | `momoe` | a comparative note about a Proto-Polynesian cognate |
| `puri` | `pupuhi` | a source slip: `pupuhi` is from `puhi` |
| `taurekareka` | `karokaro` | true, but stated inside another word's entry |

The rule: **the child must contain the base**, after folding macrons only,
and be longer than it.

Deliberately permissive. Māori reduplication has more shapes than a tidy
rule admits — full (`eke` → `ekeeke`), initial syllable (`nui` → `nunui`),
final foot (`kōrero` → `kōrerorero`), inside a compound (`pāwera` →
`pāwerawera`), two morae (`ariā` → `ariariā`). A tighter rule rejected eight
genuine source statements when this design was first drafted. Over-tight
filtering discards what the source said, which is worse than admitting a
loose containment test, because the source's assertion — not our pattern —
is what licenses the row.

**The filter must not collapse doubled vowels.** `normalise_search_key`
folds `ekeeke` to `ekeke`, which no longer equals `eke` twice. The collapse
destroys the very seam that makes a reduplication visible.

`karokaro < karo` is a true statement this design still skips: it appears in
*taurekareka*'s entry, not on the word it describes, and attaching a
derivation to an entry from another entry's prose is a different mechanism
than this spec builds.

## 5. The process is asserted, not re-derived

`53_build_word_origin` reads the affix off the two spellings with
`describe_derivation`. For reduplications that produces wrong answers:

    ekeeke  < eke   ->  ('suffix', '-ke')     the seam was collapsed away
    roroa   < roa   ->  ('prefix', 'ro-')     a partial reduplication
    nunui   < nui   ->  ('prefix', 'nu-')     a partial reduplication

papakupu says "reduplicated form". That statement is better evidence than
our reading of the letters, so these rows carry `process = 'reduplication'`
and `affix = NULL` directly. Re-deriving what a source already told us is
the mistake §2 rejects, in a smaller form.

## 6. The normalisation fix

`53_build_word_origin` calls `describe_derivation(nk(child), nk(base))`.
`nk` is `normalise_search_key`, which strips macrons **and collapses doubled
vowels**. That collapse is wrong whenever a doubled vowel is a morpheme
seam, and 61 shipped rows are wrong because of it:

| | now | correct |
|---|---|---|
| `whakaaeaea` < `Aeaeā` | `('prefix', 'whak-')` | `('prefix', 'whaka-')` |
| `kīia` < `kī` | `('suffix', '-a')` | `('suffix', '-ia')` |
| `tongiiti` < `tongi` | `('suffix', '-ti')` | `('suffix', '-iti')` |
| `awaawa` < `Awa` | `('suffix', '-wa')` | `('reduplication', None)` |

`whaka-` is the most productive prefix in the language and is stored as
the truncated `whak-` in 17 rows; 23 of the 24 prefix corrections restore a
`whaka-` form (`whakaro-` → `whakaaro-`, `whakaek-` → `whakaeke-`), and the
twenty-fourth is `ur-` → `uru-`. On the suffix side `-ia` is stored as `-a`,
which corrupts exactly the per-suffix counts this corpus exists to answer.

**But the collapse cannot simply be removed.** Williams (1957) writes a long
vowel as a doubled letter — its `Paaha` is `pāha` — so the collapse is what
reconciles Williams's orthography with macron spellings. Removing it breaks
three rows that currently work:

    whakapāha    < Paaha    ('prefix','whaka-')  -> (None, None)
    tiītoretore  < Tītore   ('suffix','-tore')   -> (None, None)
    whakatorohūū < Torohū   ('prefix','whaka-')  -> (None, None)

The same `aa` is a morpheme seam in one source and a long vowel in another,
and no single normalisation serves both.

**The rule: try the strict fold first, fall back to the collapsing key.**
A doubled vowel is treated as a seam when that yields a derivation, and as a
long vowel when it does not. Measured over all 6,153 rows on this path
(Williams 1,507 and ngata 4,646): **61 rows change and none regresses.**

    suffix -> suffix (affix corrected)     30
    prefix -> prefix (affix corrected)     24
    suffix -> reduplication                 5
    suffix -> prefix                        1   ('aaro, āro', a comma in
                                                 the headword; garbage
                                                 either way)
    None   -> suffix                        1   ('rūnāa' < 'rūnā')

Only the `derived_from` path uses `describe_derivation`. The 5,271 compound
rows take their process directly from `53_build_word_origin` and are
untouched — a first draft of this measurement recomputed them too and
produced a fictitious 4,350-row regression.

## 7. Unresolved ends are dropped

A `derivation` row needs both ends resolved to entries. Ten parsed
statements name a word that is not a papakupu entry:

    hohoko, hokohoko < hoko      taketake  < take
    whakawāwā < whakawā          nunui     < nui
    pāwerawera < pāwera          (and others)

All exist elsewhere in the corpus — `taketake` is a headword in 26 sources —
but papakupu names no source, so choosing one would invent a pointer the
source never made. `53_build_word_origin` already drops any `derived_from`
whose target does not resolve; this follows that discipline rather than
carving an exception.

`te_matatiki` → `williams` cross-source derivations exist (3,220 rows) and
are not a counter-example: Te Matatiki prints Williams page numbers, so the
source itself points across.

## 8. No new `form_type`

Everything lands in `derivation` as `process = 'reduplication'`. The `form`
table keeps its four types.

The previous spec rejected a `reduplication` form type because 8 rows would
misrepresent a phenomenon of 873. That objection dissolves once §2 settles
that the 873 are not harvestable — but the simpler answer stands anyway:
`derivation.process` is already the vocabulary for word formation and
already holds 279 reduplications. A second home for the same idea would
split it.

## 9. Expected result

| process | now | after |
|---|---|---|
| compound | 5,271 | 5,271 |
| suffix | 5,175 | 5,170 |
| prefix | 661 | 662 |
| **reduplication** | **279** | **302** |
| NULL | 38 | 37 |
| **total** | **11,424** | **11,442** |

18 new rows, all from papakupu's prose. 61 existing rows corrected in place,
of which 5 become reduplications.

**The tilde markings are NOT harvested.** The previous spec deferred eight of
them (`ue ~ue` yielding `ueue`), and two resolve at both ends. They are still
deferred, and on reflection they do not belong here at all: the notation says
a form exists, never that it is a reduplication. Reading `~ue` on `ue` as
reduplication is our inference, which is the thing §2 refuses. They would
need their own warrant.

`entry` 153,440 · `sense` 175,101 · `form` 35,638 · `concept` 91,140 and the
18 confirmed judgements are unchanged. `relation` goes 175,407 → 175,425.

## 10. Testing

**Unit, the parser** — both shapes; a sense number present and absent; the
three traps rejected by name; prose noise (`includes`, `embraces`, `can`)
rejected; a definition with no mention yielding nothing.

**Unit, the filter** — `ekeeke` accepted against `eke` (the vowel-seam case
that a collapsing fold would reject); each of the five reduplication shapes
in §4 accepted; `momoe`/`takapau` and `pupuhi`/`puri` rejected.

**Unit, the normalisation** — `whakaaeaea` < `Aeaeā` gives `whaka-`;
`kīia` < `kī` gives `-ia`; `awaawa` < `Awa` gives `reduplication`; and the
three Williams doubled-vowel-length rows still resolve through the fallback.
A test asserting zero regressions across the 6,153-row path.

**Corpus** — the table in §9, exactly; the 19 new pairs present by exact
spelling; no derivation row whose base and child are equal.

**Invariants** — the list in §9.

## 11. Rebuild

`50_build_unified.py --source papakupu`, then `59_rebuild_derived.py`, then
verify against §9. Snapshot judgements with `61_export_judgements.py` first,
and back up the database.

`59_rebuild_derived.py` takes no flags and executes on any argument,
including `--help`. Never pipe it through `head`; redirect to a file.
