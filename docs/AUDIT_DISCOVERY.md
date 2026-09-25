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

**The failure is not general — measured across six sources on cluster `aramona`, 2026-09-24.**
The first draft of this entry implied `_seed_groups` never rejoins a source's own seeds. It
does, for half of them.

| source | headword on >1 entry | identical gloss | split across concepts |
|---|---|---|---|
| te_aka | 5,707 | **986** | all |
| paekupu | 2,117 | **833** | all |
| williams | 1,093 | 0 | all |
| ngata | 5,294 | 128 | **0 — already grouped** |
| hepatakakupu | 4,921 | 4,921 | **0 — already grouped** |
| papakupu | 540 | 8 | **0 — already grouped** |

ngata, hepatakakupu and papakupu encode a shared word id inside `source_entry_id`
(hepatakakupu's `word_id~sense`, ngata's `seid#wid~i`), which `lexeme_key` collapses, so their
repeats are one lexeme and one seed already. te_aka, williams and paekupu mint an unrelated id
per entry, so nothing ties them together.

**williams's 1,093 are not a defect.** None of them shares a gloss: they are the `(i)`/`(ii)`
homographs, which belong in separate concepts and which the `homograph` finding kind exists to
keep apart. Counting them here would have inverted the rubric's most important protection.

So the real population is **te_aka 986 + paekupu 833 = 1,819** identical-gloss repeats held as
two or more concepts.

### Where it is recorded

One `queued` finding on cluster `ako tautauāmoa`, with an `observation` beside it naming the
domain pair as the thing to preserve. The memberships were deliberately **not** confirmed:
confirming both would assert that the split into two concepts is correct, which is the opposite
of the finding.

---

## D41. Subject domains live inside `gloss_en` and never reach `entry_domain` — 2,541 senses — **found by the sweep, queued**

Found judging the calibration slice's fourth tier-3 cluster, 2026-09-24.

te_aka:49647 `ārai-ā-ngaoaho` glosses `'(science) light-dependent resistor.'` The leading
`(science)` is a subject marker, and `entry_domain` holds **nothing at all** for that entry —
so the only record of the domain is inside the gloss text a reader sees.

| senses whose `gloss_en` opens with a parenthetical | |
|---|---|
| te_matatiki | 1,244 |
| te_aka | 1,017 |
| papakupu | 133 |
| paekupu | 102 |
| williams | 43 |
| kimikupu_hou, temarareo | 1 each |
| **total** | **2,541** |

te_aka's are unmistakably subjects: `(sport)` 58, `(mathematics)` 32, `(rugby)` 24, `(golf)` 20,
`(anatomy)` 20, `(softball)` 19, `(chemistry)` 19, `(cricket)` 16, `(biology)` 16, `(music)` 15.

**Distinct from D8.** That finding is about 18,439 te_aka `entry_domain` rows holding a
*register* marker instead of a domain — a wrong value in the right column. This is the domain
never reaching the column at all.

### Constraints on the eventual fix

- **Not every leading parenthetical is a domain.** The shape has to be read before it is
  stripped; a gloss may open with a grammatical or register note, and te_matatiki's 1,244 are
  its own printed convention.
- **Adding is safe, removing is not.** Writing the domain into `entry_domain` is additive and
  breaks no rule. Deleting `(science)` from `gloss_en` edits a source's printed text, which
  §2 of the rubric forbids for the raw fields — the canonical layer is where normalisation
  belongs.
- **The patch layer cannot do it.** `sweep_patch` updates fields; creating an `entry_domain`
  row is an insert. This is why the finding is `queued` rather than `applied`.
- **`subject_area`/`subject_area_en` is the controlled vocabulary** the rubric's §2 already
  permits deriving across languages with, so a mapping from `(science)` to the existing
  Pūtaiao/Science pair has a sanctioned route.

---

## D42. Editorial notes inside `example.text_en` — 3,785 te_aka examples — **found by the sweep, queued**

Found judging the calibration slice's tier-4 cluster `amupa`, 2026-09-24.

te_aka:20438's example reads:

> `On 16 August Mekini was hung for the murder of the child of a woman called Amupa.`
> `note: Maori name?`

The trailing note is te_aka's own editorial query about the headword, not a translation of the
Māori sentence. A reader shown the example sees it. **3,785 te_aka examples** carry a `note:`
marker inside `text_en`.

