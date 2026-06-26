---
name: update-dictionary
description: Use when refreshing the Māori dictionary DB from a source (Te Aka, Paekupu, He Pātaka Kupu, Williams, Papakupu, or POLLEX/LPO/ACD) after that source publishes new data — runs the scrape→parse→import→unify pipeline for ONE source at a time, then verifies. Triggers: "update <source>", "refresh the dictionary", "re-import te aka", "annual update".
---

# Update a dictionary source

Refresh one source's data into the working DB `data/staging_dictionary.db`, then export the
slim app DB `data/maori_dict.db` (the only file copied to the app repo). Sources are
independent — do **one at a time**; never rebuild everything unless asked. Full reference:
`docs/UPDATE_WORKFLOW.md`.

## Pipeline (word-list sources)

```
scrape → parse(JSON) → import → <source>_entries → unify → entry/sense/example/… → export → maori_dict.db
                       (all in staging_dictionary.db)                                (slim app DB)
```

- The per-source `*_entries` table is the **curated landing zone** — definition/POS/variant
  cleanups live there, not in the JSON. Always go through `import`; never feed `unify` from JSON.
- `unify` (`scripts/50_build_unified.py --source <name>`) is an idempotent DB→DB projection
  that rebuilds only that source's slice of the canonical core.
- Run from repo root; on Windows prefix with `PYTHONUTF8=1` (macrons/IPA in output).

## Checklist

1. **Identify the source** and confirm with the user which one (and full re-scrape vs delta).
2. **Init + back up** (never skip the backup):
   ```bash
   py scripts/00_init_db.py
   cp data/staging_dictionary.db data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-<source>
   ```
3. **Run that source's recipe** from `docs/UPDATE_WORKFLOW.md`. Map:
   | source | unify `--source` | notes |
   |--------|------------------|-------|
   | Te Aka | `te_aka` | import with `--refresh` for annual delta |
   | Paekupu | `paekupu` | import with `--refresh`; 2-phase scrape |
   | He Pātaka Kupu | `hepatakakupu` | — |
   | Williams | `williams` | Wayback source |
   | Papakupu | `papakupu` | run cleanups 09/10/11 `--apply`; dialect=Tai Tokerau auto |
   | POLLEX/LPO/ACD | _(none)_ | etymology layer — import only, **no unify** |
   - Web scrapes are long and resumable; OCR/PDF and `--refresh` modes per the doc.
4. **Unify** the source: `py scripts/50_build_unified.py --source <name>` (skip for the
   etymology layer).
5. **Verify** — all must pass before stopping:
   ```bash
   py -m unittest discover -s tests -p "test_*.py"
   ```
   For a delta import, also report `data_refresh_runs` (new/modified/deleted counts).
6. **Export the app DB**: `py scripts/60_export_app_db.py` — rebuilds the slim
   `data/maori_dict.db` from staging (this is the only file copied to the app repo).
7. **Update trackers**: add a `SESSIONS.md` row (source, row counts, what changed, date);
   update `DATABASE_REFERENCE.md` only if counts/schema changed.

## Guardrails

- One source per run. If the user names several, do them sequentially, each with its own
  backup + verify.
- If a unify step hits a `database is locked` error, ensure no other Python process holds
  the DB (a prior scrape/import), then retry.
- Don't invent data: Papakupu `example.text_mi` is NULL by a known upstream extractor bug —
  leave it until that fix lands; don't backfill from the English half.
- A brand-new PDF source needs a new `<source>_entries` table, a `source_metadata` row, and
  a new builder in `50_build_unified.py` before it can be unified (see the doc's OCR path).
