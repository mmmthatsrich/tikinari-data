# Source Update Workflow

How to refresh the Māori dictionary database when a source publishes new data.

**Cadence:** roughly once a year, **one source at a time**. Every source is isolated —
its own scrape/parse/import scripts, its own per-source table, and its own slice of the
unified core — so you update Te Aka in March and Paekupu in September without touching
anything else. There is no "rebuild everything" requirement.

> For the schema these scripts populate, see `DATABASE_REFERENCE.md` (app-builder view)
> and `SCHEMA_PROPOSAL.md` (design rationale).

> **Two databases.** All build scripts here write to **`data/staging_dictionary.db`** (the
> full working DB). The app-serving file **`data/maori_dict.db`** is a slim projection of
> the app surface, rebuilt by `scripts/60_export_app_db.py` — that is the only file copied
> to the app repo. Always run the export as the last step (see *After any update*).

---

## The pipeline (every word-list source)

```
  scrape ─▶ parse(JSON) ─▶ import ─▶  <source>_entries  ─▶ unify ─▶  entry/sense/example/… ─▶ export ─▶ maori_dict.db
  (web/PDF)               (per-src table = raw, curated         (canonical core,             (slim app DB
                           landing zone; cleanups live here)     in staging_dictionary.db)    you copy out)
```

Five stages. Two rules:

1. **Curation lives in the `*_entries` table, not the JSON.** Definition/POS/variant
   cleanups (the `09/10/11` scripts, sessions 36/38/39) edit the table in place. Never
   skip `import` and feed the unified core from JSON — you would resurrect dirty data.
2. **`unify` is a pure, idempotent DB→DB projection.** `scripts/50_build_unified.py
   --source <name>` clears just that source's slice of the core and rebuilds it. Safe to
   re-run any time; it never touches other sources.

Run everything from the repo root with `py scripts/<script>.py`. On Windows set
`PYTHONUTF8=1` (macrons + IPA/Oceanic chars in output).

---

## Before you start

```bash
py scripts/00_init_db.py            # idempotent; ensures all tables/FTS/triggers exist (in staging_dictionary.db)
cp data/staging_dictionary.db data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-<source>   # always back up the working DB
```

---

## Per-source recipes

### Te Aka  (online; supports delta refresh)
```bash
py scripts/04_te_aka_scrape.py            # re-crawl (~hours; resumable)
py scripts/04_te_aka_parse.py             # HTML → te_aka_entries.json
py scripts/04_te_aka_import.py --refresh  # diff vs DB; logs to data_refresh_runs/_log
py scripts/50_build_unified.py --source te_aka
```
`--refresh` computes a `content_hash` per entry and writes new/modified/deleted deltas to
`data_refresh_runs` + `data_refresh_log` instead of a blind reload — this is how you see
"what changed since last year". Omit it for a first/full import.

### Paekupu  (online; supports delta refresh)
```bash
py scripts/04_paekupu_scrape.py           # 2-phase: slugs then word pages (resumable)
py scripts/04_paekupu_parse.py
py scripts/04_paekupu_import.py --refresh
py scripts/50_build_unified.py --source paekupu
```

### He Pātaka Kupu
```bash
py scripts/05_hepataka_scrape.py
py scripts/05_hepataka_parse.py
py scripts/05_hepataka_import.py          # merges + expands source abbreviations at import
py scripts/50_build_unified.py --source hepatakakupu
```

### Williams  (historical; Wayback source)
```bash
py scripts/01_williams_download.py        # 14 section HTML files from the Wayback snapshot
py scripts/01_williams_parse.py           # → williams_entries.json
py scripts/01_williams_import.py
py scripts/50_build_unified.py --source williams
```

### Papakupu o Tai Tokerau  (local PDF + website gap-fill; dialect = Tai Tokerau)
```bash
py scripts/02_papakupu_extract.py         # PyMuPDF text extract → papakupu_entries.json
py scripts/02_papakupu_import.py
# in-DB curation (re-runnable; dry-run by default, --apply to commit, auto-backup):
py scripts/09_papakupu_clean_definitions.py --apply
py scripts/10_papakupu_strip_variant_blocks.py --apply
py scripts/11_papakupu_pos_fix.py --apply
py scripts/50_build_unified.py --source papakupu
```
> Known issue: `02_papakupu_extract.py` drops the **Māori** half of each example, so
> `example.text_mi` is NULL for Papakupu. The schema holds the slot; once the extractor
> fix lands, re-run extract→import→unify and `text_mi` fills in. `dialect='Tai Tokerau'`
> is set automatically from `source_metadata.default_dialect`.

---

## Etymology / comparative layer (NOT part of the unified core)

POLLEX, LPO, and ACD are an etymology layer (cognate sets + reflexes), not word-list
entries — they do **not** go through `50_build_unified.py` (see SCHEMA_PROPOSAL.md §9).
Refresh them on their own:

```bash
py scripts/03_pollex_scrape.py [--entries]   # listing pages, then protoform entry pages
py scripts/03_pollex_import.py               # pollex_entries
py scripts/33_pollex_languages_import.py     # 67-language reference
py scripts/06_lpo_import.py                  # CLDF CSV → lpo_cognatesets
py scripts/07_acd_import.py                  # CLDF CSV → acd_cognatesets
py scripts/08_etymology_linker.py            # POLLEX↔LPO↔ACD links
```

---

## New PDF source (OCR path)

For a scanned dictionary (e.g. Maunsell, He Karao): OCR → parse → curate → import into a
new `<source>_entries` table → add a builder to `50_build_unified.py` → unify. See the
historical scripts `24a/24b` (OCR), `25a/25b` (parse), `25c` (curate). Add the new source
to `source_metadata` (and `default_dialect` if dialectal) in `00_init_db.py`.

---

## After any update (do every time)

```bash
py scripts/06_fts_rebuild.py                 # rebuild FTS if you bulk-edited a table
py scripts/35_detect_pairs.py                # refresh cross-source "also in" candidates
py -m unittest discover -s tests -p "test_*.py"   # all green before you stop
py scripts/60_export_app_db.py               # rebuild the slim app DB (data/maori_dict.db) — copy THIS to the app repo
```

Then update the trackers:
- **`SESSIONS.md`** — add a row: source, row counts, what changed, date (canonical tracker).
- **`DATABASE_REFERENCE.md`** — only if counts or schema changed (it's the app-builder ref).

---

## Quick reference

| Source | scrape | parse | import | unify `--source` |
|--------|--------|-------|--------|------------------|
| Te Aka | `04_te_aka_scrape` | `04_te_aka_parse` | `04_te_aka_import --refresh` | `te_aka` |
| Paekupu | `04_paekupu_scrape` | `04_paekupu_parse` | `04_paekupu_import --refresh` | `paekupu` |
| He Pātaka Kupu | `05_hepataka_scrape` | `05_hepataka_parse` | `05_hepataka_import` | `hepatakakupu` |
| Williams | `01_williams_download` | `01_williams_parse` | `01_williams_import` | `williams` |
| Papakupu | `02_papakupu_extract` | — | `02_papakupu_import` (+09/10/11) | `papakupu` |
| POLLEX/LPO/ACD | `03/—/—` | — | `03/06/07_*_import` | _(etymology layer — no unify)_ |

Run `py scripts/50_build_unified.py` with no `--source` to rebuild the whole core
(all five word-list sources) at once.
