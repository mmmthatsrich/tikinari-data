# Audit Discovery Pass — Systemic Defect Findings

**Date:** 2026-09-07 · **Scope:** all 11 word-list sources in `data/maori_dict.db`
**Status:** findings only — nothing was written to either database.

## Purpose

Before the cluster-by-cluster audit sweep, find the defects that are *systemic* — recurring at
scale and traceable to a pipeline script — so they can be fixed at source rather than patched
tens of thousands of times downstream. A defect fixed in the importer costs one script change;
the same defect fixed in the sweep costs tens of thousands of judgements that are invalidated
the moment anyone re-imports.

## Method

A stratified sample of complete entries — every field of `entry`, `sense`, `example`, `form`,
`relation`, `entry_domain` — was read across all 11 sources. Defects were identified by
reading, not by pattern-matching. Only defects actually observed were then quantified with
targeted counts. Counts are evidence for a defect already seen, never the means of finding it.

---

## Tier 1 — Content missing that already exists elsewhere

### D1. Paekupu: 13,050 senses are empty shells, and the content is recoverable — **RESOLVED 2026-09-11**

**79% of Paekupu's senses** (13,050 of 16,486) have no `gloss_en`, no `gloss_mi`, and no
`definition_raw`. The sense row exists, carries POS and canonical POS, and holds nothing else.

This is not lost data. **All 13,050 have `entry.headword_en` populated** — `'zenith'`,
`'auto-filter (computing)'`, `'birth control pill, oral contraceptive'`. The English gloss is
sitting in the entry table and was never projected into the sense.

- **Cause:** `50_build_unified.py`, Paekupu branch — `gloss_en` was the definition and
  nothing else, so an entry without one produced a sense holding only its POS. `headword_en`
  was written to `entry` and never projected down.

**Fix applied.** `build_paekupu` now projects `d or hen`: the definition where there is one,
the entry's English headword where there is not. The headword *is* the gloss for these rows —
Paekupu is a term bank, and each record exists to give a Māori term for a named English
concept.

A second, central change: `Builder.add_sense` now coerces blank text to NULL
(`_blank_to_null`). Paekupu's `definition_raw` was being written as `''` — the concatenation
of two absent fields — which reads as present-but-blank to the app, to FTS and to this
report's own emptiness counts. The guard sits in the builder, so every source gets it; it also
cleared 9 papakupu senses whose landing rows hold `''` where 15 identical neighbours hold NULL.

| | Before | After |
|---|---|---|
| paekupu senses with no gloss, no definition | 13,050 | 0 |
| gloss projected from `entry.headword_en` | 0 | 13,050 |
| senses storing `''` for absent text (all sources) | 13,059 | 0 |
| paekupu entries / senses | 16,486 | 16,486 — unchanged |

**Verified.** 30 recovered glosses were checked against the cached source pages in
`sources/paekupu/raw/` — all 30 match the page's `h2.english_word` verbatim, and all 30 pages
genuinely carry no `short_description` block, so nothing is being papered over. Etymology
rebuilt (`08b` + `52`, parity PASS) and the app DB re-exported. Full suite: 434 passed,
3 skipped.

### D2. Williams: examples were never extracted — 61 entries out of 14,942

Williams definitions carry their examples inline, with citations:

> `Titere` — `"Throw, cast. Me titere mai kia kai atu au ko te waha (Ngā Mōteatea 19)"`

The gloss is *Throw, cast*; the rest is a Māori example sentence and its source citation. Yet
only **61 Williams entries have any `example` row at all**. Thousands of examples and citations
sit inside `definition_raw`, invisible to the app's example rendering and to FTS as examples.

Note `Tinei`: `"...extinguish.Ka po, ka tikina..."` — no space after the period. Any splitter
regex either misses this or over-splits its neighbours. The judgement is genuinely hard, but
the *extraction* belongs in the parser where it runs once.

