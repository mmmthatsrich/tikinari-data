# Design — Williams multi-sense split + sense-level POS with entry wrap-up

*Date: 2026-06-27 · Status: awaiting spec review · Scope: dictionary collection DB (`staging_dictionary.db` → `maori_dict.db`)*

## Goal

1. Split each Williams `definition` (one raw string holding numbered senses) into one
   `sense` row per sense, using the existing `sense.sense_number`.
2. Move part-of-speech to the **sense** level (Williams states POS per sense, with a
   carry-over convention).
3. Make the **entry-level POS a rolled-up set of its senses' POS**, displayed in both
   **English and Māori**.

This is a structural POS change for the whole core; the sense-*splitting parser* is
Williams-only for now.

## Locked decisions

- **Split layer:** in the unify projection (`build_williams` in `scripts/50_build_unified.py`).
  `williams_entries` stays raw, one row per headword. Senses are produced when building the
  core — rebuildable, re-runnable.
- **POS model (all sources):** `sense.part_of_speech` holds the raw abbrev; the entry holds a
  deduped, ordered canonical set in English **and** Māori.
- **Canonical labels:** drawn from `std_pos` (`canonical_en` / `canonical_mi`), which is
  already largely seeded and consistent. New/gap rows are **drafted here for review** (below)
  before being applied.
- **Sense-splitting parser:** Williams now; other sources keep their single sense (their entry
  POS wraps up that one sense). Re-unify **all** sources so the new columns populate everywhere.
- **Out of scope:** homonyms (`entry.homonym_no`, Williams roman numerals); full `std_pos`
  expert review of the 249 `needs_review` rows; per-sense example association.

## Schema changes (`scripts/00_init_db.py`)

Add to the `CREATE TABLE` statements **and** apply idempotently to the existing
`staging_dictionary.db` (because `CREATE TABLE IF NOT EXISTS` will not alter an existing table):

- `sense.part_of_speech TEXT` — raw abbrev, e.g. `v.t.` (NULL where unknown).
- `entry.part_of_speech_en TEXT` — deduped, source-order canonical English set, e.g.
  `Noun, Verb (transitive)`.
- `entry.part_of_speech_mi TEXT` — same set in Māori, e.g. `Tūingoa, Tūmahi whiti`.
- Keep the existing `entry.part_of_speech` column, now holding the deduped **raw** set (was a
  single raw value) for back-compat.

Migration helper: a guarded `_add_column(conn, table, col, decl)` that checks
`PRAGMA table_info` before `ALTER TABLE … ADD COLUMN`. Runs every `00_init_db.py` invocation.

`scripts/60_export_app_db.py` needs **no change** — it recreates schema from staging's
`sqlite_master` and copies rows with `SELECT *`, so the new columns flow through automatically.

## New module — `scripts/williams_senses.py` (pure, unit-testable, no DB)

```
split_senses(definition: str) -> list[dict]
    # each: {sense_number:int, part_of_speech:str|None, gloss_en:str, definition_raw:str}
```

Algorithm:
1. Locate sense markers with `(?:^|[.)]\s)(\d+)\.\s`; keep only the longest run forming a
   strictly increasing `1,2,3,…` sequence. This rejects page numbers inside citations
   (`…Comparative Dictionary 99). `) — they don't form the 1..N run.
2. No valid sequence → a single sense = the whole definition.
3. Per chunk: strip the leading `N.`; detect an optional leading POS token against a **closed
   Williams abbreviation set** (below). `pass.` and `fig.` are register/usage markers, **not**
   POS — left in the gloss text.
4. **Carry-over:** a chunk with no explicit POS inherits the previous chunk's POS (Williams
   convention). Sense 1 with none → NULL.
5. `gloss_en` = chunk minus the `N.` marker and POS token, trimmed. `definition_raw` = chunk
   verbatim (keeps inline example sentences + citations).

Closed Williams POS-abbrev set (from the data):
`n. a. v. v.t. v.i. ad. pt. pl. pos. int. num. pron. def. indef. prefix. l.n.`
(Counts confirm `n./a./v.t./v.i.` dominate; the rest are long-tail.)

## `build_williams` change (`scripts/50_build_unified.py`)

- Replace the single `add_sense(eid, sn, d, None, d)` with:
  `for s in split_senses(d): add_sense(eid, s["sense_number"], gloss_en=s["gloss_en"], gloss_mi=None, definition_raw=s["definition_raw"], part_of_speech=s["part_of_speech"])`.
