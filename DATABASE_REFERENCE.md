# Māori Dictionary Database — Reference for App Developers

This document describes `data/maori_dict.db` — a SQLite database containing Māori dictionary data from multiple sources, built to be bundled into a mobile app (iOS/Android) with a future web extension.

> **Two databases — copy only `maori_dict.db`.** The repo holds two SQLite files:
> - **`data/maori_dict.db`** — the slim, app-serving database. Contains *only* the
>   surface the app reads: the unified core (`entry`/`sense`/`example`/`form`/
>   `relation`/`entry_domain` + their FTS), the etymology layer (`pollex_cognatesets`/
>   `pollex_reflexes`/`pollex_languages`/`lpo_cognatesets`/`acd_cognatesets`/
>   `etymology_links`/`protoform_ancestry`/`reconstruction_levels`), and the `source_*`
>   support tables. **This is the only file you copy to the app repo.**
> - **`data/staging_dictionary.db`** — the full working/build database (~210 MB):
>   raw per-source `*_entries` landing zone, `pollex_entries`, cross-source candidates,
>   refresh logs, the personal lexicon, and `std_pos`. Never leaves this repo.
>
> `maori_dict.db` is a **rebuildable projection** of staging — regenerate it any time with
> `py scripts/60_export_app_db.py`. Everything below describes tables present in the app DB
> unless a table is explicitly noted as staging-only.

---

## File & Tech Specs

| Property | Value |
|---|---|
| App DB (copy this) | `data/maori_dict.db` — ~117 MB |
| Working/build DB | `data/staging_dictionary.db` — ~210 MB (stays in repo) |
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
| `entry` | 105,898 | one row per source headword-entry; provenance kept (not merged across sources) |
| `sense` | 114,181 | `gloss_en` **and** `gloss_mi` (language-tagged), `definition_raw`, `sense_number`, `part_of_speech` |
| `example` | 90,019 | structured `text_mi` / `text_en` + `source_abbrev` (joins `source_abbreviations`) / `citation` |
| `form` | 12,955 | variant / alternative / inflected forms (`form_search` normalised) |
| `relation` | 103,485 | `synonym` / `see_also` / `cross_ref` (Te Aka synonyms resolved to `target_entry_id`) |
| `entry_domain` | 59,570 | subject / semantic-domain tags (`domain_lang` = mi/en) |

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
- `audio_url`, `headword_en`, `loan_marker`, `locator`, `content_hash`, `first_seen`.

Key columns on `sense`:
- `sense_number` — 1-based integer ordering within the entry. Williams entries are now **multi-sense**:
  the parser splits numbered senses (i, ii, iii…) into separate `sense` rows under a single `entry`.
  Williams has 11,910 entries and 20,193 senses (avg 1.70 senses/entry).
- `part_of_speech` — per-sense POS, drawn from the source. For Williams this is the inline
  abbreviation expanded to a canonical English label (e.g. `n.` → `Noun`); for other sources it
  is the raw passthrough from the per-source table. Used to compute `entry.part_of_speech_en/_mi`.
- `gloss_en` / `gloss_mi` — language-tagged gloss (see language-tagging note below).

Language tagging (the core fix): He Pātaka Kupu glosses are **Māori** → `sense.gloss_mi`
only; Te Aka/Williams/Papakupu → `gloss_en`; Paekupu is bilingual (both). Never infer the
gloss language from the source again.

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

> Note: Papakupu `example.text_mi` is NULL pending the upstream extractor fix (schema holds
> the slot). Williams is now multi-sense (20,193 senses across 11,910 entries); all other
> sources remain one-sense-per-entry.

---

## Sources Overview

| Source ID | Display Name | Entries | Licence | Notes |
|---|---|---|---|---|
| `williams` | Williams Dictionary (1844/1971) | 11,910 | CC BY-SA 3.0 NZ | Open licence; primary source |
| `papakupu` | Papakupu o Tai Tokerau | 4,683 | **For Private Use Only** | Northland dialect; do NOT distribute |
| `pollex` | POLLEX-Online (Māori reflexes) | 3,424 | Permission pending | Etymological; Māori subset |
| `te_aka` | Te Aka Māori Dictionary | 47,878 | **Restricted** | Permissions handled externally |
| `hepatakakupu` | He Pātaka Kupu | 24,941 senses | **Restricted** | Monolingual Māori; permissions externally |
| `paekupu` | Paekupu (curriculum vocabulary) | 16,486 | **Restricted** | Subject-area vocabulary; permissions externally |
| `personal` | Personal Lexicon | 0 (user-filled) | User-owned | User's own words |
| `pollex_cognatesets` | POLLEX protoform records | 2,931 | Permission pending | Research/etymology layer |
| `lpo` | Lexicon of Proto Oceanic | 2,820 | CC-BY-4.0 | Etymology layer |
| `acd` | Austronesian Comparative Dictionary | 10,857 | CC-BY-4.0 | Etymology layer |