- **Cause:** `01_williams_parse.py` — no example/citation separation.
- **Fix:** extract trailing Māori sentences and parenthesised citations into structured examples.
- **Verify:** Williams example rows rise from 61 into the thousands; sample 50 by hand.

### D3. Williams: 148 senses are truncated mid-text

`Mumu` sense 1 ends `"...ka riro te awha (Ngā Mōteatea 124"` — the closing parenthesis and
everything after it is gone. 148 senses have unbalanced parentheses, indicating content loss at
parse time rather than display truncation.

- **Cause:** `01_williams_parse.py` boundary handling.
- **Verify:** unbalanced-paren count → 0; diff re-parsed output against the Wayback HTML.

---

## Tier 2 — Wholesale field misplacement

### D4. Williams: the entire definition is duplicated into the gloss

**18,792 of 24,556 senses** have `gloss_en` byte-identical to `definition_raw`. `gloss_en` is
not holding a gloss; it holds the definition, the examples and the citations together. Anything
reading `gloss_en` for a short gloss gets a paragraph.

Fixing D2 largely fixes this: once examples and citations are extracted, what remains *is* the
gloss.

### D5. Te Matatiki: 6,429 relations point at citation codes, not headwords

Te Matatiki records each coinage's derivation as a Williams reference:

> `Hororē` "Vacuum cleaner" — `[horohororē W.61 'to eat greedily']`

The importer turns `W.61` into a `relation` row with `target_headword = 'W.61'` and
`rel_type = 'cross_ref'`. `W.61` is a locator into Williams, not a Māori headword, so it can
never resolve. `Kāhuarau` produced **two** relation rows carrying the identical full note.

**`W.NNN` is a page number — verified, not assumed.** Looking up each bracketed Māori word in
`williams_entries` and comparing its `page_number` to the reference:

| Bracket word | Ref | Williams page | |
|---|---|---|---|
| `kāhua` | W.85 | 85 | exact |
| `hiki` | W.49 | 49 | exact |
| `rau` | W.328 | 328 | exact |
| `horohororē` | W.61 | 61 | exact |
| `unu` | W.467 | 467 | exact |
| `wāhi` | W.474 | 473 | off by one |
| `whakamatua` | W.195 | no headword match | see below |

`whakamatua` is not a Williams headword, but page 195 is exactly where the `Matua` family sits
(`Mātua`, `Matua`, `Matuaiwi`, and the recovered sub-headword `whakamāturu`). It is a run-in
derivative inside another entry — a known sub-headword recovery gap, not a bad reference.

This is derivational etymology sitting in the relations table. It belongs in the etymology
layer or a citation field — and the Māori source-word inside the bracket (`horohororē`, `wāhi`,
`kāhua`) is the thing that should resolve to an entry.

- **Cause:** `41_wakareo_parse.py` / `41_wakareo_import.py`, Te Matatiki branch.
- **Fix, strengthened by the verification above:** resolve on **page number + bracketed word**
  rather than the word alone. The page disambiguates homographs for free, and a word that
  matches on the right page but is not a headword is positive evidence of a missing Williams
  sub-headword — so this pass also generates a recovery list for D2's parser work.
- **Expect ~1 page of tolerance** (`wāhi`) for entries spanning a page break, and a fallback to
  run-in derivatives when the headword lookup misses.

### D6. Tregear exceptions: multiple senses, examples, cross-refs and notes in one field

> `Kārapa` — `"1. Squinting. 2. To flash; flashing. 3. A species of eel. Maori Example: Ki te
> mea ka uira kārapa aua kura whero. (AHM v 42) Compare With: rarapa"`

One `sense` row containing three distinct senses, a labelled example, a citation and a
see-also. `Kauaemua` adds a fourth class — `"Comments: Williams has this meaning but not a
Māori example."`, an editorial note. The labels (`Maori Example:`, `Compare With:`,
`Comments:`) are explicit and machine-visible; nothing consumed them. 321 entries.

### D7. Te Māra Reo: the gloss holds the protoform, cognate groups are filed as domains