### The notes are not one kind

This is why the finding is `queued` and not `applied` — the target column depends on which
kind it is:

| shape | example | belongs in |
|---|---|---|
| glossing a proper noun | `note: Persian king.` · `note: pharoah` | a sense gloss, or nowhere |
| a citation | `note: 2Sam1:20` | `example.citation` |
| an open editorial query | `note: Maori name?` | not a user-facing field at all |

§3 permits `applied` only where the target column is unambiguous. Here it is not, and a blanket
strip would discard a citation that the schema already has a home for.

### Related but distinct

- **D9** was source HTML reaching `definition_raw` — markup, mechanically removable.
- **D41** is a subject domain inside `gloss_en` — one kind of content, one target column.

This one is a single marker carrying at least three kinds of content, which is what makes it a
classification problem rather than a cleanup.

### Also recorded on that cluster

1,380 senses are glossed exactly `unknown` — te_aka 1,376, ngata 4. That is **not** a defect:
§2 says a missing gloss is reported and never filled, and te_aka is being honest about a
transliterated name it could not identify. Recorded so that a consumer counting glosses knows
these are a deliberate absence rather than content.

---

## D43. The monolingual source is structurally excluded from the concept layer — hepatakakupu, 24,941 memberships — **narrow fix built 2026-09-25; 5.4% → 8.7%, remainder open**

Found judging the calibration slice's tier-3 cluster `auahitūroa`, 2026-09-24. The most
consequential finding of the slice so far.

`concept_evidence`'s gloss axes — `gloss_overlap` (weight 0.5) and `gloss_overlap_weak` (0.3) —
compare `gloss_en`. **`gloss_mi` appears nowhere in the module.** He Pātaka Kupu is a
monolingual Māori dictionary, which §4 of the rubric correctly records as normal, so it has
`gloss_en` for **none** of its 24,941 senses and can never produce gloss evidence.

| source | joins a concept holding another source |
|---|---|
| williams | 17,595 of 24,976 — **70%** |
| ngata | 20,995 of 33,775 — **62%** |
| papakupu | 2,580 of 4,683 — **55%** |
| te_aka | 26,965 of 59,485 — **45%** |
| paekupu | 5,257 of 16,486 — **32%** |
| **hepatakakupu** | **1,336 of 24,941 — 5%** |

Its 5% comes entirely from the non-gloss axes: `cites_source`, `shared_example` and
`attributed_quote`.

### The proof case

`auahitūroa` is unambiguous. hepatakakupu:4287 glosses it in Māori as a celestial body with an
elliptical orbit, an ice and dust nucleus, growing a tail near the sun. te_aka:516 glosses it
`'Comet'`. **One cognate set — `AUAHI-TUROA '(To Auahi-Turoa), a comet. Cf. auahi, smoke.'` —
links to both entries.** They are still concepts 2602536 and 2602537.

> **Correction, 2026-09-25.** This entry originally read *"Both are canonically `Noun`, so no
> part-of-speech block applies."* That is true entry-to-entry and **false sense-to-sense**.
> te_aka:516 has two senses: **#1 `Proper noun (person)`** — Auahitūroa the personage — and
> **#2 `Noun`**, the comet. `proper noun` is deliberately outside `OPEN_POS`, so #1 *does*
> block against hepatakakupu's `Noun`. A block against any one member rules out the whole
> concept, so sense 1 vetoes attachment to sense 2. That is a second and independent cause,
> recorded below as **D44**, and it is why this cluster is still two concepts even now that
> the evidence axis it asked for exists.

### Why this is hard, not merely unfixed

- **A Māori-to-Māori axis buys almost nothing.** Only two sources carry `gloss_mi` at all:
  hepatakakupu (24,900) and paekupu (3,435). Every other source has zero. So a `gloss_mi`
  overlap axis could only ever pair hepatakakupu with a fifth of paekupu.
- **Cross-language gloss matching is forbidden.** §2: *"Translating a gloss from one language
  into the other is authoring, not auditing, and is forbidden."* An axis that matched
  `'Comet'` against `'He ao tuarangi…'` would have to translate one of them.