**Total searchable entries across dictionary sources: ~108,000**

---

## Dictionary Tables

### `williams_entries` — 11,910 rows

Williams 1957 dictionary, sourced from NZETC TEI HTML. English definitions, usage examples. Plain ASCII headwords (the source inconsistently uses macrons — many headwords lack them, e.g. `Aho` not `āho`). The `headword_search` normalisation handles this transparently.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `headword` | TEXT | Display text; often lacks macrons |
| `headword_sort` | TEXT | Indexed; macrons stripped |
| `headword_search` | TEXT | Indexed; macrons stripped + double vowels collapsed |
| `part_of_speech` | TEXT | Nullable |
| `definition` | TEXT | May contain expanded source abbreviations |
| `usage_examples` | TEXT | JSON array of strings |
| `sense_number` | INTEGER | Stored as Roman numeral text (`"i"`, `"ii"`) due to SQLite dynamic typing |
| `cross_refs` | TEXT | JSON array of strings |
| `page_number` | INTEGER | Page in the 1957 edition |
| `source_section` | TEXT | Letter section: A E H I K M N Ng O P R T U W |
| `created_at` | TEXT | ISO datetime |
| `last_updated` | TEXT | ISO datetime |

FTS table: `williams_fts` — covers `headword`, `definition`, `usage_examples`.

---

### `te_aka_entries` — 47,878 rows

Te Aka Māori-English/English-Māori Dictionary. Largest source. Has audio URLs, synonyms, source citations, and sense-level word filters. Supports incremental refresh.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Internal row ID |
| `word_id` | INTEGER | Te Aka's own ID (used to construct audio URL and for synonym cross-refs) |
| `headword` | TEXT | With macrons |
| `headword_sort` | TEXT | Indexed |
| `headword_search` | TEXT | Indexed |
| `part_of_speech` | TEXT | e.g. `noun`, `verb`, `particle` |
| `definition` | TEXT | Pipe-separated senses: `"1. fishing line \| 2. weft"` |
| `usage_examples` | TEXT | JSON array of strings (source citations pre-expanded) |
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

Three-tier chain tracing Māori words back through proto-languages:

```
pollex_entries (Māori reflex)
    └── pollex_cognatesets (Proto-Polynesian / Proto-Oceanic protoform)
            ├── lpo_cognatesets (Proto-Oceanic, CC-BY-4.0)
            └── acd_cognatesets (Proto-Austronesian/Malayo-Polynesian, CC-BY-4.0)
```

Connected by `etymology_links` — 229 links covering 7.8% of Māori-relevant POLLEX cognatesets (229 / 2,931).