`kauere` has `gloss_en = '*Kauere'` — that is the reconstructed protoform, not a gloss. Its
`definition_raw` duplicates its own bracket content and carries a ` ,` spacing artefact;
`rewarewa`'s bracket ends `[Knightia excelsa; Rewa normally]`, a sentence fragment captured
mid-clause.

Separately, `entry_domain` holds `'Words shared exclusively by Rarotongan & Māori'` and
`'P. Central Pacific'`. Those are cognate-distribution classifications — etymology-layer facts
filed as semantic domains.

### D8. Te Aka: 18,439 domain rows hold a register marker, not a domain

`entry_domain` = `'Historical Loan Word'` on 18,439 entries. Every other domain value is a
subject area (`hauora`, `pūtaiao`, `Tāne`). This is a loanword/register flag occupying the
semantic-domain table, and it is the single most common "domain" in the database.

---

## Tier 3 — Markup and mechanical noise

### D9. Source HTML reached `definition_raw` — 42,189 senses affected — **RESOLVED 2026-09-10**

**Corrected attribution.** An earlier draft of this report blamed `41_wakareo_parse.py` for
having no markup handling. That was wrong: `41_wakareo_parse.py` is a 42-line driver, and the
real parsing lives in `scripts/wakareo_records.py`, which has always had a correct
`strip_tags()` and applied it to every derived field — which is why `gloss_en`, the examples
and the POS were all clean.

The markup survived in `body_raw`, the deliberate archive of the source HTML, and
`50_build_unified.py` passed that archive straight into `definition_raw`.

**Fix applied.** `wakareo_records.parse_record` now emits `body_text` alongside `body_raw` —
the same body with markup stripped, or NULL when nothing but the lemma survives. The Wakareo
landing tables gained a `body_text` column (`00_init_db.py: migrate_wakareo_body_text`),
`41_wakareo_import.py` persists it, and both `50_build_unified.py` Wakareo projections read it
instead of `body_raw`.

`body_raw` is retained deliberately: Tregear's `<B>` runs delimit its definition block from the
`Maori Example:` / `Compare With:` sections, so D6 still needs the structure. Destroying it
would mean re-scraping 146 MB to do that work later.

| Source | Before | After |
|---|---|---|
| ngata | 33,878 | 0 |
| te_matatiki | 5,097 | 0 |
| kimikupu_hou | 2,839 | 0 |
| tregear_exceptions | 321 | 0 |
| papakupu | 54 | 54 — different pipeline, still open |
| **Total** | **42,189** | **54** |

Verified end to end: re-parsed 29,976 records, re-imported, re-unified all four sources,
rebuilt the etymology layer (`08b` + `52`, parity PASS) and re-exported the app DB. Entry
counts are unchanged — ngata 33,878 in and 33,878 out. Full suite: 403 passed, 3 skipped.

### D10. Kimikupu Hou: definitions containing no content — **RESOLVED 2026-09-10**

`definition_raw = '<BR><B>ākahukahu</B><BR><BR><BR><BR>'` — the headword wrapped in tags and
nothing else. Stripping alone would leave the bare headword, which reads as a definition that
merely repeats the word, so `_body_text()` returns NULL whenever the stripped body equals the
headword or one of the record's equivalents.

**2,198 Kimikupu Hou senses are now NULL** rather than falsely definition-bearing, against a
predicted 2,208 — the small difference is records-vs-senses, not a miss.

### D11. Ngata: a leading `</B>` on a recurring subset — **RESOLVED 2026-09-10**

`kohe`, `pita` and `katoa` all begin `'</B> <B>kohe</B>...'`. This turned out to be cosmetic:
`_BOLD` requires an opening tag, so the derived fields were never affected, and
`test_ngata_single_equivalent_with_stray_close_tag` already guarded the case. The artefact only
ever lived in `body_raw` and no longer reaches `definition_raw`.

### D12. Form pollution: mechanically derived spellings filed as variants

