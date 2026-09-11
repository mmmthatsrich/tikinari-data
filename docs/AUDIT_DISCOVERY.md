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
| D2 | Williams examples never extracted | 14,881 entries | `01_williams_parse.py` |
| D3 | Williams truncated senses | 148 | `01_williams_parse.py` |
| D4 | Williams gloss = whole definition | 18,792 | resolved by D2 |
| D5 | Te Matatiki citation codes as relations | 6,429 | ✅ **fixed** — `parse_derivation` + page/word resolution; 68% now resolve |
| D6 | Tregear multi-sense / example / xref in one field | 321 | ✅ **fixed** — `parse_tregear`; 86 examples, 218 relations, 49 notes recovered |
| D7 | Te Māra Reo protoform as gloss, cognate group as domain | 203 | `42_temarareo_parse.py` |
| D8 | Te Aka register marker as domain | 18,439 | `04_te_aka_parse.py` |
| D9 | Source HTML reached `definition_raw` | 42,189 | ✅ **fixed** — `wakareo_records.py` + `50_build_unified.py` |
| D10 | Kimikupu Hou contentless definitions | 2,198 | ✅ **fixed** — now NULL |
| D11 | Ngata leading `</B>` boundary artefact | cosmetic | ✅ **fixed** — never reached derived fields |
| D12 | Derived spellings filed as variant forms | 7,984 | ✅ **fixed** — guarded in `Builder.add_form`, all sources |
| D13 | Māori domains tagged English | ~16,500 | `04_paekupu_parse.py` |
| D14 | `std_pos` gaps + comma-split damage | 5,367 | `13_build_pos_normalisation.py` |
| D15 | Ngata synonym-group example misattachment | 9,936 | ✅ **fixed** — `example_owners`; down to 252 |
| D16 | Te Aka example translations absent | 45,939 | `04_te_aka_parse.py` |

## Recommended fix order

1. ~~**D9 + D10 + D11**~~ — ✅ **done 2026-09-10.** 42,135 of 42,189 senses cleared across four
   sources; only papakupu's 54 remain, from a separate pipeline.
2. ~~**D1**~~ — ✅ **done 2026-09-11.** 13,050 Paekupu senses recovered by one projection change, plus a central blank→NULL rule in `add_sense`.
3. **D13 + D14** — tagging and vocabulary; small, mechanical, and unblocks canonical POS
   coverage.
4. **D2 + D3 + D4** — the Williams parser. The largest single body of misplaced content; needs
   care and a fixture-based test suite.
5. ~~**D5 + D6 + D12**~~ — ✅ **done 2026-09-11** (commit `58f388a`), together with D15 and a
   follow-up to the `body_text` NULL rule. **D7 + D8 remain open.**
6. **D16** — verify against the upstream sources before changing anything.

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