- **The non-gloss axes are the route, and they are narrow.** `shared_example` needs two sources
  printing the same sentence; `cites_source` needs one source citing another's entry. Neither
  is available for most of hepatakakupu.

### What the cluster shows is available

The etymology link was decisive here and is not currently an evidence axis in `WEIGHTS`. A
shared cognate set is not proof on its own — the `hoi` canary in
`tests/test_concept_acceptance.py` records that `shared_cognate_set` once merged ten distinct
words into one concept, which is why it was removed or blocked. But **a shared cognate set
plus a compatible canonical part of speech** is a narrower claim than either alone, and this
cluster is a case where it would have been right. That is a hypothesis for the concept work to
test against the calibration answers, not a change to make blind.

### The hypothesis, tested — 2026-09-25

Measured before implementing, over the 23,605 stranded memberships:

| gate | memberships | |
|---|---|---|
| single-source hepatakakupu memberships | 23,605 | 100.0% |
| …`headword_search` shared with another source | 22,863 | 96.9% |
| …and a cognate set shared with one of those | 16,441 | 69.7% |
| …and at least one partner unblocked | 16,297 | 69.0% |

**The part-of-speech conjunct is vacuous.** The hypothesis above claimed "a shared cognate set
plus a compatible canonical part of speech" is narrower than either alone. It removes **144
memberships, 0.9%** — 968 partner-pairs on macron disagreement and 225 on POS. It cannot be
the safety mechanism, and for the right reason: `OPEN_POS` deliberately lets noun, verb,
stative, modifier and adverb interchange, so the block almost never fires.

**What the conjunct missed is ambiguity, not category.** Counting distinct partner *words*,
a stranded sense reaches **5.3 on average**, and 2,391 of them reach ten or more. `keho` alone
has five hepatakakupu senses all reaching williams:2671's 'Peak of a hill' *and* 'Frost, ice'.
Shipping this would have been `hoi` again.

**Sense-level cognate links do not rescue it.** `ETY_entry_link.sense_id` is populated on 88.5%
of rows, but requiring a sense-level match trims only 16,297 → 15,681 — those ids are assigned
mechanically by `resolve_unambiguous_senses` where the target has one sense, not semantically.
It also *loses* `auahitūroa`, since te_aka carries `sense_id` on just 51% of its links.

### What was built instead

The discipline D32 and D34 already use — act only where exactly one candidate survives — and
required from **both** sides:

> a shared cognate set **∧** unblocked **∧** exactly one surviving partner lexeme, each way

Mutual uniqueness costs 1,057 of the 5,737 one-sided pairs and buys a symmetric claim, which
matters because `positive_evidence` is scored in both directions. Shipped as evidence kind
`shared_cognate_set_unique` (weight 0.6, confidence **probable** — the link is stated and the
uniqueness proved, but no source says the two entries are one word), in
`concept_evidence.cognate_unique_pairs`, with `tests/test_concept_cognate_unique.py`.

| | axis off | axis on |
|---|---|---|
| concepts | 91,140 | 90,419 |
| spanning 1 source | 72,193 | 70,773 |
| spanning 2 sources | 11,832 | 12,514 |
| **hepatakakupu cross-source** | **5.4%** | **8.7%** (+832) |
| williams cross-source | 70.4% | 72.2% |
| `hoi` concepts (canary floor 7) | 7 | 7 |

### Scale

At 5%, roughly 23,600 hepatakakupu memberships sat in single-source concepts. The hedge that
"some of those words genuinely appear in no other dictionary" is now measured and is small:
**only 742 of 23,605 — 3.1% —** have a headword no other source carries. Vocabulary is not the
explanation. The axis above recovers 832; the remaining ~15,400 are reachable by headword and
cognate set but ambiguous, and need evidence a cognate set cannot supply.

---

## D44. One sense's part of speech vetoes its whole entry — 148 attachments, 324 senses — **✅ fixed 2026-09-26**

Found 2026-09-25, implementing the **D43** axis. It is why D43's own proof case still does not
merge, and it is independent of D43.

`form_concepts` refuses a concept if a block holds against **any** current member:

```python
if any(blocks(s, e) for s in seed for e in existing):
    continue
```

That is the anti-chaining rule, and the rule itself is right — it is what stops a third source
compatible with each of two separated words from quietly joining them. The problem is the
granularity of what it quantifies over. A seed is a whole **lexeme**, so a block earned by one
sense is applied to every sense of that entry.