| Source | Forms equal to the macron-stripped headword | Total forms |
|---|---|---|
| te_matatiki | 5,049 | 7,251 |
| tregear_exceptions | 301 | 363 |
| papakupu | 443 | 1,077 |

70% of Te Matatiki's `form` rows are just `headword_sort` re-filed as a variant. That is not a
variant — it duplicates a column that already exists, and it inflates any "this word has
variants" signal in the app.

---

## Tier 4 — Tagging and controlled vocabulary

### D13. Māori domain slugs tagged `domain_lang = 'en'`

`tikanga-ā-iwi` (2,933), `hangarau` (2,929), `hauora` (2,924), `pūtaiao` (2,302), `ngā-toi`
(2,195), `te-reo-matatini` (1,118), `pāngarau` (1,088) — all Māori, all tagged English.
**~16,500 rows** at minimum. `domain_lang` is the only thing telling the app which language to
render these in.

### D14. `std_pos` is missing 38 atoms, including comma-split damage

265 distinct atomic POS values appear in `sense`; 38 are absent from `std_pos`, covering 5,367
sense-atoms — Te Matatiki's `[noun]` family, Kimikupu Hou, ngata's `Phrase`.

Two of those 38 are `[noun` and `transitive verb]` — a composite `[noun, transitive verb]`
split on its internal comma, severing the brackets. That is a parse bug wearing a vocabulary
bug's clothes.

### D15. Ngata: examples misattached across synonym groups

Ngata stores synonym sets as one record: `<B>turituri, hoihoi, manioro</B>` with a single
example using `turituri`. The importer correctly creates three entries and links them as
synonyms — but attaches the same example to all three. Entry `hoihoi` carries an example
sentence that does not contain `hoihoi`.

**9,936 of 33,054** ngata examples do not contain their entry's headword. That figure is an
**upper bound** — some are legitimate inflected forms (`ūtonga` → `ūtongatia`). The defect is
confirmed; its exact size needs the sweep to separate misattachment from inflection.

### D16. Examples have no English half in three sources

| Source | Examples missing `text_en` | Total | Assessment |
|---|---|---|---|
| te_aka | 45,939 | 45,939 | Te Aka publishes English translations — likely a parse gap, verify upstream |
| hepatakakupu | 24,447 | 24,447 | **Expected** — He Pātaka Kupu is monolingual Māori |
| paekupu | 9,669 | 9,669 | Verify against paekupu.co.nz |

Te Aka at 100% is the one to check first: 45,939 translations that may exist upstream and were
never captured.

---

## Summary

| # | Defect | Scale | Script |
|---|---|---|---|
| D1 | Paekupu senses empty, recoverable from `headword_en` | 13,050 | ✅ **fixed** — `build_paekupu` projects `headword_en`; blank→NULL in `add_sense` |
| D2 | Williams examples never extracted | 14,881 entries | ✅ **fixed** — `williams_examples.py`; 61 → 8,004 entries, 15,696 examples |
| D3 | Williams truncated senses | 148 | ✅ **fixed** — `_MARKER_RE` lookbehind; 7 remain, all source typos |
| D4 | Williams gloss = whole definition | 18,792 | ✅ **fixed** — 18,792 → 9,878, via D2 |
| D17 | Williams headword-prefix strip orphans a parenthetical | 44 | ✅ **fixed** — `williams_headword.py`; 11 plurals, 16 registers, 11 notes recovered |
| D5 | Te Matatiki citation codes as relations | 6,429 | ✅ **fixed** — `parse_derivation` + page/word resolution; 68% now resolve |
| D6 | Tregear multi-sense / example / xref in one field | 321 | ✅ **fixed** — `parse_tregear`; 86 examples, 218 relations, 49 notes recovered |
| D7 | Te Māra Reo protoform as gloss, cognate group as domain | 203 | ✅ **fixed** — `temarareo_gloss.py`; 181 domain rows → 0, 16 glossless senses → 0 |
| D8 | Te Aka register marker as domain | 18,439 | ✅ **fixed** — `split_filters` → `entry.loan_marker` |
| D9 | Source HTML reached `definition_raw` | 42,189 | ✅ **fixed** — `wakareo_records.py` + `50_build_unified.py` |
| D10 | Kimikupu Hou contentless definitions | 2,198 | ✅ **fixed** — now NULL |
| D11 | Ngata leading `</B>` boundary artefact | cosmetic | ✅ **fixed** — never reached derived fields |
| D12 | Derived spellings filed as variant forms | 7,984 | ✅ **fixed** — guarded in `Builder.add_form`, all sources |
| D13 | Māori domains tagged English, and slugs not display text | 16,486 | ✅ **fixed** — both languages from `subject_area` / `subject_area_en` |
| D14 | `std_pos` gaps + comma-split damage | 5,371 | ✅ **fixed** — `utils.pos_atoms`; unmapped atoms → 0, coverage 99.6% |
| D15 | Ngata synonym-group example misattachment | 9,936 | ✅ **fixed** — `example_owners`; down to 252 |
| D16 | Te Aka example translations absent | 45,939 | ✅ **fixed** — `te_aka_examples.py`; 45,398 recovered. paekupu/HPK confirmed correct as-is |