### `pollex_cognatesets` — 3,291 rows (2,931 with Māori reflex + 360 ancestor-only)

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | URL slug (e.g. `"aho"`) |
| `protoform_name` | TEXT | Bare name (e.g. `"AHO"`) |
| `level` | TEXT | Proto-language code (see below) |
| `level_name` | TEXT | Full name (e.g. `"Central-Eastern Polynesian"`) |
| `description` | TEXT | Gloss |
| `reconstruction` | TEXT | Full reconstructed form |
| `notes` | TEXT | POLLEX `*N`-coded cross-refs (`*0 <<`/`>>`, `*1 Cf.`, `*4 POC`, `*6 PAN`…); parsed into `protoform_ancestry` |
| `pollex_url` | TEXT | Source URL |
| `origin` | TEXT | `maori_reflex` (searchable entry) \| `ancestor_only` (higher protoform with no Māori reflex; tree node only). See [Reconstruction & Ancestry](#reconstruction--ancestry-decomposition-tree) |

**Level codes and counts (top 10):**

| Code | Name | Count |
|---|---|---|
| PN | Polynesian | 841 |
| CE | Central-Eastern Polynesian | 492 |
| NP | Nuclear Polynesian | 374 |
| OC | Oceanic | 175 |
| MP | Malayo-Polynesian | 169 |
| AN | Austronesian | 160 |
| TA | Tahitic | 156 |
| EP | Eastern Polynesian | 143 |
| FJ | Fijian | 112 |
| CK | Cook Islands Māori | 79 |

### `pollex_reflexes` — 49,760 rows

Cross-language reflexes across all 67 POLLEX languages (not just Māori). `language_slug` is a FK into `pollex_languages`.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `cognateset_id` | TEXT | FK → `pollex_cognatesets(id)` |
| `language` | TEXT | Language name |
| `language_slug` | TEXT | FK → `pollex_languages(language_slug)` |
| `reflex` | TEXT | The reflex form in that language |
| `gloss` | TEXT | English gloss |
| `source_code` | TEXT | Citation code |
| `source_author` | TEXT | Author name |
| `flags` | TEXT | JSON array (e.g. `["Borrowed"]`) |

### `pollex_languages` — 67 rows

Reference table for every language in the POLLEX dataset. Joined via `language_slug` when you need subgroup or region filtering on reflex queries.

| Column | Type | Notes |
|---|---|---|
| `language_slug` | TEXT PK | Matches `pollex_reflexes.language_slug` |
| `language` | TEXT | Full language name |
| `iso_code` | TEXT | ISO 639-3 code; NULL for extinct/uncertain varieties |
| `subgroup` | TEXT NOT NULL | Indexed; see values below |
| `region` | TEXT | Geographic region (`Pacific` for all current entries) |
| `country_or_island_group` | TEXT | Country or island group |
| `notes` | TEXT | Dialects, alternate names, ISO uncertainty |

Indexed on `subgroup`.

**Subgroup breakdown:**

| Subgroup | Languages |
|---|---|
| Eastern Polynesian | 19 |
| Other Oceanic | 19 |
| Polynesian Outlier | 12 |
| Samoic-Outlier | 8 |
| Tongic | 5 |
| Fijian | 3 |
| Rotuman | 1 |

### `lpo_cognatesets` — 2,820 rows

Proto-Oceanic reconstructions from the Lexicon of Proto Oceanic (CC-BY-4.0).

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | CLDF ID |
| `name` | TEXT | Reconstructed form (no asterisk, e.g. `"Rumaq"`) |
| `name_key` | TEXT | Indexed; normalised form for matching |
| `description` | TEXT | Gloss |
| `level` | TEXT | POc \| PAn \| PMP \| PEOc \| PNGOc \| PEMP \| PCP \| PPT |
| `chapter_id` | TEXT | Chapter reference |
| `chapter_title` | TEXT | Chapter name |

### `acd_cognatesets` — 10,857 rows

Austronesian Comparative Dictionary reconstructions (CC-BY-4.0).

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | CLDF ID |
| `name` | TEXT | Reconstructed form |
| `name_key` | TEXT | Indexed; normalised form for matching |
| `description` | TEXT | Gloss |
| `level` | TEXT | PAN \| PMP \| PWMP \| POC \| PPH \| PCEMP \| PCMP \| PEMP \| PSHWNG |
| `etymon_id` | TEXT | Indexed; groups related reconstructions (PAN + PMP sharing an etymon) |

### `etymology_links` — 229 rows

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `pollex_cognateset_id` | TEXT | FK → `pollex_cognatesets(id)` |
| `lpo_cognateset_id` | TEXT | FK → `lpo_cognatesets(id)`; nullable |
| `acd_cognateset_id` | TEXT | FK → `acd_cognatesets(id)`; nullable |
| `match_confidence` | REAL | 0.0–1.0 |
| `match_method` | TEXT | How the link was found (see below) |
| `lpo_citation` | TEXT | Raw `"LPO N:NNN"` text from POLLEX notes |
| `notes` | TEXT | Curation comments |

**Match methods:**
- `tier2_acd_citation` — ACD form explicitly cited in POLLEX notes (169 links, most reliable)
- `tier2_lpo_citation` — LPO form cited in POLLEX notes (36 links)
- `tier1_formkey` — form-key match at same proto-level (13 links)
- Combinations of the above (11 links)

**Full etymology chain query:**
```sql
SELECT
    pe.headword            AS maori_word,
    pc.protoform_name      AS pollex_proto,
    pc.level_name          AS pollex_level,
    lc.name                AS lpo_form,
    lc.description         AS lpo_gloss,
    ac.name                AS acd_form,
    ac.level               AS acd_level,
    ac.description         AS acd_gloss
FROM pollex_entries pe
JOIN pollex_cognatesets pc ON pe.cognateset_id = pc.id
LEFT JOIN etymology_links el ON el.pollex_cognateset_id = pc.id
LEFT JOIN lpo_cognatesets lc ON el.lpo_cognateset_id = lc.id
LEFT JOIN acd_cognatesets ac ON el.acd_cognateset_id = ac.id
WHERE pe.headword_search = 'aho'
```

---

## Reconstruction & Ancestry (Decomposition Tree)

Layer that lets an app render a **decomposition tree** for a word: the Māori
reflex at the top, its same-level cognates from other languages below, then the
ancestral reconstructions climbing as far back as POLLEX asserts (e.g.
`CE → PN → POc → PAn`). Built by `scripts/pollex_ancestry.py` from POLLEX's own
`*N`-coded cross-references in `pollex_cognatesets.notes` plus the curated
`etymology_links`. POLLEX has **no structured parent pointer** — these tables
derive it.

> **Reality check:** ancestry is sparse *by design*. Most protoforms are
> single-level innovations with **no** higher ancestor (e.g. `CE.PUAGA` "Rigel"
> stops at Central-Eastern). ~1,189 of 2,931 Māori-relevant cognatesets reach a
> higher level; 325 reach Proto-Austronesian. The rest are correctly terminal —
> not a gap to fill.

### `reconstruction_levels` — 25 rows

The Austronesian → Polynesian subgrouping ladder. Lets the app order the
"levels above" axis and validate edges (an ancestor must rank strictly higher).

| Column | Type | Notes |
|---|---|---|
| `code` | TEXT PK | Level code: `AN, MP, OC, EO, RO, CP, FJ, PN, TO, NP, SO, EC, CC, EP, CE, TA, MQ, CK`, + peripheral codes |
| `name` | TEXT | e.g. `Central-Eastern Polynesian` |
| `parent_code` | TEXT | Immediately higher level on the main spine (`AN` has none) |
| `depth_rank` | INTEGER | 0 = deepest (AN) … 12 = shallowest (CK). Bigger = more recent |

### `protoform_ancestry` — ~1,600 rows

Directed edges: a cognateset (child) → its ancestor reconstruction. Walk
`child_id` upward to build the vertical chain.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `child_id` | TEXT | FK → `pollex_cognatesets(id)` |
| `child_level` | TEXT | Level code of the child |
| `ancestor_kind` | TEXT | `pollex` (internal cognateset) \| `lpo` (Proto-Oceanic) \| `acd` (Proto-Austronesian/MP) |
| `ancestor_id` | TEXT | FK → `pollex_cognatesets(id)` / `lpo_cognatesets(id)` / `acd_cognatesets(id)` per `ancestor_kind` |
| `ancestor_level` | TEXT | Level code / `POc` / `PAn/PMP` |
| `relation` | TEXT | `descends` (POLLEX `<<` / external proto) \| `cf` (POLLEX `Cf.` compare) |
| `source` | TEXT | `notes` \| `etymology_links` \| `notes_ext` |
| `confidence` | REAL | `0.95` curated/`<<`, `0.75` internal `Cf.`, `0.7` name-matched external |

Counts: ~706 internal (`pollex`), ~408 `lpo`, ~485 `acd`. Index on `child_id`.

### `pollex_cognatesets.origin` (new column)

| Value | Meaning |
|---|---|
| `maori_reflex` | Original 2,931 sets that have a Māori reflex — searchable dictionary entries |
| `ancestor_only` | ~360 higher-level protoforms fetched from POLLEX that have **no** Māori reflex; exist only as ancestor nodes in the tree |

**App rule:** filter `origin='maori_reflex'` for headword search; use **all** rows when rendering the tree.

### Working tables (reference / audit, safe to ignore in app)

- `pollex_slug_inventory` — 5,680 rows: every POLLEX protoform slug + level, crawled from the site; used to resolve note cross-refs to real slugs.
- `pollex_fetch_log` — audit of ancestor-fetch attempts (resumable scraper state).

### Decomposition-view queries

**1. Same-level cognates (the wide top of the tree)** — every language that shares the reflex, grouped by subgroup:
```sql
SELECT r.language, pl.subgroup, r.reflex, r.gloss, te.audio_url
FROM pollex_reflexes r
LEFT JOIN pollex_languages pl ON pl.language_slug = r.language_slug
WHERE r.cognateset_id = :cognateset_id
ORDER BY pl.subgroup, r.language
```

**2. Ancestral chain (climbing the levels)** — recursive walk up `protoform_ancestry`:
```sql
WITH RECURSIVE up(child_id, ancestor_kind, ancestor_id, ancestor_level, relation, confidence, depth) AS (
    SELECT child_id, ancestor_kind, ancestor_id, ancestor_level, relation, confidence, 1
        FROM protoform_ancestry WHERE child_id = :cognateset_id
    UNION ALL
    SELECT a.child_id, a.ancestor_kind, a.ancestor_id, a.ancestor_level, a.relation, a.confidence, up.depth + 1
        FROM protoform_ancestry a
        JOIN up ON a.child_id = up.ancestor_id AND up.ancestor_kind = 'pollex'
)
SELECT * FROM up ORDER BY depth, confidence DESC
```
Resolve each ancestor node: `ancestor_kind='pollex'` → `pollex_cognatesets`; `'lpo'` → `lpo_cognatesets`; `'acd'` → `acd_cognatesets`. Use `confidence` to grey out tentative (`cf`) links vs solid (`descends`).

**Worked example** — Māori `wahine`:
```
CE.WAHINE  [CE]  "Woman, female"
 └─ AN.FAFINE [AN] "Woman, female"        (descends)
     ├─ POc *papine "woman"   (LPO)       (descends)
     └─ PAn *bahi  "female"   (ACD)       (descends)
```

---

## Supporting Tables

### `source_metadata` — 10 rows

Registry of all data sources.

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

### `cross_source_candidates` — 181,938 rows

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
| HPK × Te Aka | 58,318 |
| HPK × Williams | 31,003 |
| Te Aka × Williams | 22,141 |
| HPK × Papakupu | 17,660 |
| HPK × Paekupu | 14,508 |
| Paekupu × Te Aka | 13,981 |
| Papakupu × Te Aka | 11,595 |
| Papakupu × Williams | 5,455 |
| Paekupu × Williams | 4,415 |
| Paekupu × Papakupu | 2,862 |

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
-- All reflexes for a protoform, annotated with subgroup and location
SELECT pr.reflex, pr.gloss, pl.language, pl.subgroup, pl.country_or_island_group
FROM pollex_cognatesets pc
JOIN pollex_reflexes pr ON pr.cognateset_id = pc.id
JOIN pollex_languages pl ON pl.language_slug = pr.language_slug
WHERE pc.id = 'aho'
ORDER BY pl.subgroup, pl.language

-- Eastern Polynesian reflexes only (narrows to cognate Māori relatives)
SELECT pr.reflex, pr.gloss, pl.language, pl.country_or_island_group
FROM pollex_cognatesets pc
JOIN pollex_reflexes pr ON pr.cognateset_id = pc.id
JOIN pollex_languages pl ON pl.language_slug = pr.language_slug
WHERE pc.id = 'aho'
  AND pl.subgroup = 'Eastern Polynesian'
ORDER BY pl.language
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
| Te Aka | Restricted | Only with permission confirmed |
| He Pātaka Kupu | Restricted | Only with permission confirmed |
| Paekupu | Restricted | Only with permission confirmed |
| Personal Lexicon | User-owned | Yes |

---

## What the App Must Handle

1. **Search normalisation** — implement `normalise_search_key()` in the app language before any `headword_search =` query. Do not query by raw user input.

2. **JSON columns** — `usage_examples`, `synonyms`, `cross_refs`, `variant_forms`, `subject_areas`, `alternative_words`, `filters` are all JSON arrays stored as TEXT. Parse with the platform's JSON library before displaying.

3. **Null checks** — most optional columns (`audio_url`, `definition_mi`, `part_of_speech`, `synonyms`, etc.) may be NULL.

4. **He Pātaka Kupu multi-row headwords** — one headword = potentially many rows (up to 19). Group by `headword_search`, order by `sense_number`.

5. **Audio** — URLs are remote. Not bundled. Requires connectivity to play, or a separate offline audio download step.

6. **DB size** — the app DB (`maori_dict.db`) is ~114 MB and already excludes the raw staging tables (it is the projection built by `scripts/60_export_app_db.py`). The etymology layer (`pollex_reflexes` 49,760 rows, `lpo_cognatesets`, `acd_cognatesets`) is included; if etymology is not a UI feature, dropping those tables from the export is the obvious further slim-down — edit `APP_TABLES` in `60_export_app_db.py`.

7. **WAL mode** — the DB uses WAL journal mode. Open with `PRAGMA journal_mode = WAL` if not already set; use a single shared connection per process.

8. **Cross-source duplicates** — query `cross_source_candidates WHERE status = 'approved' AND headword_search = ?` to surface "also in [source]" cross-links for a headword. Only `approved` rows should be shown; `pending`, `unreviewed`, and `dismissed*` rows are internal pipeline state.