### The case

| sense | part of speech | |
|---|---|---|
| te_aka:516#1 | `Proper noun (person)` | Auahitūroa, the personage |
| te_aka:516#2 | `Noun` | the comet |
| hepatakakupu:4287#1 | `Noun` | the comet, described in Māori |

`cognate_unique_pairs` names `(hepatakakupu:4287#1, te_aka:516#2)` as a mutually unique pair —
the evidence is there and correct. But te_aka:516#1 is a proper noun, `proper noun` is
emphatically outside `OPEN_POS` (the `Hene` rule, and rightly so), and so the block it earns
against `Noun` rules out the entire concept. Sense 2 never gets to attach.

### Why this is not a quick fix

- **The POS block is sense-level; the seed is entry-level.** `blocks()` already compares the
  sense's own `part_of_speech_en`. It is the quantifier in `form_concepts` that widens a
  sense's claim to its whole lexeme.
- **Narrowing it weakens the anti-chaining rule**, which the design calls "the safety
  mechanism of the whole design". Any change here must be measured against the `hoi` canary
  and the calibration answers, exactly as the D43 axis was.
- **Not every block should narrow.** A source filing two entries apart (`a['lexeme'] !=
  b['lexeme']`) is a statement about *words* and should keep vetoing the whole seed. A macron
  disagreement is about a *spelling*. Only the POS block is clearly a per-sense claim. The
  three may not deserve the same treatment.

### Scale — measured 2026-09-26

Measured by replaying the real attachment loop over the whole corpus and recording every
seed-vs-concept rejection where at least one sense of the seed was itself clean **and** had
positive evidence — the attachments a per-sense rule would have allowed.

| | |
|---|---|
| seed-vs-concept rejections caused by a block | 67,525 |
| …where **every** sense was blocked — genuine | 67,016 (99.2%) |
| …clean sense, but no evidence anyway | 361 |
| **…clean sense with evidence — preventable** | **148 (0.22%)** |

148 attachments, **324 senses**: papakupu 164, williams 93, te_aka 67. No other source is
affected at all.

### The speculation above is confirmed, and more sharply than it was put

This entry guessed that the three block kinds "may not deserve the same treatment". Measured,
**every one of the 148 is caused by the part-of-speech block alone.** Not predominantly —
exclusively. Zero involve a macron disagreement, and zero involve a source filing two entries
apart.

That last is the important one. The anti-chaining rule's stated purpose is the *lexeme* block
— *"if two words are separated by their own source's numbering, no third source compatible
with each can later join them"* — and the lexeme block never appears in this population.
Narrowing the POS block to the sense that earns it would leave the anti-chaining mechanism
untouched.

### What it would attach

| confidence the attachment would earn | |
|---|---|
| `certain` | 5 |
| `probable` | 91 |
| `uncertain` | 52 |

The export keeps `status = 'confirmed' OR confidence IN (certain, probable)`, so the 52
uncertain ones would not ship unless a human confirmed them: the shipped gain is about **96
attachments**. Small, and it includes D43's proof case — `auahitūroa`, blocked by
`part_of_speech`, with `shared_cognate_set_unique` as its evidence, sitting in this population.

Worked examples: te_aka's `ae` (sense 1 `Verb` 'to agree' blocks; senses 2–4 `Interjection`
'yes' are clean and match papakupu's 'yes, in the sense of "I agree with"'); papakupu's `ata`
(sense 1 `Noun` 'morning, daylight' matches ngata 'Morning', while sense 3
`Proper noun (person)` blocks).

### Fixed — scope, not a new rule

The first design considered was to attach only the clean senses. That was wrong: it would have
**split a seed across concepts**, and a seed is a lexeme — a grouping the source stated, and
the reason seeds are trusted where cross-source attachment is not.

The block's own comment gives the right answer instead. It fires only when both sides are
single-valued, because *"a source listing several parts of speech is describing a word that
functions several ways; that is not a claim excluding another source's single tag"* — and
`_pos_atoms` splits on `[,/|]`, so one sense tagged `'Noun, Verb'` was **already** exempt. The
rule was right; it simply could not see the same claim spread over sense rows instead of
commas.