## Recommended fix order

1. ~~**D9 + D10 + D11**~~ — ✅ **done 2026-09-10.** 42,135 of 42,189 senses cleared across four
   sources; only papakupu's 54 remain, from a separate pipeline.
2. ~~**D1**~~ — ✅ **done 2026-09-11.** 13,050 Paekupu senses recovered by one projection change, plus a central blank→NULL rule in `add_sense`.
3. **D13 + D14** — tagging and vocabulary; small, mechanical, and unblocks canonical POS
   coverage.
4. ~~**D2 + D3 + D4**~~ — ✅ **done 2026-09-11** (commit `f8013b9`). Surfaced **D17**, a
   distinct headword-prefix-strip defect affecting 44 senses, which remains open.
5. ~~**D5 + D6 + D12**~~ — ✅ **done 2026-09-11** (commit `58f388a`), together with D15 and a
   follow-up to the `body_text` NULL rule. ~~**D7**~~ — ✅ **done 2026-09-11** (commit
   `5b43f78`) and **D8** (commit pending).
6. **D16** — verify against the upstream sources before changing anything.

**All 17 findings resolved.** The residues that remain (7 unclosed and 3 orphaned brackets in Williams, 423 `needs_review` POS codes, one papakupu etymology-in-POS outlier) are source-level or expert-review items, documented in the rows above.

## What this changes about the sweep

Items 1–4 should complete before the cluster sweep begins. Sweeping 42,189 markup-laden senses
would spend lexicographic judgement on a missing `strip_tags` call, and every finding recorded
against them would be invalidated by the re-import that eventually fixes them.

Ngata, Te Matatiki and Kimikupu Hou — 41,814 entries, 27% of the corpus — were the worst of
this. **As of 2026-09-10 their markup is gone**, so the blocking objection to sweeping them is
lifted; D5 (Te Matatiki relations), D12 (form pollution) and D15 (ngata example misattachment)
remain open against them but none of those obscure the text the way markup did.

Tregear (D6) still needs `body_raw`'s `<B>` structure to split its senses — that work must read
the archive, not `body_text`.

---

## D18. Macronisation is inconsistent across sources — **blocked on the concept layer**

Unlike D1–D17 this is **not** a pipeline defect, and it cannot be fixed before the sweep. It is
an *output* of deduplication rather than a prerequisite for it.

Williams is often described as macron-free. It is not: 31% of its headwords carry one, within
the range of every other source (paekupu 48%, te_aka 35%, papakupu 27%). Most Māori words have
no long vowel, so the percentage is not the signal. The inconsistency is:

**2,297 Williams headwords are unmacronised while another source writes the same word with a
macron.** Across all sources, 3,393 `headword_search` keys carry both a macronised and a plain
spelling.

**Search is unaffected.** `headword_search` strips macrons and collapses double vowels, so
`āho` / `aho` / `aaho` all resolve to `aho`. This is display consistency, not findability.