- `add_sense` signature gains `part_of_speech=None`, writes the new column.
- Examples: `usage_examples` is a flat list (not sense-tagged) → attach all to **sense 1**
  (today they attach to the lone sense). Documented simplification; no data loss.

## Entry POS wrap-up (all sources) — `scripts/50_build_unified.py`

After a source's senses are built, for each entry compute:
- `pos_raw_set` = senses' `part_of_speech`, deduped, in sense order.
- `part_of_speech_en` = each raw → `std_pos.canonical_en`, deduped in order, joined `", "`.
- `part_of_speech_mi` = same via `std_pos.canonical_mi`.
- Unmapped raw POS contributes nothing to the canonical columns; if no sense maps, the en/mi
  columns are NULL (raw set still present in `entry.part_of_speech`).

`std_pos` is loaded once into a dict at the start of the run. Non-Williams sources feed their
single existing POS through the same wrap-up, so the columns populate everywhere their POS is
mapped.

## `std_pos` additions/fixes (apply via a small seeding step before re-unify)

**Approved.** `canonical_mi` is sourced from Paekupu `pos_mi` where it matches (Title-cased to
match the existing seeded convention: `tūingoa`→`Tūingoa`); otherwise left NULL until expert
terms are supplied.

Already mapped & consistent (reuse, no change): `n.`→Noun/Tūingoa · `a.`→Modifier/Tūāhua ·
`v.`→Verb/Tūmahi · `v.t.`→Verb (transitive)/Tūmahi whiti · `v.i.`→Verb (intransitive)/Tūmahi
poro · `pron.`→Pronoun · `int.`→Interjection.

`ad.`→Adverb: set `canonical_mi = Tūkē` (from Paekupu `pos_mi`).

New/gap rows to add:

| raw | canonical_en | canonical_mi | source |
|----|----|----|----|
| `l.n.` | Locative | Tūwāhi | reuse / Paekupu `tūwāhi` |
| `pt.` | Particle | NULL | no Paekupu match |
| `pos.` | Determiner (possessive) | NULL | no Paekupu match |
| `def.` | Determiner (definite) | NULL | no Paekupu match |
| `indef.` | Determiner (indefinite) | NULL | no Paekupu match |
| `prefix.` | Prefix | NULL | no Paekupu match |
| `num.` | Numeral | NULL | no Paekupu match |

Paekupu `pos_mi` covers only: Noun→Tūingoa, Adjective/Modifier→Tūāhua, Transitive
Verb→Tūmahi whiti, Intransitive Verb→Tūmahi poro, Verb→Tūmahi, Neuter Verb→Tūmahi oti,
Adverb→Tūkē, Locative→Tūwāhi (+ `adverb (time)`→Tūwā). Everything else keeps
`canonical_mi = NULL`, so those entries get the **English** wrap-up and a partial/NULL Māori
wrap-up until expert terms land. No further Māori terms invented.

## Impact / counts

- `entry` williams unchanged (11,910 — still one entry per headword).
- `sense` grows: ~3,958 multi-sense Williams rows expand to multiple senses (williams senses
  ~11,910 → estimated ~24k; exact reported after the run). Other sources unchanged in count.
- New columns populated for every re-unified source where POS maps.
- App read surface (`maori_dict.db`) gains `sense.part_of_speech`, `entry.part_of_speech_en`,
  `entry.part_of_speech_mi` after the next export.

## Testing

- `tests/test_williams_senses.py` (unit, no DB): `Pae` (5 senses, POS `n.` then carry-over),
  `Rere` (`v.i.` carry-over across senses), citation-with-digits not mis-split, single-sense
  leading-POS extraction, no-POS → NULL.
- Extend `tests/test_unified.py`: a known multi-sense Williams entry yields N senses with
  sequential `sense_number`; `sense.part_of_speech` populated; `entry.part_of_speech_en/mi`
  are deduped sets; non-Williams entry still 1 sense with wrap-up populated.
- Full suite green → re-unify all sources → `60_export_app_db.py` → re-verify.

## Rollout

1. Add columns + migration (`00_init_db.py`); run it.
2. Apply approved `std_pos` additions.
3. Add `williams_senses.py`; wire into `build_williams`; add the entry wrap-up.
4. Tests green.
5. `py scripts/50_build_unified.py` (all sources) → `py scripts/60_export_app_db.py`.
6. Update `DATABASE_REFERENCE.md` (POS model), `SESSIONS.md`, `SCHEMA_PROPOSAL.md`.