So `concept_evidence.seed_blocks()` weighs the part-of-speech reason against the seed's whole
inventory, and `form_concepts` uses it in place of `blocks()`. The seed stays atomic.

The asymmetry is load-bearing: a seed is a grouping the source **stated**, so the union of its
senses' tags is that source's own claim; a concept is a grouping this pipeline **inferred**, so
its members' tags are not one word's inventory and get no such treatment. Only the
part-of-speech reason is ever suppressed — the lexeme block is the anti-chaining rule's own
instrument and the macron block is a claim about spelling.

| | before | after |
|---|---|---|
| concepts | 90,419 | 90,236 |
| spanning 1 source | 70,773 | 70,617 |
| spanning 5 sources | 523 | 562 |
| te_aka cross-source | 46.1% | **46.6%** (+278) |
| williams | 72.2% | **72.8%** (+155) |
| papakupu | 56.2% | **59.0%** (+132) |
| hepatakakupu | 8.7% | **8.9%** (+55) |
| `hoi` concepts (canary floor 7) | 7 | 7 |
| `aho` / `hiwi` concepts | 15 / 8 | 15 / 8 |

**Not a pure win.** 160 memberships *lose* cross-source status against roughly 750 gained, net
**+586**. The mechanism is ordering: a concept that now accepts a seed earlier has more
members, and a later seed blocking against one of those is correctly kept out. That is the
anti-chaining rule working on a larger concept, not a regression in it — but it is a
redistribution, and the gross figure is the honest one to quote.

**D43's proof case closes.** `auahitūroa` goes from two concepts to one, holding
`hepatakakupu:4287#1` with both te_aka senses, on `shared_cognate_set_unique` evidence. It took
both fixes: without the D43 axis there is no evidence, without this one the evidence was
vetoed. Persisted to `staging_dictionary.db` 2026-09-26; all 28 judged rows kept.

---

## D45. An inflected English gloss never overlaps its own base form — 895 memberships — **found by the sweep, queued**

Found judging the calibration slice's tier-1 cluster `kaingākau`, 2026-09-25.

`concept_evidence._content_words` lowercases, folds macrons and splits on `[a-z]+`. It does
not stem. So two sources glossing the same word with the same English lexeme in different
inflections share nothing at all:

| source | gloss | content words |
|---|---|---|
| taikupu | `'valued'` | `{valued}` |
| te_aka | `'to prize greatly, value, treasure, fond of…'` | `{prize, greatly, value, treasure, fond…}` |
| williams | `'Prize greatly, value.'` | `{prize, greatly, value}` |

The intersection is **empty**, so no gloss axis can fire, and taikupu sits in its own concept
while te_aka and williams share one — even though a single cognate set, `KAINGAKAU 'to prize
greatly, to value'`, links all three.

### Scale

Measured over the memberships now sitting in single-source concepts, using a deliberately
conservative rule: a surface form counts as an inflection only when the stem is **itself
attested as a gloss word somewhere in the corpus**, so nothing is invented — `valued` reaches
`value` because the sources use `value`, and `ring` never reaches `r`.

**895 memberships would gain gloss evidence**, across every bilingual source:

| source | | source | |
|---|---|---|---|
| te_aka | 291 | taikupu | 45 |
| paekupu | 209 | papakupu | 42 |
| ngata | 169 | kimikupu_hou | 26 |
| williams | 105 | others | 8 |

**381 of them are reachable by plural/singular alone** — the safest subset.

### The grading rule already handles the bad ones

This is why the finding is `queued` rather than blocked. Graded by the existing
coverage/distinctiveness rule, the 895 split:

| | | |
|---|---|---|
| would grade ordinary `gloss_overlap` | 308 | 34.4% |
| would grade `gloss_overlap_weak` | 587 | 65.6% |

The ordinary ones are unambiguous — ngata `'Deform'` against williams `'Deformed. Turi haka…'`;
ngata `'Disengage'` against williams `'Separated, disengaged, divided.'`; te_aka `'sawyers.'`
against papakupu `'sawyer {From English}'`; ngata `'Cringe'` against te_aka `'…shivering from
cold, cringing.'`