### Why it needs the concept layer first

| Of the 2,297 inheritable Williams headwords | |
|---|---|
| on a key with more than one Williams entry (homographs) | **1,300 (57%)** |
| with competing macronisations across sources | 304 |
| clean single-candidate | ~1,000 |

`aho` is the case in point: PPN \*afo "fishing line" and \*aho "daylight" share a search key.
Inheriting a macron on key identity alone asserts that two different words are one — exactly
the error the concept layer prevents. Even the clean cases need proof that the macronised
counterpart is the *same word* rather than a homophone.

A concept record supplies that proof: if Williams #133 and Te Aka #1204 sense 2 are witnesses
to one concept, and Te Aka writes `āho`, then Williams's `Aho` is that word.

### Constraints on the eventual fix

- **Do not rewrite `headword`.** Williams 1957 printed `Aho`; that is the record, and under
  CC BY-SA a quotation. Same rule as part-of-speech: raw preserved, canonical alongside. No
  field exists for it yet — `headword_sort` and `headword_search` are stripped keys, not
  spellings — so this needs a new column (`entry.headword_modern` or similar).
- **Source precedence is a tie-breaker within a concept, never a licence across one.** Te Aka
  can supply 1,943 of the 2,297, then hepatakakupu (1,530) and ngata (1,075).
- **Sequence:** sense addressability → concept layer → macronisation. It is the first item that
  genuinely depends on the sweep having run.

### D7 residue — 12 protoform glosses in the etymology layer

The D7 fix cleaned `sense.gloss_en`, but the same scrape artefact also reached
`ETY_cognateset.gloss`, a different table. 12 of Te Māra Reo's 271 cognate sets
carry a bare protoform where a gloss belongs (`'*Falafala'`, `'*Kauere'`); three
more begin with one but go on to real content (`'*Aute, *Siapo, Broussonetia
papyfera, "Paper mulberry" (Moraceae)'`) and are fine as they are.

Left for the sweep rather than fixed in the pipeline: 12 rows is below the point
where a re-parse and rebuild is cheaper than a judgement, and the batch
assembler surfaces them in the etymology section where they will be read anyway.

---

## D39. Brackets and terminal punctuation reach `headword_search` — 883 entries — **found by the sweep, deferred**

Found judging the calibration slice's first two tier-4 clusters, 2026-09-24. Twenty-nine
tier-1 and tier-2 clusters had not surfaced it: a multi-source cluster is judged on whether
the sources agree, not on whether a reader could have found the word.

paekupu prints `(Te) Rā Rangaawatea`, where the parenthesis marks the article as optional.
`normalise_search_key` keeps it, so `headword_search` is `(te) ra rangawatea` and a reader
searching the bare term does not reach the entry. te_aka's `[tō] tara!` is the same shape with
square brackets and an exclamation mark.

| in `headword_search` | entries |
|---|---|
| round brackets | 707 |
| square brackets | 139 |
| ellipsis `...` | 128 |
| slash | 48 |
| exclamation mark | 46 |
| question mark | 35 |
| **any bracket or terminal punctuation** | **883** |

By source: paekupu 506, te_aka 252, kimikupu_hou 57, papakupu 28, williams 20,
te_matatiki 14, hepatakakupu 4, tregear_exceptions 2. 1,080 sweep clusters are keyed with a
bracket.

### Why it is not simply "strip the punctuation"

**The shapes are not one defect.** Two of them are genuinely different:

- **An optional element.** `(Te) Rā Rangaawatea`, `[tō] tara!` — the brackets mark something a
  speaker may omit. The bare form is the one a reader will type, so the key should hold it.
- **Real alternation.** te_aka's `(ka/he/te) tau/kino (kē) (hoki)` and
  `(ko) wai ka hua, (ko) wai ka tohu` are idiom templates. The parentheses and slashes mark
  choices, and there is no single bare form to strip to. Stripping would produce
  `ka/he/te tau/kino kē hoki`, which is not a word anyone would search for either.

