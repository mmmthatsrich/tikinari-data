# Māori Dictionary Database — Reference for App Developers

This document describes `data/maori_dict.db` — a SQLite database containing Māori dictionary data from multiple sources, built to be bundled into a mobile app (iOS/Android) with a future web extension.

> **Two databases — copy only `maori_dict.db`.** The repo holds two SQLite files:
> - **`data/maori_dict.db`** — the slim, app-serving database. Contains *only* the
>   surface the app reads: the unified core (`entry`/`sense`/`example`/`form`/
>   `relation`/`entry_domain` + their FTS), the **unified etymology layer**
>   (`ETY_level`/`ETY_depth`/`ETY_language`/`ETY_cognateset`/`ETY_reflex`/
>   `ETY_link`/`ETY_entry_link`), and the `source_*` support tables. **This is the only file
>   you copy to the app repo.**
> - **`data/staging_dictionary.db`** — the full working/build database (~390 MB):
>   raw per-source `*_entries` landing zone, `pollex_entries`, the raw per-source
>   etymology tables (`pollex_cognatesets`/`pollex_reflexes`/`pollex_languages`/
>   `lpo_cognatesets`/`acd_cognatesets`/`etymology_links`/`protoform_ancestry`/
>   `reconstruction_levels`/`pollex_entry_links` and the `tregear_*`/`abvd_*`/
>   `walworth_*` staging sets), cross-source candidates, refresh logs, the personal
>   lexicon, and `std_pos`. Never leaves this repo.
>
> **Session 59 hard cutover:** the app DB no longer ships the raw per-source
> etymology tables — they are folded into the unified `ETY_*` layer and kept
> staging-only, with **no backward-compat views**. If your app queried
> `pollex_cognatesets`/`pollex_reflexes`/`etymology_links`/`pollex_entry_links`
> etc. directly, migrate to `ETY_*` (mapping in [Etymology Layer](#etymology-layer)).
>
> `maori_dict.db` is a **rebuildable projection** of staging — regenerate it any time with
> `py scripts/60_export_app_db.py`. Everything below describes tables present in the app DB
> unless a table is explicitly noted as staging-only.

---

## File & Tech Specs

| Property | Value |
|---|---|
| App DB (copy this) | `data/maori_dict.db` — ~166 MB |
| Working/build DB | `data/staging_dictionary.db` — ~390 MB (stays in repo) |
| Format | SQLite 3 with WAL journal mode |
| FTS engine | FTS5 (built into SQLite) |
| Encoding | UTF-8 throughout |
| Build the app DB | `py scripts/60_export_app_db.py` |
| Python utility module | `scripts/utils.py` |

---

## The Three Headword Columns (Read This First)

Every dictionary table has three headword columns. Understanding them is essential for building search correctly.

| Column | Purpose | Example for *āho* |
|---|---|---|
| `headword` | Display text — canonical macron spelling | `āho` |
| `headword_sort` | Sort key — macrons stripped, lowercase | `aho` |
| `headword_search` | Search key — macrons stripped AND double vowels collapsed | `aho` |

### Why `headword_search` exists

Māori spelling has two conventions for long vowels:
- Modern: macron — `ā`
- Traditional: double vowel — `aa`

A user might type `āho`, `aaho`, or `aho` and expect the same result. The `headword_search` column normalises all three to `aho` so a single equality lookup finds the entry regardless of which convention the user typed.

The normalisation rules:
1. Strip macrons (NFD decompose, remove combining marks)
2. Collapse consecutive identical vowels: `aa→a`, `ee→e`, `ii→i`, `oo→o`, `uu→u`
3. Note: `ao`, `ae`, etc. are NOT collapsed — only true double vowels

**Critical:** `headword_search` does NOT understand `kaokao` → `kaokao` (the `ao` pair is left alone). The rule is strictly per-vowel-identity: collapse `aa`→`a` but leave `ao` unchanged.

### Applying this in the app

Before querying by headword, normalise the user's input the same way:

```python
# Python (from utils.py)
import unicodedata, re

def normalise_search_key(text: str) -> str:
    text = unicodedata.normalize('NFD', text.lower().strip())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')  # strip macrons
    return re.sub(r'([aeiou])\1+', r'\1', text)  # collapse double vowels
```

For Swift/Kotlin/JS the logic is the same: NFD decompose → strip combining characters → regex collapse.

**Query pattern for headword lookup:**
```sql
SELECT * FROM te_aka_entries WHERE headword_search = ? LIMIT 1
```
where `?` is the user input after normalisation.

---

## Canonical Unified Core (`entry` / `sense` / `example` / …) — the app read surface

The per-source `*_entries` tables (documented below) are the **raw, curated landing
zone**. On top of them sits a **unified core** that gives every source one shape, with the
two long-standing ambiguities fixed: language-tagged glosses and structured bilingual
examples. **Build the app against this core**, not the per-source tables. It is a
**rebuildable projection** — regenerate any source's slice with
`py scripts/50_build_unified.py --source <name>` (see `docs/UPDATE_WORKFLOW.md`).
Full rationale: `SCHEMA_PROPOSAL.md`.

| Table | Rows | What it holds |
|---|---|---|
| `entry` | 111,205 | one row per source headword-entry; provenance kept (not merged across sources) |
| `sense` | 132,416 | `gloss_en` **and** `gloss_mi` (language-tagged), `definition_raw`, `sense_number`, `part_of_speech` |
| `example` | 92,690 | structured `text_mi` / `text_en` + `source_abbrev` (joins `source_abbreviations`) / `citation` |
| `form` | 12,955 | variant / alternative / inflected forms (`form_search` normalised) |
| `relation` | 107,870 | `synonym` / `see_also` / `cross_ref` / `citation` (Te Aka synonyms resolved to `target_entry_id`; Williams `‖` refs → `see_also` headword links + `citation` literature refs, e.g. `J. vii, 120`). Williams `see_also` rows are resolved to `target_entry_id` at build (3,490 / 4,230 = 83%): multi-target strings like `mataaho, tiaho` are split into one row each, `(i)`/`(ii)` sense pointers prefer the matching homograph, and cognate/citation/relative pointers (`Tah, ao`, `J. vii, 120`, `6, below`) stay NULL with the raw text kept in `note`. The app renders resolved rows as clickable links and unresolved rows as plain text |
| `entry_domain` | 57,617 | subject / semantic-domain tags (`domain_lang` = mi/en). Subject areas **only** — Te Aka's loan marker moved to `entry.loan_marker` and Te Māra Reo's proto-levels to the `ETY_*` layer. Paekupu tags each entry in **both** languages (`Pūtaiao` / `Science`); He Pātaka Kupu is Māori-only, since its atua-based scheme has no English form in the source |

Key columns on `entry`:
- `source_id` + `source_entry_id` — provenance. The device id is `'{source_id}:{source_entry_id}'`
  (minted downstream); `source_entry_id` is unique within a source. `entry.id` is an
  **internal surrogate only** and is volatile across rebuilds — never reference it from the device.
- `headword_search` / `headword_sort` — same normalisation as the per-source tables.
- `part_of_speech` — deduped raw POS set across the entry's senses (e.g. `n., v.t.`). Canonical
  labels are in `part_of_speech_en`/`part_of_speech_mi` below.
- `part_of_speech_en` — **entry-level POS wrap-up (English).** Deduped, comma-joined canonical
  English labels drawn from the entry's senses' `sense.part_of_speech` values via `std_pos`.
  Present wherever at least one sense has a `std_pos` canonical mapping.
- `part_of_speech_mi` — **entry-level POS wrap-up (Māori).** Same dedup/join, but only where
  `std_pos.canonical_mi` is populated (i.e. the Māori term was matched from Paekupu). NULL when
  no Māori term is recorded for any of the entry's POS values (e.g. He Pātaka Kupu entries whose
  POS codes have not yet been added to `std_pos`).
- `dialect` — e.g. `'Tai Tokerau'` (Papakupu). **Ranking/boost reads `dialect`, never `source_id`.**
- `loan_marker` — register/etymology label, e.g. `'Historical Loan Word'` (18,439 Te Aka
  entries). **Read it here, not from `entry_domain`**: it used to be written as a semantic
  domain, where it was the single most common "domain" in the database. `entry_domain` is
  subject areas only.
- `audio_url`, `headword_en`, `locator`, `content_hash`, `first_seen`.

Key columns on `sense`:
- `sense_number` — 1-based integer ordering within the entry. **Williams and Te Aka are multi-sense**:
  numbered senses are split into separate `sense` rows under a single `entry`. Williams: 14,942
  entries → 24,556 senses (avg 1.64). Te Aka: 47,888 entries → 59,485 senses (avg 1.24); exact
  duplicate senses in the source are collapsed and survivors renumbered 1..n.
- `part_of_speech` — per-sense POS, drawn from the source. Williams: inline abbreviation expanded
  to a canonical English label (e.g. `n.` → `Noun`). Te Aka: the genuine per-sense POS recovered
  from the raw HTML (e.g. a verb entry whose later senses are nouns keeps `verb` on senses 1–6 and
  `noun` on 7–10). Other sources: raw passthrough from the per-source table. Used to compute
  `entry.part_of_speech_en/_mi`. ~1,911 Te Aka senses (3.2%) have NULL POS where the source omits it.
- `gloss_en` / `gloss_mi` — language-tagged gloss (see language-tagging note below).

Language tagging (the core fix): He Pātaka Kupu glosses are **Māori** → `sense.gloss_mi`
only; Te Aka/Williams/Papakupu/TaiKupu → `gloss_en`; Paekupu is bilingual (both). Never infer the
gloss language from the source again.

Paekupu has a short description on only 3,436 of its 16,486 entries. For the other 13,050 the
sense's `gloss_en` is the entry's own `headword_en` — the English term the Māori word was
coined for, which is the gloss for a term bank. No app-side fallback to `entry.headword_en` is
needed; every Paekupu sense carries a gloss. Absent text is always NULL, never `''`.

FTS over the core: `entry_fts(headword, headword_search)`, `sense_fts(gloss_en, gloss_mi,
definition_raw)`, `example_fts(text_mi, text_en)` — external-content, trigger-synced.

**Example app query — full entry with senses + examples:**
```sql
SELECT e.headword, e.dialect, s.sense_number, s.gloss_en, s.gloss_mi,
       x.text_mi, x.text_en, x.source_abbrev
FROM entry e
JOIN sense s   ON s.entry_id = e.id
LEFT JOIN example x ON x.sense_id = s.id
WHERE e.headword_search = ?            -- normalise_search_key(user input)
ORDER BY e.source_id, s.sense_number, x.sort_no;
```

> Note: Papakupu examples are bilingual — `example.text_mi` (Māori) and `example.text_en`
> (English) are both populated (10,071 of 10,211 have text_mi; the Māori half is recovered
> by an orthography heuristic at extraction). Williams (24,556 senses / 14,942 entries) and
> Te Aka (59,485 senses / 47,888 entries)
> are multi-sense with per-sense POS and per-sense examples; the remaining sources are
> one-sense-per-entry.

---

## Sources Overview

| Source ID | Display Name | Entries | Licence | Notes |
|---|---|---|---|---|
| `williams` | Williams Dictionary (1844/1971) | 14,942 | CC BY-SA 3.0 NZ | Open licence; primary source |
| `papakupu` | Papakupu o Tai Tokerau | 4,683 | **For Private Use Only** | Northland dialect; do NOT distribute |
| `taikupu` | Papakupu o Tai Tokerau | 2,265 | Used with permission | Ngāpuhi vocab (Māori Minute); shown under the Papakupu banner (same `display_name`); Tai Tokerau dialect |
| `pollex` | POLLEX-Online (Māori reflexes) | 3,424 | Permission pending | Etymological; Māori subset |
| `te_aka` | Te Aka Māori Dictionary | 47,888 | **Restricted** | Permissions handled externally |
| `hepatakakupu` | He Pātaka Kupu | 24,941 senses | **Restricted** | Monolingual Māori; permissions externally |
| `paekupu` | Paekupu (curriculum vocabulary) | 16,486 | **Restricted** | Subject-area vocabulary; permissions externally |
| `personal` | Personal Lexicon | 0 (user-filled) | User-owned | User's own words |
| `pollex_cognatesets` | POLLEX protoform records | 3,291 | Permission pending | Research/etymology layer |
| `lpo` | Lexicon of Proto Oceanic | 2,820 | CC-BY-4.0 | Etymology layer |
| `acd` | Austronesian Comparative Dictionary | 10,857 | CC-BY-4.0 | Etymology layer |
| `temarareo` | Te Māra Reo (The Language Garden) | 203 | CC BY-NC 3.0 NZ | Māori plant names + Proto-Polynesian etymologies (Benton); unifies AND feeds `ETY_*` |

**Total searchable entries across dictionary sources: ~111,000** (unified `entry` = 111,205)

### Te Māra Reo tables (staging)

`temarareo_entries` (203) is the only slice that unifies. The other three are the
comparative layer, projected into `ETY_*` by `52_build_etymology_unified.py`:

| Table | Rows | What it holds |
|---|---|---|
| `temarareo_entries` | 203 | Māori plant names. 101 have their own page (definition, species, related names); 102 come only from the index and carry that row's species as their gloss — `has_page` tells them apart. |
| `temarareo_cognatesets` | 122 | Protoform records: 111 from `PPN-*.html` pages, 11 derived from name pages whose protoform has no page of its own. |
| `temarareo_reflexes` | 1,363 | Per-language comparative witnesses across 130 languages (1,167 Polynesian, 196 wider Austronesian). One row per (page, language), Tregear-style. |
| `temarareo_chain` | 431 | Ordered reconstruction steps (PAn → PMP → POc → PPn). Becomes `ETY_link` ancestry edges with `origin = 'temarareo_chain'`. |

Two source-side caveats are recorded rather than papered over:

- **The index's name↔species pairing is not recoverable.** Columns 2 and 3 of
  `TMR-Ingoa.html` are aligned only visually with `<br/>` runs that do not
  correspond one-to-one (the `*fara` row has 7 names against 9 species lines), so
  species are stored as an unordered list per row. Authoritative pairings come from
  the individual pages.
- **16 level names have no `ETY_level` code.** They are Benton's own finer
  subdivisions — Proto South/East/Central Eastern Pacific, Proto Pre-Polynesian,
  Proto Rarotongan-Māori — which the ladder does not carry. `level_code` is NULL
  and the name is preserved in `level_name` / `ETY_cognateset.notes`.

---

## Dictionary Tables

### `williams_entries` — 14,942 rows

Williams 1957 dictionary, sourced from NZETC TEI HTML. English definitions, usage examples. Plain ASCII headwords (the source inconsistently uses macrons — many headwords lack them, e.g. `Aho` not `āho`). The `headword_search` normalisation handles this transparently.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Deterministic, assigned by `assign_ids()` in `01_williams_import.py`: main headwords 1–11,910 (positional, stable across re-imports); recovered sub-/hang-headwords (paragraph-initial, S65) `1_000_000 + parent_main_id*100 + k` for `k = 1..49` (e.g. `piriahi` = 1694401 under `Piri` 6944); `subx` mid-paragraph recoveries (glued behind the parent's prose, S66) take the same formula with `k = 50 + j` (`j` 1-based per parent, e.g. `whakahinuhinu` = 1000000 + `Hinu`'s main id \*100 + 51; 37 rows post-S66-fix — a same-session false-positive split (`nawai`, a Taranaki dialect-cognate citation misread as a derivative of `Nāwai` because `_related()` trivially passed on raw-key identity) was reclaimed back into its parent and never occupied a stable id). Referenced by `cross_source_candidates` and the device id — never renumbered. |
| `headword` | TEXT | Display text; often lacks macrons |
| `headword_sort` | TEXT | Indexed; macrons stripped |
| `headword_search` | TEXT | Indexed; macrons stripped + double vowels collapsed |
| `part_of_speech` | TEXT | Nullable |
| `definition` | TEXT | May contain expanded source abbreviations |
| `usage_examples` | TEXT | JSON array of strings |
| `sense_number` | INTEGER | Stored as Roman numeral text (`"i"`, `"ii"`) due to SQLite dynamic typing |
| `cross_refs` | TEXT | JSON array of `{"type","target"}` objects extracted from the `‖` ("compare") marker. `type` is `see_also` (Māori headword ref, e.g. `apa (i), 2`) or `citation` (literature ref, e.g. `J. vii, 120`). Exploded into unified `relation` rows by `50_build_unified.py`. Pure-pointer entries get a synthesised `Cf. <targets>.` definition |
| `page_number` | INTEGER | Page in the 1957 edition |
| `source_section` | TEXT | Letter section: A E H I K M N Ng O P R T U W |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `williams_fts` — covers `headword`, `definition`, `usage_examples`.

---

### `te_aka_entries` — 47,888 rows

Te Aka Māori-English/English-Māori Dictionary. Largest source. Has audio URLs, synonyms, source citations, and sense-level word filters. Supports incremental refresh.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Internal row ID |
| `word_id` | INTEGER | Te Aka's own ID (used to construct audio URL and for synonym cross-refs) |
| `headword` | TEXT | With macrons |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `part_of_speech` | TEXT | Entry-level POS (first sense's), e.g. `noun`, `verb`, `particle`. Per-sense POS lives in `senses` |
| `definition` | TEXT | Legacy pipe-separated senses: `"1. fishing line \| 2. weft"` — kept for FTS/back-compat. Authoritative per-sense data is in `senses` |
| `senses` | TEXT | JSON array, one object per sense: `{"sense_number", "part_of_speech", "gloss_en", "definition_raw", "examples", "citations", "synonyms"}`. `gloss_en` has the leading passive marker `(-ia,-ngia)` stripped (kept in `definition_raw`). Exploded into unified `sense`/`example` rows by `50_build_unified.py` |
| `usage_examples` | TEXT | JSON array of all examples flat (source citations pre-expanded); per-sense examples are in `senses[].examples` |
| `audio_url` | TEXT | MP3 URL on Google Cloud Storage — 58.6% of entries have audio |
| `synonyms` | TEXT | JSON array of `{"text": "raina", "word_id": 6429}` objects |
| `source_citations` | TEXT | JSON array of expanded citation strings |
| `filters` | TEXT | JSON array of word-level labels e.g. `["Historical Loan Word"]` |
| `content_hash` | TEXT | SHA-256 of material fields; used for incremental refresh diffing |
| `first_seen` | TEXT | ISO datetime of first import |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `te_aka_fts` — covers `headword`, `definition`, `usage_examples`.

**Audio:** URLs follow the pattern `https://storage.googleapis.com/maori-dictionary-prod2-web-assets/public/{word_id}.mp3`. Files are not bundled — the app must stream them or download them separately for offline use.

**Synonyms:** `word_id` in each synonym object is a Te Aka `word_id` and can be used to look up the synonym entry:
```sql
SELECT headword, definition FROM te_aka_entries WHERE word_id = 6429
```

---

### `hepatakakupu_entries` — 24,941 rows (12,638 headwords × avg 1.97 senses)

He Pātaka Kupu — monolingual Māori dictionary. One row per **sense**, not per headword. Multiple rows share the same `headword` and `word_id` (grouped by sense number). No English definitions — Māori only.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `word_id` | INTEGER | He Pātaka Kupu's own ID |
| `headword` | TEXT | With macrons |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `part_of_speech` | TEXT | Māori abbreviations: `ing` (noun), `mahw`/`mahp` (verb types), `āhua` (adjective), `pīi` (particle), `hono` (conjunction), `pāt` (interrogative) |
| `definition` | TEXT | In Māori only |
| `usage_examples` | TEXT | JSON array; source citations pre-expanded |
| `sense_number` | INTEGER | 1-based; max 19 for highly polysemous words |
| `synonyms` | TEXT | JSON array of synonym strings |
| `semantic_domain` | TEXT | Māori deity domain (see below) |
| `suffixes` | TEXT | `DEFAULT '[]'`; JSON array of suffix tokens as the source wrote them |
| `definition_mi` | TEXT | NULL — field reserved for future use |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `hepatakakupu_fts` — covers `headword`, `definition`, `usage_examples`.

**Semantic domains** (Māori deity classification system):

| Domain | Count |
|---|---|
| Tāne | 8,823 |
| Tūmatauenga | 5,149 |
| Ranginui & Papatūānuku | 2,369 |
| Tangaroa | 1,832 |
| Ranginui | 1,664 |
| Papatūānuku | 1,461 |
| Tāwhirimātea | 1,057 |
| Rongo | 885 |

**Grouping senses for display:**
```sql
SELECT * FROM hepatakakupu_entries
WHERE headword_search = ?
ORDER BY sense_number
```

---

### `paekupu_entries` — 16,486 rows

Paekupu curriculum vocabulary — bilingual (Māori + English), organised by subject area. Excellent audio coverage (99.7%). Has alternative spellings/forms.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `slug` | TEXT UNIQUE | URL slug used as stable key (e.g. `pae-whakatipu`) |
| `headword` | TEXT | Māori headword (not always same as slug) |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `headword_en` | TEXT | English headword (e.g. `growth plate`) |
| `part_of_speech` | TEXT | English label |
| `pos_mi` | TEXT | Māori POS label |
| `subject_area` | TEXT | Primary subject (Māori); one of 9 values |
| `subject_area_en` | TEXT | Primary subject (English) |
| `subject_areas` | TEXT | JSON array of all subject slugs this entry appears in |
| `audio_url` | TEXT | MP3 or M4A URL — 99.7% populated |
| `definition_mi` | TEXT | Short Māori description (~20.8% populated) |
| `definition` | TEXT | Short English description |
| `alternative_words` | TEXT | JSON array of alternative Māori spellings/forms |
| `usage_examples` | TEXT | JSON array of example sentences |
| `content_hash` | TEXT | SHA-256 for refresh diffing |
| `first_seen` | TEXT | ISO datetime of first import |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `paekupu_fts` — covers `headword`, `definition`, `usage_examples`.

**Subject areas:**

| Māori | English | Count |
|---|---|---|
| Tikanga ā-Iwi | Social Sciences | 2,933 |
| Hangarau | Technology | 2,929 |
| Hauora | Health | 2,924 |
| Pūtaiao | Science | 2,302 |
| Ngā Toi | Arts | 2,195 |
| Te Reo Matatini | Literacy | 1,118 |
| Pāngarau | Mathematics | 1,088 |
| Para Kore | Environmental Sustainability | 531 |
| Mātauranga Whānui | General Knowledge | 466 |

---

### `papakupu_entries` — 4,683 rows

Papakupu o Tai Tokerau — Northland (Tai Tokerau) dialect dictionary, extracted from PDF. Includes variant forms (double-vowel alternates). **Licence: For Private Use Only — cannot be distributed in a public app.**

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `headword` | TEXT | With macrons |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `part_of_speech` | TEXT | Nullable |
| `definition` | TEXT | Leading `{source_code}` and `[part_of_speech]` tokens already captured in their own columns have been stripped (see cleanup note below). Per-sense duplicate codes, uppercase example-attribution codes (`[TTU]`, `[NGH3]`), date codes (`[041126]`) and sense refs (`[1]`) are retained. |
| `usage_examples` | TEXT | JSON array |
| `variant_forms` | TEXT | JSON array of alternate spellings (e.g. `["aapiha", "apiha"]` for `āpiha`) |
| `variant_search_keys` | TEXT | JSON array of normalised search keys for all variant forms |
| `source_code` | TEXT | Contributor/informant code (e.g. `WAI`, `NKM`) — not expandable. Some rows hold page/citation codes (e.g. `117/T`, `52/DN`) from the session-6b WRRT terminology import; these were never `{..}` tokens in the definition text. |
| `loan_marker` | TEXT | Marks loanword entries |
| `see_also` | TEXT | JSON array of cross-reference headwords |
| `pdf_page` | INTEGER | Page in the source PDF |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `papakupu_fts` — covers `headword`, `definition`, `usage_examples`.

**Definition cleanup:** The PDF extraction left structured metadata inline in `definition`. The leading source code (`{RK2}`) and part-of-speech (`[Noun]`) tokens — which are already stored in `source_code` / `part_of_speech` — have been stripped (`scripts/09_papakupu_clean_definitions.py`; 3,774 of 4,683 rows). Only the single extracted occurrence is removed, so repeated per-sense codes survive. Definitions are display-ready prose.

### `taikupu_entries` — 2,265 rows

TaiKupu — a Ngāpuhi vocab app on the Māori Minute platform, imported with the owner's permission from its public JSON API (`GET https://maoriminute.com/api/dictionary`). Same Northland (Tai Tokerau) dialect as Papakupu, and **shown in-app under the same source banner** — `source_metadata.display_name` is `'Papakupu o Tai Tokerau'`, identical to `papakupu`, and `default_dialect='Tai Tokerau'` so it gets the same dialect boost. Storage is a separate table; only the display label is shared.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Local rowid |
| `source_entry_id` | TEXT UNIQUE | TaiKupu API id (e.g. `e_1780218354352_y91cn1`); stable across refreshes; drives the device id `taikupu:{source_entry_id}` |
| `headword` | TEXT | `maori`; with macrons (proper orthography) |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `part_of_speech` | TEXT | Present in the API but currently always empty → NULL |
| `definition` | TEXT | English gloss |
| `usage_examples` | TEXT | JSON array of `{text_mi, text_en}` (one bilingual example per entry) |
| `level` | INTEGER | Learning poutama position 1–100 (not linguistic) |
| `notes` | TEXT | Rarely populated |
| `content_hash` | TEXT | For refresh diffing |
| `first_seen` | TEXT | ISO datetime |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `taikupu_fts` — covers `headword`, `definition`, `usage_examples`.

**Homographs:** duplicate `headword` values are distinct senses (e.g. `ao` = "the world" / "to scoop up"), not duplicate rows — no dedup is applied. **Refresh:** `scripts/40_taikupu_import.py --version-check` compares the local `version` against the live API; `--download` refreshes the raw JSON before importing.

**Variant search:** To find an entry by any of its variant spellings:
```sql
SELECT * FROM papakupu_entries
WHERE headword_search = ?
   OR variant_search_keys LIKE '%"' || ? || '"%'
```
where both `?` are the normalised search key.

---

### `pollex_entries` — 3,424 rows

POLLEX-Online — Māori reflexes of reconstructed Proto-Polynesian forms. Etymological resource. Headwords are plain ASCII (no macrons in source).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `headword` | TEXT | Plain ASCII Māori reflex |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `part_of_speech` | TEXT | Nullable |
| `definition` | TEXT | English gloss of the reflex |
| `usage_examples` | TEXT | JSON array |
| `protoform` | TEXT | Reconstructed protoform (e.g. `*AHO`) |
| `protoform_desc` | TEXT | Description of the protoform entry |
| `maori_reflex` | TEXT | The Māori reflex form |
| `maori_gloss` | TEXT | English gloss |
| `source_citation` | TEXT | Raw citation code |
| `source_author` | TEXT | Expanded author name |
| `cognateset_id` | TEXT | FK → `pollex_cognatesets(id)` |
| `pollex_url` | TEXT | Source URL |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `pollex_fts` — covers `headword`, `definition`, `usage_examples`.

---

### `personal_lexicon` — 0 rows (user-filled at runtime)

User's own words. The CRUD module is in `scripts/05_personal_lexicon_crud.py` (class `PersonalLexicon`). The app should implement its own interface over this table.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `headword` | TEXT | |
| `headword_sort` | TEXT | |
| `headword_search` | TEXT | |
| `part_of_speech` | TEXT | |
| `definition` | TEXT | |
| `usage_examples` | TEXT | JSON array |
| `tags` | TEXT | JSON array of user-defined tags |
| `pronunciation` | TEXT | User's phonetic note |
| `source_note` | TEXT | Where the user found this word |
| `is_private` | INTEGER | 0 = visible, 1 = hidden |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `personal_fts` — covers `headword`, `definition`, `usage_examples`.

---

## Full-Text Search (FTS5)

Every dictionary table has a corresponding FTS5 virtual table, kept in sync by INSERT/UPDATE/DELETE triggers.

| FTS Table | Content Table |
|---|---|
| `williams_fts` | `williams_entries` |
| `papakupu_fts` | `papakupu_entries` |
| `taikupu_fts` | `taikupu_entries` |
| `pollex_fts` | `pollex_entries` |
| `te_aka_fts` | `te_aka_entries` |
| `hepatakakupu_fts` | `hepatakakupu_entries` |
| `paekupu_fts` | `paekupu_entries` |
| `personal_fts` | `personal_lexicon` |

**FTS columns indexed:** `headword`, `definition`, `usage_examples` for all tables.

**Query syntax:**
```sql
-- Exact term
SELECT headword, definition FROM te_aka_fts WHERE te_aka_fts MATCH 'rope'

-- Prefix search
SELECT headword FROM williams_fts WHERE williams_fts MATCH 'ahor*'

-- Phrase
SELECT headword FROM te_aka_fts WHERE te_aka_fts MATCH '"fishing line"'
```

**Important:** FTS search is NOT macron-aware by default. The `unicode61` tokenizer treats `ā` and `a` as different characters. For macron-tolerant full-text search, run FTS on the normalised content, or combine FTS with `headword_search =` lookup.

**Rebuild FTS** (if ever needed): `py scripts/06_fts_rebuild.py`

---

## Etymology Layer

**Unified `ETY_*` layer (session 59 hard cutover).** Every comparative source —
POLLEX, LPO, ACD, Tregear (1891, public domain), ABVD (CC-BY-4.0) and Walworth
(CC-BY-4.0, gap-fill only) — is projected into six normalised tables. The raw
per-source tables (`pollex_cognatesets`, `pollex_reflexes`, `pollex_languages`,
`lpo_cognatesets`, `acd_cognatesets`, `etymology_links`, `pollex_entry_links`,
`protoform_ancestry`, `reconstruction_levels`) are **staging-only** and no longer
shipped in the app DB, with no backward-compat views.

```
entry (a Māori word the user looked up)
  └── ETY_entry_link ── ETY_cognateset (a reconstructed protoform / cognate set)
                            ├── ETY_reflex   (one language's reflex of the set)
                            └── ETY_link     (set ↔ set: ancestry / equivalence)
      ETY_language / ETY_level / ETY_depth — reference tables (languages, level ladder, per-rank label)
```

Provenance is inline: `ETY_cognateset.source` / `ETY_reflex.source` name the
originating source (`pollex|lpo|acd|tregear|abvd|walworth`); `gap_fill=1` marks
Walworth rows promoted only to fill a novel gap; `source_ref` is the raw row id
for traceback into staging.

> **Surrogate ids are volatile.** `ETY_cognateset.id` / `ETY_reflex.id` are
> integer surrogates re-minted on every rebuild. Never persist them client-side —
> re-resolve through `ETY_entry_link` / `source`+`source_ref`.

### Migration from the old raw tables

| Old app table | Now query |
|---|---|
| `pollex_cognatesets` / `lpo_cognatesets` / `acd_cognatesets` | `ETY_cognateset` (filter `source=`) |
| `pollex_reflexes` | `ETY_reflex WHERE source='pollex'` |
| `pollex_languages` | `ETY_language WHERE source='pollex'` |
| `reconstruction_levels` | `ETY_level` |
| `etymology_links` + `protoform_ancestry` | `ETY_link` |
| `pollex_entry_links` | `ETY_entry_link WHERE source='pollex'` (all sources: drop the filter) |

### `ETY_cognateset` — 29,823 rows (1 per reconstructed protoform / cognate set)

By source: ACD 10,857 · Tregear 9,638 · POLLEX 3,291 · ABVD 3,020 · LPO 2,820 · Walworth 197 (gap-fill).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Surrogate — **volatile across rebuilds** |
| `source` | TEXT | `pollex\|lpo\|acd\|tregear\|abvd\|walworth` |
| `source_ref` | TEXT | Raw cognateset id (traceback into staging) |
| `protoform` | TEXT | Reconstructed form / set name |
| `proto_key` | TEXT | `normalise_proto_key(protoform)`; cross-source dedup key (NULL for ABVD attested-concept sets) |
| `level` | TEXT | Level code → `ETY_level.code` (not FK-enforced) |
| `gloss` | TEXT | Description / gloss |
| `set_group` | TEXT | ACD `etymon_id` / LPO `chapter_id` (ancestry grouping) |
| `notes` | TEXT | |
| `url` | TEXT | Source URL |
| `gap_fill` | INTEGER | 1 = Walworth novel-gap promotion; else 0 |

Indexed on `source`, `proto_key`, `source_ref`, `level`.

### `ETY_reflex` — 256,402 rows (1 per language reflex of a set)

By source: ABVD 181,023 · POLLEX 49,760 · Tregear 22,201 · Walworth 3,418. 13,642 are Māori reflexes (`lang_key='maori'`).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Surrogate — volatile across rebuilds |
| `cognateset_id` | INTEGER | FK → `ETY_cognateset(id)` |
| `source` | TEXT | `pollex\|abvd\|tregear\|walworth` |
| `source_ref` | TEXT | Raw reflex/form id |
| `lang_key` | TEXT | → `ETY_language.lang_key` (e.g. `maori`) |
| `language` | TEXT | Display name |
| `form` | TEXT | The reflex form |
| `gloss` | TEXT | English gloss |
| `source_code` | TEXT | Citation code (POLLEX) |
| `source_author` | TEXT | Author name |
| `flags` | TEXT | JSON array |
| `gap_fill` | INTEGER | 1 = Walworth; else 0 |

Indexed on `cognateset_id`, `lang_key`, `source`.

### `ETY_language` — 2,067 rows (reference)

By source: ABVD 1,807 · Tregear 186 · POLLEX 67 · Walworth 7. Joined via `lang_key` for subgroup / region filtering on reflex queries.

| Column | Type | Notes |
|---|---|---|
| `lang_key` | TEXT PK | Language slug/key (POLLEX `language_slug`) |
| `name` | TEXT | Full language name |
| `iso_code` | TEXT | ISO 639-3; NULL where uncertain |
| `subgroup` | TEXT | e.g. `Tongic`, `Eastern Polynesian`, `Samoic-Outlier` |
| `region` | TEXT | Geographic region |
| `country` | TEXT | Country / island group |
| `notes` | TEXT | Dialects, alternate names, ISO uncertainty |
| `source` | TEXT | `pollex\|abvd\|tregear\|walworth` |

Indexed on `subgroup`.

### `ETY_level` — 87 rows (reference)

The Austronesian → Polynesian subgrouping ladder — order the "levels above" axis and validate that an ancestor ranks strictly higher. Covers both the POLLEX 2-letter codes AND the ACD/LPO raw codes (`PAN, PMP, POc, PWMP, PPH`, Micronesian/Melanesian subgroups, …), so every `ETY_cognateset.level` resolves a `depth_rank`.

| Column | Type | Notes |
|---|---|---|
| `code` | TEXT PK | `AN, MP, OC, EO, RO, CP, … PN, NP, CE, TA, CK` + ACD/LPO codes + peripheral |
| `name` | TEXT | e.g. `Central-Eastern Polynesian` |
| `parent_code` | TEXT | Next level up on the spine (`AN` has none) |
| `depth_rank` | INTEGER | 0 = deepest (AN); bigger = more recent; NULL for attested-language tags |

### `ETY_depth` — 14 rows (reference)

One clean display label per `depth_rank` (many `ETY_level.code`s share a rank). Join `ETY_level.depth_rank = ETY_depth.depth_rank` for readable sort/group output instead of an alphabetical `MIN(name)` pick.

| Column | Type | Notes |
|---|---|---|
| `depth_rank` | INTEGER PK | 0 = deepest (AN) … 12 = Cook Islands Maori; 99 = Loans/Unknown |
| `label` | TEXT | Māori-lineage spine name for the rung, e.g. `Polynesian` |
| `spine_code` | TEXT | Representative `ETY_level.code` (NULL for rank 99) |

```sql
-- deepest-first cognate-set counts with clean labels
SELECT d.depth_rank, d.label, COUNT(*)
FROM ETY_cognateset cs JOIN ETY_level l ON l.code = cs.level
JOIN ETY_depth d ON d.depth_rank = l.depth_rank
GROUP BY d.depth_rank ORDER BY d.depth_rank;
```

### `ETY_link` — 2,076 rows (set ↔ set)

Cross-set relations: `descends_from` 981, `same_as` 718, `cf` 377. By origin: `protoform_ancestry` 1,358, `etymology_links` 376, `dedup` 342 (cross-source protoform-key merges).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `source_set_id` | INTEGER | FK → `ETY_cognateset(id)` |
| `target_set_id` | INTEGER | FK → `ETY_cognateset(id)`; nullable |
| `link_type` | TEXT | `ancestry\|equivalence\|cross_ref` |
| `relation` | TEXT | `cf\|descends_from\|same_as` |
| `match_confidence` | REAL | 0.0–1.0 |
| `match_method` | TEXT | How the link was found |
| `origin` | TEXT | `etymology_links\|protoform_ancestry\|dedup\|notes` |
| `notes` | TEXT | |

Indexed on `source_set_id`, `target_set_id`.

### `ETY_entry_link` — 120,003 rows (reflex → unified `entry` bridge)

Reverse bridge from a **Māori reflex** to a row in the unified `entry` table,
matched by macron-neutral headword (`normalise_search_key`). This is how the app
goes from *a word the user searched* to its proto-tree. By source: Tregear 64,243
· POLLEX 49,967 · ABVD 4,804 · Walworth 989. Reaches 43,198 distinct entries
(the S63 TaiKupu entries added new link targets).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `cognateset_id` | INTEGER | FK → `ETY_cognateset(id)` |
| `reflex_id` | INTEGER | FK → `ETY_reflex(id)`; the specific Māori reflex matched (nullable) |
| `entry_id` | INTEGER | FK → `entry(id)` |
| `source` | TEXT | Etymology source that produced the bridge |
| `match_key` | TEXT | The `normalise_search_key` value that matched (= `entry.headword_search`) |
| `match_method` | TEXT | e.g. `headword_exact` |
| `match_confidence` | REAL | 1.0 for exact normalised match |

Indexed on `cognateset_id`, `entry_id`.

**Entry → proto-tree query:**
```sql
SELECT cs.protoform, cs.level, cs.gloss, cs.source
FROM entry e
JOIN ETY_entry_link el ON el.entry_id = e.id
JOIN ETY_cognateset cs ON cs.id = el.cognateset_id
WHERE e.headword_search = 'aho';
```

**Full cross-source chain (equivalent sets + ancestors):**
```sql
SELECT cs.source, cs.protoform, cs.level, cs.gloss,
       lk.link_type, lk.relation,
       tgt.source AS to_source, tgt.protoform AS to_protoform, tgt.gloss AS to_gloss
FROM entry e
JOIN ETY_entry_link el  ON el.entry_id = e.id
JOIN ETY_cognateset cs  ON cs.id = el.cognateset_id
LEFT JOIN ETY_link lk        ON lk.source_set_id = cs.id
LEFT JOIN ETY_cognateset tgt ON tgt.id = lk.target_set_id
WHERE e.headword_search = 'aho';
```

---

## Reconstruction & Ancestry (Decomposition Tree)

Render a **decomposition tree** for a word: the Māori reflex at the top, its
same-level cognates from other languages below, then the ancestral reconstructions
climbing as far back as the sources assert. All of this now lives in `ETY_*`:
`ETY_reflex` (the wide top — sibling-language reflexes of a set), `ETY_link`
(`link_type='ancestry'` edges climbing the levels, plus `equivalence` edges tying
equivalent sets across POLLEX/LPO/ACD), and `ETY_level` (the level ladder for
ordering / validating "higher = older").

> **Reality check:** ancestry is sparse *by design*. Most protoforms are
> single-level innovations with **no** higher ancestor and are correctly
> terminal — not a gap to fill.

**1. Same-level cognates (wide top of the tree)** — every language sharing the set, by subgroup:
```sql
SELECT r.language, l.subgroup, r.form, r.gloss
FROM ETY_reflex r
LEFT JOIN ETY_language l ON l.lang_key = r.lang_key
WHERE r.cognateset_id = :cognateset_id
ORDER BY l.subgroup, r.language;
```

**2. Ancestral / equivalent sets (climbing + cross-source)** — walk `ETY_link` from the set:
```sql
WITH RECURSIVE up(sid, tid, link_type, relation, depth) AS (
    SELECT source_set_id, target_set_id, link_type, relation, 1
        FROM ETY_link WHERE source_set_id = :cognateset_id
    UNION ALL
    SELECT k.source_set_id, k.target_set_id, k.link_type, k.relation, up.depth + 1
        FROM ETY_link k JOIN up ON k.source_set_id = up.tid
)
SELECT u.depth, u.link_type, u.relation,
       cs.source, cs.protoform, cs.level, cs.gloss
FROM up u JOIN ETY_cognateset cs ON cs.id = u.tid
ORDER BY u.depth;
```
Order ancestors by `ETY_level.depth_rank` (bigger = more recent); grey out tentative (`relation='cf'`) vs solid (`descends_from`) links.

---

## Supporting Tables

### `source_metadata` — 14 rows

Registry of all data sources (6 word-list sources + `personal` + the 7 etymology
sources: `pollex`, `pollex_cognatesets`, `lpo`, `acd`, `abvd`, `walworth`, `tregear`).

| Column | Type |
|---|---|
| `source_id` | TEXT PK |
| `display_name` | TEXT |
| `licence` | TEXT |
| `url` | TEXT |
| `last_updated` | TEXT |
| `entry_count` | INTEGER |
| `notes` | TEXT |

### `source_abbreviations` — 145 rows

Expanded inline citation abbreviations, pre-applied at import time. Stored for reference.

| Column | Type | Notes |
|---|---|---|
| `abbrev` | TEXT | e.g. `"TTR"`, `"J."` |
| `source_dict` | TEXT | Which dictionary uses it (`te_aka`, `williams`, `hepatakakupu`) |
| `full_name` | TEXT | e.g. `"Ngā Tāngata Taumata Rau"` |
| `pub_type` | TEXT | `newspaper` \| `book` \| `journal` \| `curriculum` \| `reference` \| `other` |
| `year_range` | TEXT | e.g. `"1921-1932"` |
| `notes` | TEXT | |

Counts: Te Aka — 90, He Pātaka Kupu — 47, Williams — 8.

**Note:** The `usage_examples` and `source_citations` text in Te Aka, Williams, and He Pātaka Kupu entries already has abbreviations expanded at import time. The app reads expanded text directly — no runtime expansion needed.

### `cross_source_candidates` — 213,867 rows

Detected cross-source duplicate pairs — entries in two different dictionaries sharing the same normalised headword. Detected algorithmically, AI-reviewed by Claude Code, then optionally confirmed by a human reviewer. The app reads `approved` rows to surface "also in [source]" cross-links.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `headword_search` | TEXT | Normalised search key shared by both entries |
| `source_a` | TEXT | Lower-ranked source per canonical ordering |
| `entry_id_a` | INTEGER | Row ID in `{source_a}_entries` |
| `source_b` | TEXT | Higher-ranked source |
| `entry_id_b` | INTEGER | Row ID in `{source_b}_entries` |
| `status` | TEXT | `unreviewed` → `pending` or `dismissed_by_ai` → `approved` or `dismissed` |
| `ai_reasoning` | TEXT | Claude Code's reasoning when setting status |
| `detected_at` | TEXT | ISO datetime of detection |
| `reviewed_at` | TEXT | ISO datetime of human review |
| `review_notes` | TEXT | Human reviewer notes |

UNIQUE on `(source_a, entry_id_a, source_b, entry_id_b)`. Indexed on `status` and `headword_search`.

**Source pair breakdown:**

| Pair | Count |
|---|---|
| HPK × Te Aka | 58,334 |
| HPK × Williams | 37,338 |
| Te Aka × Williams | 26,218 |
| HPK × Papakupu | 17,660 |
| HPK × Paekupu | 14,508 |
| Paekupu × Te Aka | 13,981 |
| Papakupu × Te Aka | 11,596 |
| HPK × TaiKupu | 7,976 |
| Papakupu × Williams | 6,527 |
| TaiKupu × Te Aka | 5,243 |
| Paekupu × Williams | 5,254 |
| Paekupu × Papakupu | 2,862 |
| TaiKupu × Williams | 2,934 |
| Papakupu × TaiKupu | 2,100 |
| Paekupu × TaiKupu | 1,336 |

### `cross_source_detection_runs`

Audit log — one row per run of `35_detect_pairs.py`.

| Column | Type |
|---|---|
| `id` | INTEGER PK |
| `run_at` | TEXT |
| `new_pairs` | INTEGER |
| `skipped_existing` | INTEGER |
| `notes` | TEXT |

---

### `data_refresh_runs` and `data_refresh_log`

Track incremental updates for Te Aka and Paekupu.

`data_refresh_runs` — one row per refresh import run:

| Column | Type |
|---|---|
| `id` | INTEGER PK |
| `source_dict` | TEXT |
| `run_at` | TEXT |
| `new_count` | INTEGER |
| `modified_count` | INTEGER |
| `deleted_count` | INTEGER |
| `unchanged_count` | INTEGER |
| `total_scraped` | INTEGER |
| `notes` | TEXT |

`data_refresh_log` — one row per changed entry within a run:

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER | FK → `data_refresh_runs(id)` |
| `source_dict` | TEXT | |
| `entry_key` | TEXT | `word_id` for Te Aka; `slug` for Paekupu |
| `headword` | TEXT | |
| `change_type` | TEXT | `new` \| `modified` \| `deleted` |
| `changed_fields` | TEXT | JSON array of field names (modified only) |
| `old_values` | TEXT | JSON object of old field values |
| `new_values` | TEXT | JSON object of new field values |
| `logged_at` | TEXT | ISO datetime |

---

## Common App Query Patterns

### Headword lookup (exact, any source)
```sql
-- Normalise the user's input first, then:
SELECT 'te_aka' AS source, headword, definition, audio_url
    FROM te_aka_entries WHERE headword_search = ?
UNION ALL
SELECT 'williams', headword, definition, NULL
    FROM williams_entries WHERE headword_search = ?
UNION ALL
SELECT 'hepatakakupu', headword, definition, NULL
    FROM hepatakakupu_entries WHERE headword_search = ?
ORDER BY source
```

### Full-text search across all sources
```sql
SELECT 'te_aka' AS source, headword, definition
    FROM te_aka_fts WHERE te_aka_fts MATCH ?
UNION ALL
SELECT 'williams', headword, definition
    FROM williams_fts WHERE williams_fts MATCH ?
```

### Curriculum vocabulary by subject area
```sql
SELECT headword, headword_en, definition, audio_url
FROM paekupu_entries
WHERE subject_area = 'Hauora'
ORDER BY headword_sort
```

### All senses for a He Pātaka Kupu headword
```sql
SELECT sense_number, part_of_speech, definition, usage_examples, synonyms
FROM hepatakakupu_entries
WHERE headword_search = ?
ORDER BY sense_number
```

### Fetch Te Aka synonyms for a word
```sql
-- Get synonyms for word_id=79 (aho)
SELECT te2.headword, te2.definition
FROM te_aka_entries te1
JOIN te_aka_entries te2
    ON json_extract(value, '$.word_id') = te2.word_id
    CROSS JOIN json_each(te1.synonyms)
WHERE te1.word_id = 79
```

### Cross-language reflexes with subgroup filtering
```sql
-- All reflexes for a cognate set, annotated with subgroup and location
SELECT r.form, r.gloss, l.name AS language, l.subgroup, l.country
FROM ETY_cognateset cs
JOIN ETY_reflex r   ON r.cognateset_id = cs.id
LEFT JOIN ETY_language l ON l.lang_key = r.lang_key
WHERE cs.source = 'pollex' AND cs.source_ref = 'aho'
ORDER BY l.subgroup, l.name;

-- Eastern Polynesian reflexes only (narrows to cognate Māori relatives)
SELECT r.form, r.gloss, l.name AS language, l.country
FROM ETY_cognateset cs
JOIN ETY_reflex r   ON r.cognateset_id = cs.id
JOIN ETY_language l ON l.lang_key = r.lang_key
WHERE cs.source = 'pollex' AND cs.source_ref = 'aho'
  AND l.subgroup = 'Eastern Polynesian'
ORDER BY l.name;
```

### Cross-source duplicate lookup (app "also in" panel)
```sql
-- Find approved cross-source matches for a headword
SELECT source_a, entry_id_a, source_b, entry_id_b
FROM cross_source_candidates
WHERE headword_search = ?
  AND status = 'approved'
```

---

## Licensing Summary

| Source | Licence | Can ship publicly? |
|---|---|---|
| Williams | CC BY-SA 3.0 NZ | Yes (with attribution + share-alike) |
| LPO / ACD | CC-BY-4.0 | Yes (with attribution) |
| POLLEX | Permission pending | Clarify before shipping |
| Papakupu | For Private Use Only | **No** |
| TaiKupu | Used with permission (Māori Minute / Ngāpuhi) | Yes — per owner permission; shown under the Papakupu banner |
| Te Aka | Restricted | Only with permission confirmed |
| He Pātaka Kupu | Restricted | Only with permission confirmed |
| Paekupu | Restricted | Only with permission confirmed |
| Te Māra Reo | CC BY-NC 3.0 NZ | Yes — attribution required, **non-commercial only** |
| Personal Lexicon | User-owned | Yes |

---

## What the App Must Handle

1. **Search normalisation** — implement `normalise_search_key()` in the app language before any `headword_search =` query. Do not query by raw user input.

2. **JSON columns** — `usage_examples`, `synonyms`, `cross_refs`, `variant_forms`, `subject_areas`, `alternative_words`, `filters` are all JSON arrays stored as TEXT. Parse with the platform's JSON library before displaying.

3. **Null checks** — most optional columns (`audio_url`, `definition_mi`, `part_of_speech`, `synonyms`, etc.) may be NULL.

4. **He Pātaka Kupu multi-row headwords** — one headword = potentially many rows (up to 19). Group by `headword_search`, order by `sense_number`.

5. **Audio** — URLs are remote. Not bundled. Requires connectivity to play, or a separate offline audio download step.

6. **DB size** — the app DB (`maori_dict.db`) is ~166 MB and already excludes the raw staging tables (it is the projection built by `scripts/60_export_app_db.py`). The unified etymology layer (`ETY_reflex` 256,402 rows, `ETY_entry_link` 120,003, `ETY_cognateset` 29,823) is the bulk of it; if etymology is not a UI feature, dropping the `ETY_*` tables from the export is the obvious further slim-down — remove them from `APP_TABLES` in `60_export_app_db.py`.

7. **WAL mode** — the DB uses WAL journal mode. Open with `PRAGMA journal_mode = WAL` if not already set; use a single shared connection per process.

8. **Cross-source duplicates** — query `cross_source_candidates WHERE status = 'approved' AND headword_search = ?` to surface "also in [source]" cross-links for a headword. Only `approved` rows should be shown; `pending`, `unreviewed`, and `dismissed*` rows are internal pipeline state.
