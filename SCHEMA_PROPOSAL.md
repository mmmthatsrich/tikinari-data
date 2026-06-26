# Canonical Database Structure for the Māori Dictionary Aggregator
*Research report — generated 2026-06-21 | Sources: 5 dictionaries analysed in-DB + 4 lexicographic standards | Goal: app-serving SQLite | Confidence: High*

> **Audience / how to read this.** This document is written so that **a separate LLM
> agent can assess the impact of adopting this schema on an existing application that
> currently reads the OLD per-source table structure** (`williams_entries`,
> `te_aka_entries`, `hepatakakupu_entries`, `paekupu_entries`, `papakupu_entries`,
> `pollex_*`, etc.). §1 describes the current/old structure; §3 the proposed structure;
> **§7 is the migration-impact guide** (old→new field map, breaking changes, query
> rewrites, and a backward-compatibility view strategy) — start there if your task is
> "will this break the app and what must change". The proposed core is now **implemented**
> (`entry`/`sense`/`example`/`form`/`relation`/`entry_domain`, built by
> `scripts/50_build_unified.py`) — the old `std_*` review-sample tables and the `std_review`
> view have been removed. The POS normalisation table `std_pos` (§10) is retained in the
> working DB `data/staging_dictionary.db`. Note: the build now lives in two files —
> `staging_dictionary.db` (full working DB) and `maori_dict.db` (slim app projection, built
> by `scripts/60_export_app_db.py`); see `DATABASE_REFERENCE.md`.

> ## Grain refinement update (2026-06-27)
> Williams multi-sense split is now **implemented and shipped**. The Williams parser
> (`scripts/williams_senses.py`) splits numbered senses (i, ii, iii…) into separate
> `sense` rows under a single `entry`; each sense carries its own `sense.part_of_speech`
> (canonical English label from the inline abbreviation). Result: 11,910 Williams entries →
> 20,193 senses (avg 1.70). All other sources remain one-sense-per-entry for now.
>
> POS is now **sense-level** (`sense.part_of_speech`) with an **entry-level wrap-up**
> (`entry.part_of_speech_en` / `entry.part_of_speech_mi`) across all sources. The wrap-up
> deduplicates and joins the canonical labels from the entry's senses via `std_pos`.
> `part_of_speech_mi` is populated only where `std_pos.canonical_mi` is set (Māori terms
> sourced from Paekupu `pos_mi`); He Pātaka Kupu entries have NULL `part_of_speech_mi`
> because HPK POS codes have not yet been added to `std_pos`. The `std_pos` seed covers
> Williams inline abbreviations (66 rows seeded, Māori from Paekupu where matched).

> ## Tikinari amendments (2026-06-25)
> This generic research report has been reviewed against the actual Tikinari app +
> build pipeline. Full analysis: **`docs/SCHEMA_PROPOSAL_APP_IMPACT.md`**. Binding
> decisions that override / qualify the text below:
>
> 1. **§7's premise does not apply to this app.** The Flutter app **never reads the
>    per-source tables** (`*_entries`). It reads a *derived bundle* (`tikinari_app.db`,
>    one unified `entries` table) built by `scripts/build_app_db.py`. The *only* consumer
>    of the per-source tables is that build script. So "breaking at the read layer" lands
>    on `build_app_db.py`'s readers, not app code. The bundle already implements most of
>    this proposal (entry→sense→example, structured examples/variants/synonyms/cross-refs,
>    cross-source links, POLLEX-as-etymology).
> 2. **Entry-id scheme = Option A, `{source}:{source_pk}`** (= `entry.source_entry_id`).
>    The new global integer `entry.id` is an **internal collection-DB surrogate only** and
>    is **never** the device-referenced id. The build mints the stable
>    `{source}:{source_pk}` (split senses suffixed `~n`) so Taku Tikinari / SRS refs,
>    `entry_links`, redirects, and the delta chain survive from-scratch rebuilds. Frozen
>    at launch.
> 3. **TT-boost is dialect-driven, source-set.** `entry` gains a **`dialect`** column
>    (added below). Source sets it (Papakupu → `'Tai Tokerau'`, from `source_metadata`);
>    ranking *reads* `dialect`, never `source` (inviolable rule 5 — any TT-tagged entry
>    floats, not just Papakupu).
> 4. **Pre-launch — adopt in one cut.** No installs in the field, so the full-re-download
>    gating and ID migration costs are nil. Restructure collection, rewrite build readers,
>    split `gloss_en`/`gloss_mi`, add bilingual `example.text_mi`/`text_en`, and normalise
>    POS all in one coordinated change. Post-launch any bundle-column change reverts to a
>    forced full re-download.