A fix has to tell those apart, and the discriminator is not obvious from the string alone.

**The precedent is that this belongs in the pipeline, not the rubric.** §6 of the rubric records
D19 and D20 being fixed in the script that caused them rather than written into the standard.
The same applies here: `normalise_search_key` builds these keys, and 883 entries cannot be
corrected cluster by cluster.

### Constraints on the eventual fix

- **Do not rewrite `headword`.** Same rule as D18 and part-of-speech: the printed form is the
  record. Only the key changes.
- **Keying on the bare form must not merge homographs.** Stripping `(te)` from
  `(te) ra rangawatea` yields `ra rangawatea`; check first whether that collides with an
  existing key, because a collision is a merge, and merging on key identity alone is the error
  D18 exists to prevent.
- **An entry may need more than one key.** The honest answer for the optional-element shape may
  be that both `(te) ra rangawatea` and `ra rangawatea` should find it, which is a
  search-alias question rather than a key-rewrite one. `form` already holds alternative
  spellings for exactly this purpose and may be the right home.
- **Measure the alternation shapes before touching them.** The 48 slashes and some of the 707
  parentheses are idiom templates where no bare form exists.

### Where it is recorded

Two `deferred` findings in `sweep_finding`, on clusters `(te) ra rangawatea` and `[to] tara!`.
The first counted round brackets only and reported 707; the second corrects it to 883 and
names the per-source and per-shape breakdown. Both are `action='deferred'` rather than
`queued`, because there is no per-cluster patch that would address them.

---

## D40. A source's own repeats are never grouped — 2,117 paekupu headwords — **found by the sweep, queued**

Found judging the calibration slice's fourth tier-4 cluster, 2026-09-24, and invisible to the
twenty-nine multi-source clusters judged before it for the same reason as D39: a tier-1 cluster
is read for whether the *sources* agree, and this is a source disagreeing with itself.

paekupu publishes per curriculum subject, so a coined term can be listed under two subject
areas. `ako tautauāmoa` appears as `ako-tautauamoa` under Hangarau/Technology and
`ako-tautauamoa-2` under Mātauranga Whānui/Education General. Every field that carries meaning
is identical — headword, `headword_en`, `gloss_en`, and the same cross-reference. Only the
domain differs.

| | |
|---|---|
| paekupu slugs ending `-2`, `-3`, … | 3,486 |
| paekupu headwords on more than one entry | **2,117** |
| …of those, with an identical gloss across the entries | **833** |
| …of those, landing in more than one concept | **2,117 — all of them** |

`54_build_concepts._seed_groups` seeds on `lexeme`, which is `(source_id, source_entry_id,
headword, locator)`. Two slugs from one source are two lexemes, so they are two seeds, and
nothing in the matcher rejoins seeds from the same source. The 833 identical-gloss cases are
one word held as two concepts.

### What a fix must not lose

**The domain pair is the only content distinguishing the entries, and it is real information.**
That paekupu classifies `ako tautauāmoa` under both Technology and Education General says
something about the term. A concept can hold two members with both domains attached, so
grouping them need not discard either — but a deduplication that kept one entry and dropped
the other would.

**The 2,117 are not all the 833.** A shared headword with *different* glosses is a homograph,
which the rubric's `homograph` kind exists to protect: those belong in separate concepts and
grouping them would be the worst error the sweep can make. Only the identical-gloss subset is
clearly one word, and even there the check should be on the gloss, not the slug.

**Other sources may have the same shape.** Measured for paekupu because that is where the
cluster led. hepatakakupu repeats a `word_id` across senses by design and is already handled;
te_aka, ngata and williams have not been measured for this.

### Where it is recorded

One `queued` finding on cluster `ako tautauāmoa`, with an `observation` beside it naming the
domain pair as the thing to preserve. The memberships were deliberately **not** confirmed:
confirming both would assert that the split into two concepts is correct, which is the opposite
of the finding.