The spurious ones land in the weak bucket exactly where they belong: williams's `'A small
fresh-water fish'` reaches te_aka's `'breaking of the waters (childbirth).'` through
`waters`→`water`, and grades weak on both axes because `water` is common and covers almost
none of either gloss. **The grading rule is not what is blind — the tokeniser is.**

### Why ngata is disproportionate

ngata is an English→Māori dictionary, so its `gloss_en` is the English headword in citation
form: `'Deform'`, `'Cringe'`, `'Slope'`, `'Hop'`. Every other source glosses in running English
and inflects. The mismatch is therefore systematically ngata-against-everyone, and it is
structural rather than incidental.

### What this is not

Not a licence to match loosely. §2 forbids deriving across languages; this is entirely within
English, and the attested-stem constraint keeps it to forms the sources themselves use. A
looser rule — edit distance, or stripping suffixes without checking the result is a word —
would be inventing the link rather than reading it, and is the same error
`resolve_relations_by_gloss` refused when it required exact string identity (D34).

---

## D46. Te Aka's sense-level synonyms are flattened onto the entry — 87,569 relations — **found on the bench, queued**

Found 2026-09-26, answering a question about te Aka's relation model. Not found judging a
cluster: `aho`, the case below, sits at priority 1 behind the calibration slice.

### The source says which sense; the build does not

`04_te_aka_parse.py` reads the dictionary-link anchors **inside each sense's div** and stores
them on that sense (`sense_synonyms`, line 160). It then also accumulates an entry-level
`all_synonyms`, commented *"legacy / FTS / synonym resolution"*.

`50_build_unified.py` line 618 iterates that entry-level aggregate and calls
`b.add_relation(eid, ...)`. **The per-sense list is never read.** `relation` has no source-side
sense column, so the assertion becomes one about the word.

`te_aka_entries.senses` still holds the per-sense lists, so nothing was lost at parse and
nothing needs re-scraping. The flattening is entirely in the build.

### `aho` — five senses, two synonym sets, twelve flat relations

| | |
|---|---|
| sense 1 | `fishing line, cord, string, line, medium for an atua` |
| sense 2 | `weft, woof - cross-threads of weaving or a mat.` |
| sense 3 | `line of descent, genealogy.` |
| sense 4 | `chord (maths).` |
| sense 5 | `sine (maths)` |

The source puts `{io, kapa, papanga, raina, ripa, rārangi, tawhā}` on **sense 1** and
`{hikahika, kaha, kāwai, kāwei, takiaho}` on **sense 3**. What is built is twelve relations on
the entry with no sense, so the cord sense and the genealogy sense become mutual synonyms.
`aho` is the rubric's own `spurious_etymology` worked example.

### Scale

| | |
|---|---|
| te_aka synonym relations | 87,569 |
| entries carrying at least one | 10,676 |
| of those, multi-sense | 4,489 |
| **whose senses carry different sets** | **2,046** |
| relations sitting on a multi-sense entry | 49,755 |
| relations attributable to a named sense | 89,957 |

The last row exceeding the first is a second, smaller loss: the entry-level aggregate dedups
(`if syn not in all_synonyms`), so a synonym serving two senses collapses to one link and the
fact that it serves both is discarded — **2,388 attributions**.

### The 42% that looks like sense resolution is not

`target_sense_id` is set on 37,104 of the 87,569. Of the **50,465** relations pointing at a
*multi-sense* target, **zero** have a sense chosen. Every resolved one came from
`resolve_unambiguous_senses` picking the only sense there was. There is no editorial sense
choice in this data, on either side.

### It is also dense, which compounds it

Median degree 4, max 170, **91% reciprocated**. Of 1,421 connected components, 1,175 (82.7%)
are complete graphs — synonym sets expanded to full cliques. But the largest component holds
**7,630 entries**, 71% of everything carrying a synonym, because the cliques chain through
shared members. Flattening senses is what lets them chain: `aho`'s two unrelated sets are
joined at the entry, and every set touching either is now one component.

### Why this is queued, not applied

The fix is a build change, not a field patch — `add_relation` would need a source-side
`sense_id`, and `relation` would need the column. That is schema work plus a rebuild, and it
should be measured against the concept layer first: 49,755 relations currently asserting more
than the source does is also 49,755 that `resolve_within_source_relations` and the concept
evidence axes have been reading. Narrowing them is likely right and is certainly not free.