## Executive Summary

The DB currently stores each source dictionary in its **own table with its own column
set**. The five word-list sources (`williams_entries`, `te_aka_entries`,
`hepatakakupu_entries`, `paekupu_entries`, `papakupu_entries`) share a rough core
(`headword`, `headword_sort`, `headword_search`, `part_of_speech`, `definition`,
`usage_examples`) but diverge badly on everything else — and, more dangerously, the
**same column means different things in different sources**:

- `definition` is **English** in Te Aka / Williams / Papakupu, **Māori** in He Pātaka
  Kupu, and **both** (split across `definition` + `definition_mi`) in Paekupu.
- `usage_examples` is a flat JSON array of strings, but shaped four incompatible ways:
  Te Aka = *Māori sentence + (citation)*, Papakupu = *English translation only* (the
  Māori half was dropped on extraction — a live bug), Paekupu = *Māori only*, Williams
  = *Māori fragment only*.
- Senses are **per-row** in Williams / He Pātaka Kupu (via `sense_number`) but
  **flattened into one definition blob** in Te Aka / Paekupu / Papakupu.
- Relations are modelled three ways: `synonyms` as linked objects (`{text, word_id}`)
  in Te Aka, `cross_refs` / `see_also` as plain string arrays in Williams / Papakupu.

The four recognised lexicographic data models (OntoLex-Lemon, TEI Lex-0,
Wiktextract/Kaikki) **all converge on the same shape**:
`Entry (lemma + one POS) → Forms (incl. variants) → Senses → (gloss + examples +
labels) + relations + pronunciation + etymology + provenance`.

**Recommendation:** keep one row per source (preserve provenance — do *not* merge
sources into a single "canonical" headword), but converge every source onto a shared
**entry → sense → example** normalised core with explicit language tagging and
structured examples. Link equivalent entries across sources via the existing
`cross_source_candidates` table. This is the pragmatic OntoLex/TEI shape expressed in
flat SQLite, and it directly fixes the language-mixing and lost-Māori-example
problems.

---

## 1. What the sources actually contain (divergence matrix)

| Field / concept        | Williams | Te Aka | He Pātaka Kupu | Paekupu | Papakupu |
|------------------------|:--------:|:------:|:--------------:|:-------:|:--------:|
| rows                   | 11,910   | 47,878 | 24,941         | 16,486  | 4,683    |
| `definition` language  | English  | English| **Māori**      | English | English  |
| Māori monolingual def  | —        | —      | (in `definition`) | `definition_mi` (3,435) | — |
| English headword       | —        | —      | —              | `headword_en` | — |
| senses                 | `sense_number` rows | inline in def | `sense_number` rows | inline | inline |
| examples shape         | Māori frag | Māori + (cite) | inline | Māori only | **English only (Māori lost)** |
| audio                  | —        | `audio_url` | — | `audio_url` | — |
| synonyms               | —        | `synonyms` [{text,word_id}] | `synonyms` | `alternative_words` | — |
| cross-refs / see-also  | `cross_refs` [str] | — | — | — | `see_also` [str] |
| semantic domain        | —        | `filters` | `semantic_domain` | `subject_area(s)` | — |
| variant forms          | —        | — | — | `alternative_words` | `variant_forms` (+ search keys) |
| source citation        | — | `source_citations` | — | — | `source_code` / `loan_marker` |
| provenance locator     | `page_number`, `source_section` | `word_id` | `word_id` | `slug` | `pdf_page` |

**Already well-structured (keep as-is):** the etymology layer
(`pollex_*`, `lpo_*`, `acd_*`, `protoform_ancestry`, `etymology_links`,
`reconstruction_levels`), `source_metadata`, `source_abbreviations`, and
`cross_source_candidates` (181,938 cross-source equivalence pairs). These are good and
the proposal builds on them rather than replacing them.

---

## 2. What the standards converge on

Three independent, widely-used models agree on the hierarchy — strong evidence it is
the right backbone:

- **OntoLex-Lemon** (W3C): a *LexicalEntry* is a word/MWE/affix with a **single POS**,
  one morphological pattern, one etymology, and a **set of senses**; it groups *Forms*
  (surface/variant forms) and *LexicalSenses* (each sense belongs to exactly one
  entry). The Lexicography Module adds grouping components for nested entries/sense
  groups. ([W3C lexicog module](https://www.w3.org/2019/09/lexicog/),
  [DARIAH: Modeling Dictionaries in OntoLex-Lemon](https://campus.dariah.eu/resources/hosted/modeling-dictionaries-in-ontolex-lemon),
  [McCrae et al. 2017](https://john.mccr.ae/papers/mccrae2017ontolex.pdf))
- **TEI Lex-0** (baseline for lexicographic interchange): `entry → form` (headword +
  variant forms) `→ gramGrp` (grammatical info) `→ sense` (nestable for sub-senses)
  containing `def` + `cit` (examples & translations) + `usg` (usage/domain labels) +
  `xr` (cross-references). Homographs are modelled as **nested `<entry>`**, not a flat
  field. ([TEI Lex-0 entries](https://lex-0.org/entries.html), [lex-0.org](https://lex-0.org/))
- **Wiktextract / Kaikki** (the pragmatic JSON model behind machine-readable
  Wiktionary): one record per *(word, POS, etymology)*; `senses[]` each with
  `glosses[]`, `examples[]`, `tags`, `categories`, `links`; plus top-level `forms[]`,
  `sounds[]` (`ipa`, `audio`), `synonyms`, `related`, `translations`, `etymology_text`.
  ([wiktextract README](https://github.com/tatuylonen/wiktextract/blob/master/README.md),
  [kaikki raw data](https://kaikki.org/dictionary/rawdata.html))

Common denominator: **Entry (lemma+POS) → Forms → Senses → {gloss, examples, labels}
→ relations + pronunciation + etymology + provenance.** That is the target shape.

---

## 3. Recommended canonical schema (app-serving SQLite)

Design principles for the app build:
1. **One row per source entry** — never silently merge Te Aka + Williams + … into a
   single headword. Provenance and licence differ per source; merging is lossy and
   politically/contractually risky. Unify the *shape*, link with equivalence.
2. **Normalise senses and examples** into child tables so multi-sense sources
   (Williams, HPK) and inline-sense sources (Te Aka, Paekupu, Papakupu) read the same.
3. **Tag language explicitly** — separate `gloss_en` and `gloss_mi`; never rely on
   "which source is this" to know the definition language.
4. **Keep the original blob** (`definition_raw`) for fidelity/debugging.
5. **FTS over derived columns**, not over the source tables directly.

```sql
-- ── one row per source headword-entry ──────────────────────────────────────────
CREATE TABLE entry (
    id              INTEGER PRIMARY KEY,    -- INTERNAL surrogate only; NOT the device id (amend. 2)
    source_id       TEXT NOT NULL,          -- FK source_metadata.source_id
    source_entry_id TEXT,                   -- original id/word_id/slug; the build mints the stable
                                            --   device id '{source_id}:{source_entry_id}' from this (amend. 2)
    headword        TEXT NOT NULL,
    headword_sort   TEXT NOT NULL,          -- macron-stripped (existing util)
    headword_search TEXT NOT NULL,          -- macron + double-vowel normalised (existing util)
    homonym_no      INTEGER,                -- distinguishes homographs (TEI nested-entry analogue)
    headword_en     TEXT,                   -- Paekupu English headword (bilingual sources)
    part_of_speech  TEXT,                   -- normalised vocabulary (see §5)
    loan_marker     TEXT,                   -- Papakupu
    dialect         TEXT,                   -- e.g. 'Tai Tokerau'; drives the app's dialect boost.
                                            --   Source-defaulted (Papakupu) via source_metadata, with
                                            --   optional per-entry override. Ranking reads this, never
                                            --   source_id (inviolable rule 5). (amend. 3)
    audio_url       TEXT,                   -- Te Aka, Paekupu
    locator         TEXT,                   -- pdf_page / url / source_section, as text
    content_hash    TEXT,
    first_seen      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    last_updated    TEXT DEFAULT (datetime('now'))
);

-- ── variant / alternative / inflected forms ────────────────────────────────────
CREATE TABLE form (
    id          INTEGER PRIMARY KEY,
    entry_id    INTEGER NOT NULL REFERENCES entry(id),
    form        TEXT NOT NULL,
    form_search TEXT NOT NULL,              -- normalised, for matching
    form_type   TEXT,                       -- variant | alt_spelling | plural | inflected
    note        TEXT
);                                          -- ← Papakupu variant_forms, Paekupu alternative_words

-- ── senses (normalises sense_number rows AND inline senses) ─────────────────────
CREATE TABLE sense (
    id              INTEGER PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES entry(id),
    sense_number    INTEGER,
    parent_sense_id INTEGER REFERENCES sense(id),   -- sub-senses (TEI nested sense)
    gloss_en        TEXT,                   -- English gloss (Te Aka/Williams/Papakupu/Paekupu)
    gloss_mi        TEXT,                   -- Māori monolingual gloss (HPK, Paekupu definition_mi)
    definition_raw  TEXT,                   -- original blob, untouched, for fidelity
    register        TEXT                    -- usage label (formal, dialectal, archaic…)
);

-- ── examples (FIXES the lost-Māori-example problem) ─────────────────────────────
CREATE TABLE example (
    id           INTEGER PRIMARY KEY,
    sense_id     INTEGER REFERENCES sense(id),
    entry_id     INTEGER NOT NULL REFERENCES entry(id),   -- denormalised for entry-level fallback
    text_mi      TEXT,                      -- Māori sentence  ← currently dropped for Papakupu
    text_en      TEXT,                      -- English translation
    source_abbrev TEXT,                     -- FK source_abbreviations.abbrev (e.g. TTU, NGH3)
    citation     TEXT,                      -- full citation if present (Te Aka)
    sort_no      INTEGER
);

-- ── relations: synonyms, see-also, cross-refs, antonyms ─────────────────────────
CREATE TABLE relation (
    id              INTEGER PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES entry(id),
    rel_type        TEXT NOT NULL,          -- synonym | see_also | cross_ref | antonym | variant_of
    target_headword TEXT NOT NULL,
    target_entry_id INTEGER REFERENCES entry(id),  -- resolved when possible (Te Aka word_id)
    note            TEXT
);

-- ── domain / subject tags ───────────────────────────────────────────────────────
CREATE TABLE entry_domain (
    id         INTEGER PRIMARY KEY,
    sense_id   INTEGER REFERENCES sense(id),
    entry_id   INTEGER NOT NULL REFERENCES entry(id),
    domain     TEXT NOT NULL,               -- HPK semantic_domain, Paekupu subject_area, Te Aka filters
    domain_lang TEXT                        -- 'mi' | 'en'
);

-- ── FTS over derived columns ────────────────────────────────────────────────────
-- entry_fts(headword, headword_search, forms)         contentless, synced by triggers
-- sense_fts(gloss_en, gloss_mi, definition_raw)
-- example_fts(text_mi, text_en)
```

Unchanged / reused: `source_metadata`, `source_abbreviations`, `personal_lexicon`
(maps onto the same `entry`/`sense`/`example` shape with `is_private`), the whole
etymology stack, and `cross_source_candidates` (now linking `entry.id` ↔ `entry.id`
across sources — this is the "same word in N dictionaries" join the app needs).

---

## 4. Per-source conversion mapping

| Source | → `entry` | → `sense` | → `example` | → `form` / `relation` / `entry_domain` |
|--------|-----------|-----------|-------------|----------------------------------------|
| **Williams** | headword*, POS, `page_number`/`source_section`→`locator` | split `sense_number` rows; `definition`→`gloss_en` | split Māori fragments → `text_mi` | `cross_refs`→`relation(cross_ref)` |
| **Te Aka** | headword, POS, `audio_url`, `word_id`→`source_entry_id` | split inline senses; `definition`→`gloss_en` | parse `usage_examples`: Māori→`text_mi`, trailing `(citation)`→`citation`/`source_abbrev` | `synonyms`→`relation(synonym, target_entry_id=word_id)`; `filters`→`entry_domain` |
| **He Pātaka Kupu** | headword, POS, `word_id` | `sense_number` rows; `definition`→**`gloss_mi`** (monolingual!) | inline | `synonyms`→`relation`; `semantic_domain`→`entry_domain(mi)` |
| **Paekupu** | headword, `headword_en`, POS/`pos_mi`, `audio_url`, `slug` | `definition`→`gloss_en`, `definition_mi`→`gloss_mi` | `usage_examples` (Māori)→`text_mi` | `alternative_words`→`form`; `subject_areas`→`entry_domain` |
| **Papakupu** | headword, POS, `loan_marker`, `source_code`, `pdf_page` | inline senses; `definition`→`gloss_en` | **re-extract Māori sentence→`text_mi`** + existing English→`text_en` + `[SRC]`→`source_abbrev` | `variant_forms`→`form(variant)`; `see_also`→`relation(see_also)` |

\* Williams headwords need macron restoration on import (legacy orthography) — already a known project task.

The **Papakupu example fix** falls straight out of this model: the Māori half is being
discarded at extraction (`02_papakupu_extract.py`), leaving only the English + `[SRC]`.
Under the new `example` table each example carries `text_mi` **and** `text_en`, so the
re-extraction (already planned alongside the run-on fix) must populate both.

---

## 5. Key decisions & trade-offs

1. **Don't merge sources into one canonical headword.** Keep per-source rows; unify
   shape; join via `cross_source_candidates`. Rationale: differing licences, differing
   editorial authority, and merge conflicts (POS, senses) that no rule resolves
   cleanly. The app shows "this word appears in N dictionaries" by querying the link
   table — more useful and more honest than a fabricated merged entry.
2. **Normalise senses now, not later.** Even though three sources flatten senses
   inline, splitting them is what makes cross-source sense comparison and clean display
   possible. Inline-sense sources start with one `sense` row each and can be split
   progressively without schema change.
3. **`gloss_en` + `gloss_mi`, not one `definition` + a language flag.** The app almost
   always wants "give me the English gloss" or "give me the Māori gloss"; two columns
   make that a non-conditional query and remove the per-source language ambiguity that
   exists today.
4. **Structured examples are the highest-value change.** They fix a live data-loss bug
   (Papakupu Māori sentences), make `[SRC]` codes joinable to `source_abbreviations`,
   and enable a "Māori sentence ↔ English translation" UI.
5. **Part-of-speech vocabulary needs normalising** across sources (Williams uses
   abbreviations, Te Aka/Paekupu use words, Papakupu was just cleaned to
   Noun/Verb/Stative/Universal/…). Adopt one controlled vocabulary (the Williams/Te
   Aka grammatical categories: Noun, Verb (transitive/intransitive), Stative,
   Universal, Locative, Particle, …) and map each source to it on import.
6. **Keep FTS contentless and trigger-synced** (as the existing papakupu FTS already
   is) so the normalised tables stay the single source of truth.

---

## 6. Migration path (non-destructive, staged)

1. Build `entry`/`sense`/`example`/`form`/`relation`/`entry_domain` **alongside** the
   existing per-source tables (no drop).
2. Write one importer per source that reads the existing table and populates the
   unified core (pure transform; the source tables remain the raw landing zone).
3. Re-extract Papakupu (and audit Te Aka) so examples carry both `text_mi` and
   `text_en` — folds into the already-planned run-on / extractor fix.
4. Point FTS + the app's read queries at the unified core; keep per-source tables for
   provenance and re-import.
5. Re-home the etymology + cross-source links onto `entry.id`.

This keeps the raw per-source tables as the immutable landing layer and makes the
unified core a rebuildable projection — the same "raw → cleaned projection" pattern the
project already uses for FTS and refresh tracking.

---

## 7. Impact assessment — for an LLM evaluating an existing app on the OLD schema

This section exists so an agent can judge **what breaks and what must change** in an
app that currently queries the old per-source tables.

> **Tikinari note (amend. 1):** this section's premise is **moot for the Tikinari app** —
> it does not query the per-source tables. Only `scripts/build_app_db.py` does. Read the
> field-map and breaking-changes below as a guide for **rewriting the build readers**,
> not the app. Device impact is covered in `docs/SCHEMA_PROPOSAL_APP_IMPACT.md`.

### 7.1 Nature of the change

The proposal is **additive at the storage layer, breaking at the read layer**:
- The old per-source tables are **retained unchanged** as the raw "landing zone"
  (§6). No columns are dropped or renamed in `*_entries`. An app left untouched keeps
  working against the old tables.
- The new value is in the **unified `entry/sense/example/...` core**. An app that
  wants the cross-source benefits (one query surface, structured examples, language-
  tagged glosses, normalised POS) must **migrate its read queries** to the new tables.
- Therefore impact is proportional to **how much the app reads dictionary content
  directly** vs. through a thin data layer. A repository/DAO with a few query methods =
  low impact (rewrite the methods). SQL scattered through the UI = high impact.

### 7.2 Old → new field map (what each old column becomes)

| Old (per-source) | New (unified) | Note for the app |
|---|---|---|
| `*_entries.id` | `entry.source_entry_id` (+ new `entry.id`) | **PK changes.** For Tikinari (amend. 2): the device id is `'{source_id}:{source_entry_id}'`, minted by the build — **not** the new global `entry.id` (which is collection-internal only). |
| `headword`, `headword_sort`, `headword_search` | `entry.*` (same names) | unchanged semantics. |
| `part_of_speech` (315 raw variants) | `entry.part_of_speech` **normalised** via `std_pos` | **Behaviour change:** values are canonicalised (e.g. `n.`,`noun`,`simple noun` → `Noun`). Filters/labels in the app that match raw strings will break — repoint to `std_pos.canonical_en`/`canonical_mi`. |
| `definition` (language varies!) | `sense.gloss_en` **or** `sense.gloss_mi` | **Semantic fix:** HPK `definition` (Māori) → `gloss_mi`; others → `gloss_en`; Paekupu split. App code assuming `definition` is always English is currently wrong for HPK and must switch on language. |
| `definition_mi` (paekupu/HPK col) | `sense.gloss_mi` | consolidated. |
| `usage_examples` (flat JSON string[]) | `example` rows (`text_mi`,`text_en`,`source_abbrev`,`citation`) | **Shape change** from array-of-strings to rows; fixes Papakupu lost-Māori bug. App example rendering must change. |
| `sense_number` (williams/HPK) | `sense.sense_number` | multi-sense now first-class for ALL sources. |
| `variant_forms`, `alternative_words` | `form` rows | array → child rows. |
| `synonyms`, `cross_refs`, `see_also` | `relation` rows (`rel_type`) | three old shapes unified. |
| `semantic_domain`, `subject_area(s)`, `filters` | `entry_domain` rows | unified; `domain_lang` tags mi/en. |
| `audio_url`, `headword_en`, `loan_marker` | `entry.*` (same names) | unchanged. |
| `source_code`, `page_number`, `slug`, `word_id` | `entry.locator` / `entry.source_entry_id` | provenance preserved as text. |
| `pollex_*`, etymology tables | **unchanged** (see §9) | no migration; re-home FK to `entry.id`. |

### 7.3 Breaking changes the app WILL hit (checklist for the assessor)

1. **Primary keys.** New global `entry.id`; old per-source `id` survives only as
   `source_entry_id`. Any bookmark/deep-link/foreign key on the old `id` needs a join.
2. **`definition` is gone as a single column.** Replaced by `gloss_en`/`gloss_mi` on
   `sense`. Every read of `*_entries.definition` must be rewritten, and code must stop
   assuming a single definition string per row (now 1..N senses).
3. **`usage_examples` JSON parsing is gone.** Replaced by `example` rows. Any client
   that `JSON.parse`s `usage_examples` breaks.
4. **POS values change string identity** (normalised). Hard-coded POS filters break.
5. **One headword can now span multiple `sense` rows** even for sources that were
   one-row-per-entry. Pagination/counts that assumed 1 row = 1 entry need `DISTINCT
   entry_id` or group-by.
6. **FTS moves** from per-source FTS tables to `entry_fts`/`sense_fts`/`example_fts`.
   Search queries repoint.

### 7.4 Low-risk adoption path (recommended to the app)

Provide **backward-compatibility views** that reproduce the old shape on top of the new
core, so the app can migrate incrementally instead of in one cut-over:

```sql
-- Emulates the old te_aka_entries shape from the unified core.
CREATE VIEW te_aka_entries_comch AS
SELECT e.source_entry_id AS id, e.headword, e.headword_sort, e.headword_search,
       e.part_of_speech, s.gloss_en AS definition,
       (SELECT json_group_array(coalesce(x.text_mi,x.text_en))
          FROM example x WHERE x.entry_id=e.id) AS usage_examples,
       e.audio_url
FROM entry e JOIN sense s ON s.entry_id=e.id
WHERE e.source_id='te_aka';
```

Assessment heuristic for the other agent: **count the app's distinct read paths to
`*_entries` and to `usage_examples`/`definition`.** That count, times "join vs view
rewrite", is the migration size. If the app already funnels DB access through a small
data layer, this is a few-day change; if not, budget for touching every query site.

---

## 8. Example attribution model (is per-example source common?)

Yes — attribution is **the norm wherever examples are real**, measured across the DB:

| Source | examples | with attribution | form |
|---|---:|---:|---|
| papakupu | 9,693 | **99.9%** | short codes `[TTU]`, `[NGH3]`, `[041126]` |
| te_aka | 46,055 | **51%** | full citation `(Te Toa Takitini 1/3/1930:1992)` |
| hepatakakupu | 24,447 | **42%** | text refs `(W7.72)` |
| paekupu | 9,669 | 0.2% | coined vocab — no citation |
| williams | 159 | 0% | tiny inline fragments |

Two distinct attribution shapes coexist, so the `example` table models **both**:
- **`example.source_abbrev`** → FK to `source_abbreviations` (the short joinable
  informant/text codes; Papakupu + HPK). Lets the app expand `[TTU]` → full name and
  filter examples by source.
- **`example.citation`** → free-text full citation (Te Aka newspaper/manuscript refs)
  that has no controlled-vocabulary code.

Populate whichever the source provides; both may be NULL (Paekupu/Williams). This makes
"show example with its source", "filter by attested source", and "expand abbreviation"
all first-class — none are possible with the current flat string array.

---

## 9. Where POLLEX fits (it is NOT a sixth dictionary)

POLLEX is structurally different from the five word-lists and must **not** be flattened
into `entry`/`sense`/`example`:

- **It has zero usage examples** (`pollex_entries.usage_examples` is empty) — the
  example table does not apply to it.
- Its unit of evidence is the **reflex**: `pollex_reflexes` (49,760 rows = a protoform's
  form in each Polynesian language), and **100% carry `source_author`**. That is
  attribution *per data point*, a different model from per-example attribution.
- Entry-level it stores reconstruction data: `protoform`, `protoform_desc`,
  `maori_reflex`, `maori_gloss`, `cognateset_id`, plus `source_citation` (e.g. "Bgs") +
  `source_author` (e.g. "Bruce Biggs").

**Recommendation:** keep POLLEX as the **etymology / comparative layer it already is**
(`pollex_cognatesets`, `pollex_reflexes`, `protoform_ancestry`, `etymology_links`,
`reconstruction_levels`, `pollex_languages`) — this is already well-modelled. Connect it
to the dictionary core by **linking `entry` ↔ `cognateset`** (via `headword_search`
match and the existing `etymology_links`), not by ingesting POLLEX glosses as entries
(they are lower quality and redundant with Williams/Te Aka). The app surfaces "this word
across 67 Polynesian languages" by `entry → cognateset → pollex_reflexes`.

**Cross-cutting attribution insight:** dictionary `example.source_abbrev`, POLLEX
`reflexes.source_author`, and `pollex_entries.source_citation` all answer "who attests
this". The clean unification is a shared citation/source reference table that all three
FK into — and `source_abbreviations` (145 rows) is already ~80% of that table. Pragmatic
call: **extend `source_abbreviations`** into that shared role (add `author`, broaden
`source_dict` scope) rather than inventing a new table.

---

## 10. Part-of-speech normalisation (`std_pos`)

The five sources use **315 distinct raw `part_of_speech` strings** — abbreviations
(`n.`, `v.t.`), words (`noun`, `transitive verb`), Te Aka compounds (`loan, noun`,
`proper noun - person`), and He Pātaka Kupu's Māori codes (`ing`, `mahp, ing, āhua`).
To normalise **and** translate to Māori, the DB now contains a seeding table:

```sql
CREATE TABLE std_pos (
    id INTEGER PRIMARY KEY,
    raw_pos       TEXT,        -- exact value as stored in a source
    source_counts TEXT,        -- JSON {source_id: count}  (who uses it, how often)
    total_count   INTEGER,
    is_loan       INTEGER,     -- raw value carried a 'loan' marker
    canonical_en  TEXT,        -- normalised English POS (controlled vocabulary)
    canonical_mi  TEXT,        -- Māori translation
    status        TEXT,        -- 'seeded' | 'needs_review'
    notes         TEXT
);
```

State after `scripts/13_build_pos_normalisation.py`:
- **315** distinct raw values captured, one row each, with per-source usage counts.
- **66 seeded** mappings covering **73.7% of all entry-rows** (the high-frequency
  English/abbreviation forms), with Māori from Paekupu's authoritative `pos_mi`:
  `Noun→Tūingoa`, `Verb→Tūmahi`, `Verb (transitive)→Tūmahi whiti`,
  `Verb (intransitive)→Tūmahi poro`, `Stative→Tūāhua`, `Locative→Tūwāhi`.
- **249 `needs_review`**, dominated by He Pātaka Kupu **compound** codes
  (`ing`, `mahp`, `mahw`, `āhua`, `tūkē` …). These are not single POS values — HPK lists
  **every grammatical function a word can take** (e.g. `mahp, ing, āhua` = verb + noun +
  stative). That is a genuinely different (multi-POS) model and needs the HPK legend +
  an expert decision on whether the app stores a primary POS or a set. Left unmapped on
  purpose rather than guessed.

How it plugs in: `entry.part_of_speech` (and a parallel Māori POS field, or a join)
resolves through `std_pos.canonical_en` / `canonical_mi`. The app's POS filters and
labels read the canonical columns; `raw_pos` is retained for provenance and re-mapping.
Workflow: an expert fills `canonical_en`/`canonical_mi` for the `needs_review` rows
(especially the HPK codes), then the importers apply the mapping.

---

## Key Takeaways

- The backbone every standard agrees on — **entry → form → sense → example** with
  explicit language tags and provenance — is the right target, expressed as flat
  SQLite child tables rather than RDF/XML.
- **Two columns are actively lossy/ambiguous today:** `definition` (language varies by
  source) and `usage_examples` (four shapes; Papakupu drops the Māori sentence). Both
  are fixed by `gloss_en`/`gloss_mi` and a structured `example(text_mi, text_en,
  source_abbrev)` table.
- **Preserve per-source rows; unify the shape; link equivalence** via the existing
  `cross_source_candidates` table — don't fabricate a merged canonical headword.
- The etymology layer and cross-source detection are already well-modelled; this
  proposal extends them, it doesn't replace them.

## Sources

1. [W3C — OntoLex Lemon Lexicography Module](https://www.w3.org/2019/09/lexicog/) — entry/sense/component model for dictionaries.
2. [DARIAH — Modeling Dictionaries in OntoLex-Lemon](https://campus.dariah.eu/resources/hosted/modeling-dictionaries-in-ontolex-lemon) — applied modelling tutorial.
3. [McCrae et al. 2017 — The OntoLex-Lemon Model](https://john.mccr.ae/papers/mccrae2017ontolex.pdf) — entry = one POS + forms + senses.
4. [TEI Lex-0 — Entries](https://lex-0.org/entries.html) and [lex-0.org](https://lex-0.org/) — baseline entry/form/sense/cit/usg/xr encoding; nested-entry homographs.
5. [wiktextract README](https://github.com/tatuylonen/wiktextract/blob/master/README.md) and [kaikki raw data](https://kaikki.org/dictionary/rawdata.html) — pragmatic JSON word→senses[]→glosses/examples model.

## Methodology

Analysed the live schema and sampled data of all 5 word-list sources + etymology and
support tables in `data/maori_dict.db`; cross-referenced against 3 lexicographic data
standards (OntoLex-Lemon, TEI Lex-0, Wiktextract/Kaikki) via web search. Sub-questions:
(1) what does each source actually store; (2) where do columns mean different things;
(3) what hierarchy do standards converge on; (4) what app-serving SQLite shape captures
it without losing provenance; (5) how to migrate non-destructively.
