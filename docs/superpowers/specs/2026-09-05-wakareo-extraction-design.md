# Design — Wakareo ā-ipurangi extraction (10 new component dictionaries)

*Date: 2026-09-05 (revised 2026-09-06) · Status: in implementation · Scope: dictionary collection DB (`staging_dictionary.db`) and the app DB (`maori_dict.db`)*

## Goal

Extract the component dictionaries of **Wakareo ā-ipurangi** (reotupu.co.nz, Wordstream
Corporation Ltd) into the staging DB as ten new word-list sources, unify them into the
canonical core, and ship them in the app DB.

Access is by paid subscription plus written permission from Wordstream for full exploration
and use. Recon was performed 2026-09-05; fixtures live in `sources/wakareo/recon/`.

## What Wakareo is

A *compilation* of eleven separately-owned dictionaries behind one ASP.NET WebForms search
UI, ~81,000 records total. `About.aspx` claims "more than 50,000 entries"; the observed ID
space is larger.

| # | Component | Direction | ID range (observed) | ~Entries | Copyright asserted (per `Legal.aspx`) |
|---|-----------|-----------|---------------------|----------|----------------------------------------|
| 1 | Wordstream Williams Corpus | MI→EN | 1 – 25,578 | ~25,500 | © 2003 Wordstream — **SKIPPED** (duplicate) |
| 2 | Wordstream Tregear Exceptions | MI→EN | 25,579 – 26,216 | ~640 | © 2002 Wordstream |
| 3 | H.M. Ngata Dictionary | **EN→MI** | 26,217 – 47,745 | ~21,500 | © Whai Ngata; pub. Learning Media 1993 |
| 4 | Te Matatiki | MI→EN | 47,746 – 52,723 | ~5,000 | © 1996 Te Taura Whiri; **OUP written-permission clause** |
| 5 | Kimikupu Hou | **EN→MI** | 52,724 – 75,204 | ~22,500 | NZCER, kaitiaki Te Taura Whiri |
| 6 | He Kupu Arotake | **EN→MI** | 75,205 – 77,660 | ~2,450 | © 1995 Crown / Education Review Office |
| 7 | Kupu Rorohiko | **EN→MI** | 77,661 – 78,033 | ~370 | Te Taka Keegan / Univ. of Waikato |
| 8 | Tai Kupu (variances) | MI→EN | 78,034 – 79,694 | ~1,660 | © 2003 Wordstream |
| 9 | Ngā tini a Tangaroa (fish) | MI→EN | 79,695 – 81,047 | ~1,350 | Ministry of Fisheries |
| 10 | Kupu Mataora | **EN→MI** | 81,048 – 81,062 | ~15 | *not listed in `Legal.aspx`* |
| 11 | Custom Māori Law Lexicon | MI→EN | 81,063 – ? | ~10 | *not listed in `Legal.aspx`* |

Ranges are **estimates from browse-index sampling** and are not trusted by the
implementation — see *Extraction*.

## Locked decisions

- **Williams is skipped entirely.** `williams_entries` (14,942 rows, NZETC TEI of the same
  1971 7th edition) already covers it. Not scraped, not diffed, not landed.
- **All ten ship** (revised 2026-09-06, see *Permitted use* below). They land in
  `staging_dictionary.db`, unify into the core, and export to `maori_dict.db` like any other
  source.
- **Name clash resolved:** Wakareo's "Tai Kupu" becomes `tai_kupu_variants`. The existing
  `taikupu` source (Ngāpuhi vocab, Māori Minute app) is untouched. Other components take
  plain names.
- **EN→MI sources invert at unify, not at landing** (see *The direction problem*).
- **No core schema change.** No new columns on `entry` / `sense` / `form` / `relation`.

## Permitted use — READ BEFORE CHANGING THE EXPORT

*Revised 2026-09-06.* The repo owner holds confirmation that all ten components may be used
**in a private, non-public, non-commercial app**. On that basis they ship in `maori_dict.db`.
This follows existing practice for `papakupu`, which ships carrying
`licence='For Private Use Only'`.

**This permission is conditional, and the condition is the whole basis for it.** Wakareo is a
*compilation*: Wordstream licenses components 3–7 and 9 in the inventory above from third
parties — Whai Ngata / Learning Media, Te Taura Whiri with an explicit Oxford University Press
written-permission clause, NZCER, the Crown (ERO), the Ministry of Fisheries, and Te Taka
Keegan / University of Waikato. Wordstream cannot sub-license those onward for public or
commercial distribution.

**If the app ever becomes public or commercial, this arrangement lapses and those components
must be withheld from the export again.** A working per-source export exclusion —
`EXCLUDED_SOURCES` / `TABLE_FILTER` in `60_export_app_db.py`, plus the relation-target cleanup
it needs — was implemented and verified in commit `148fd3a`; restore it from there rather than
rewriting it. Components 2, 8, 10 and 11 are Wordstream-owned or unattributed and are the
least constrained.

## Record model

Every record in every component uses one template, emitted **before** the page's `<!DOCTYPE>`:

```
<TD><TD><FONT SIZE='+2'>{headword}</FONT></TD>
<TD>{pos}</TD>
<TD ALIGN='Right'>{search_scope}</TD>
<BR><HR SIZE='2' WIDTH='100%'><BR>
{body}
<BR><BR>[Reference: WR-{TAG}.{n}]
```

Four slots plus a provenance tag. Observed tags: `WR-WWC` (Williams Corpus), `WR-TE`
(Tregear Exceptions), `WR-HMN` (Ngata), `WR-TM` (Te Matatiki), `WR-KKH` (Kimikupu Hou),
`WR-HKA` (He Kupu Arotake), `WR-HKR` (Kupu Rorohiko), `WR-TK` (Tai Kupu), `WR-NT` (Ngā tini
a Tangaroa), `WR-KM` (Kupu Mataora), `WR-CL` (Custom Law Lexicon).

`{pos}` and `{search_scope}` are frequently empty. `{search_scope}` appears as either
`(Search Scope: ...)` or `[Search Scope: ...]` and lists authored spelling/macron variants.

Sample bodies (verbatim from recon fixtures):

- **Ngata** `ID=26300` — a bolded `tū whakamatara, tūrangahapa`, then an English sentence and
  its Māori translation, each on its own `<BR>`. The comma-separated list is *multiple Māori
  equivalents*, not one multi-word term.
- **Te Matatiki** `ID=47800` — headword `Aumanga`, pos `[noun]`, gloss `Vent`, then a
  bracketed derivation citing a Williams page: `[W.22 'a hollowed-out space, ...']`.
- **Tai Kupu** `ID=78035` — headword `Ahūa, āhua`, scope `[ahua, ahūa, āhua]`, body
  `āhua - attitude, form`.
- **Kimikupu Hou** `ID=52800` — `Abundant` to `pukahu`, no example.

Note: the page `<title>` reads `Custom Māori Law Lexicon` on **every** record — an upstream
template bug. It is not a provenance signal and must be ignored; `WR-` tags are authoritative.

## Extraction — `scripts/41_wakareo_scrape.py`

**Sweep by ID, not by browse tree.** `Browse.aspx?ID={n}` is a plain authenticated GET
returning one record; no `__VIEWSTATE` postback is required for navigation. Each record
self-identifies by its `WR-` tag, so the sweep routes records by what they *say they are*
rather than by an assumed range. The ID-range table above is therefore documentation, not
control flow — it determines only the start offset (25,579, to skip Williams), and even that
is **verified at runtime**: any record carrying `WR-WWC` is discarded and counted, not landed.

- Auth: `utils.load_env("WAKAREO_USER", "WAKAREO_PASS")` reading the gitignored `.env`;
  POST to `login.aspx` carrying `__VIEWSTATE` / `__VIEWSTATEGENERATOR` / `__EVENTVALIDATION`
  plus `Login1$UserName` / `Login1$Password` / `Login1$LoginButton`. Success is asserted by
  the response URL no longer containing `login.aspx`.
- **TLS:** call `truststore.inject_into_ssl()` before `import requests`. Norton Antivirus on
  this machine performs TLS interception (`CN=Norton Web/Mail Shield Root`), so `certifi`
  cannot validate the chain but the Windows trust store can. `verify=False` is **not**
  acceptable — credentials are POSTed over this connection.
- Session expiry: on a response redirecting to `login.aspx`, re-authenticate once and retry
  the same ID; abort the run if that fails twice consecutively.
- Politeness: 1.5s delay, `User-Agent: MaoriDictResearch/1.0 (rich@kaio.co.nz)`, 3 retries
  with 15s backoff — matching `04_te_aka_scrape.py`.
- Raw HTML to `sources/wakareo/raw/{ID}.html`; `manifest.json` tracking
  `fetched` / `empty` / `errors` / `last_id` / per-tag counts. Fully resumable.
- Upper bound discovered by probing forward until 50 consecutive empty records.
- Estimated ~55,000 requests, ~23 hours.

Flags: `--limit N` for test runs; `--from ID` / `--to ID` for targeted refetch.

## Parse — `scripts/41_wakareo_parse.py` + `scripts/wakareo_records.py`

`wakareo_records.py` is a **pure, DB-free, unit-testable module** (same shape as
`williams_senses.py`):

- `split_template(html)` returns `{headword, pos, search_scope, body, ref_tag, ref_no}` — the
  generic four-slot split, shared by all ten components.
- `parse_search_scope(text)` returns the variant list, handling both bracket styles.
- Ten body parsers, dispatched on `ref_tag`, each returning a normalised dict. The EN→MI
  parsers split the leading bolded run on commas into an ordered `equivalents` list and pull
  the `(text_en, text_mi)` example pair. The MI→EN parsers produce `gloss_en`; Te Matatiki
  additionally produces a `derivation` string and the extracted `W.<page>` cross-refs.

`41_wakareo_parse.py` walks `sources/wakareo/raw/`, dispatches, and writes one JSON per
component to `sources/wakareo/parsed/{source_id}.json`.

## Landing tables — `scripts/41_wakareo_import.py`

Ten tables created in `00_init_db.py`, each preserving its source's **native direction**:

`tregear_exceptions_entries`, `ngata_entries`, `te_matatiki_entries`,
`kimikupu_hou_entries`, `he_kupu_arotake_entries`, `kupu_rorohiko_entries`,
`tai_kupu_variants_entries`, `nga_tini_a_tangaroa_entries`, `kupu_mataora_entries`,
`maori_law_lexicon_entries`.

Common columns: `id`, `wakareo_id` (the numeric `Browse.aspx?ID`), `ref_no` (the `WR-XX.n`
ordinal), `headword`, `headword_sort`, `headword_search`, `part_of_speech`,
`search_scope` (JSON array), `body_raw`, `created_at`, `last_updated`.

Direction-specific columns:

- EN→MI tables add `equivalents` (JSON array of Māori terms), `example_en`, `example_mi`.
- MI→EN tables add `gloss_en`; Te Matatiki additionally adds `derivation` and
  `williams_refs` (JSON array).

Per the project rule, these tables are the **curated landing zone** — later cleanups edit
them in place, never the JSON.

Ten `source_metadata` rows are inserted with `display_name`, `url`
(`https://reotupu.co.nz/WSLiveWakareo/`), and a `licence` string naming that component's
asserted copyright holder as given in the table above. No `default_dialect` is set — Wakareo's dialect data is a per-record topic facet,
not a source-wide default.

## The direction problem

Five components (~46,800 entries, the bulk of the new material) are **English-headword**.
`entry` is Māori-headword-centric: `headword_sort` / `headword_search` / `entry_fts` and the
app's whole lookup model assume a Māori headword, with `headword_en` a Paekupu-only extra.

**Decision — invert at unify, preserve at landing.**

For each EN→MI landing row, `50_build_unified.py` emits **one `entry` per Māori equivalent**:

- `headword` = the Māori equivalent; `headword_en` = the English lemma
- `sense.gloss_en` = the English lemma
- `example.text_en` / `text_mi` = the sentence pair, attached to every sibling (the source
  gives one pair per lemma, not per equivalent)
- siblings cross-linked with `relation(rel_type='synonym')`
- `source_entry_id` = the `WR-` reference (e.g. `WR-HMN.235`), so an inverted entry still
  names its exact origin

The landing table retains the true one-lemma-many-equivalents shape, so no fidelity is lost
and a future reverse-lookup view can be built from it without re-scraping.

**No dedup.** A Māori term that appears as an equivalent under several English lemmas (say
`pukahu` under both *Abundant* and *Plentiful*) produces one `entry` per occurrence, each
carrying its own `source_entry_id` and `headword_en`. This follows the existing `taikupu`
precedent — duplicate headwords are distinct senses. `homonym_no` is left NULL; collapsing
these is a curation decision for the landing table later, not a projection concern.

**Rejected:** English as `entry.headword` behind a new `headword_lang` column. More faithful
to the source, but it ripples through `headword_sort`, `headword_search`, `entry_fts`, the
export, and the app's search model — a large blast radius for ten sources that are not being
shipped.

## Unify — additions to `scripts/50_build_unified.py`

Ten new builders, registered under `--source` names matching the table prefixes. Each clears
only its own slice, per the existing idempotent-projection contract.

Mappings beyond the direction handling above:

- `search_scope` becomes `form` rows with `form_type='variant'`. These are **authored**
  variants, in contrast to the macron/double-vowel forms `normalise_search_key` derives — a
  genuine improvement in variant coverage for these entries.
- Te Matatiki `williams_refs` become `relation(rel_type='cross_ref')` rows targeting Williams
  headwords, with the page number in `relation.note`.
- `part_of_speech` goes to `sense.part_of_speech`, resolved through `std_pos` by the existing
  `resolve_pos`. Wakareo's 35 POS values are mostly already-known atomic terms (`noun`,
  `transitive verb`, ...); genuinely new ones land in `std_pos` as `needs_review` and are
  dumped to `seeds/std_pos_seed.csv` afterwards.

Topic facets are **not** harvested in this round — they are a search-form filter, not a field
on the record, so capturing them needs a separate faceted crawl. See *Out of scope*.

## Export

`60_export_app_db.py` needs no source filtering: all ten export like any other source. Each
carries a `source_metadata.licence` naming the component's asserted copyright holder and
`notes` recording that use is permitted for a private, non-commercial app only — so the
condition travels with the data into the app DB rather than living only in this document.

## Testing

- `tests/test_wakareo_records.py` — unit tests for `wakareo_records.py` against the saved
  recon fixtures: template split, both `Search Scope` bracket styles, Ngata multi-equivalent
  splitting, Te Matatiki `W.<page>` extraction, the empty-`pos` and empty-`scope` paths, and
  the `WR-WWC` discard path.
- `tests/test_wakareo_provenance.py` — DB-level: every unified `entry` for a Wakareo source
  has a `source_entry_id` whose `WR-` tag maps to that `source_id`; no `WR-WWC` row landed;
  landing-table row counts reconcile with unified `entry` counts allowing for EN→MI fan-out.
- Export guard: each of the ten sources that has staging rows appears in `maori_dict.db` with
  a matching entry count.
- Full suite green: `py -m unittest discover -s tests -p "test_*.py"`.

## Out of scope

- Licence clearance correspondence with the individual rights holders (not needed under the
  private-use basis; required only if the app's status changes).
- Wordstream Williams Corpus (skipped), and any diff of it against `williams_entries`.
- Topic/dialect facet harvesting, including routing the 12 non-Māori Polynesian facet values
  (Hawaii, Samoa, Tonga, Tahiti, Marquesas, Niue, Futuna, Tikopia, Nukuoro, Paumotu,
  Mangareva, Uvea) into the `ETY_*` comparative layer. Recorded here because the facet list
  is evidence the data exists; harvesting it is separate work.
- `35_detect_pairs.py` tuning for the expected overlap between Kimikupu Hou / Te Matatiki and
  the existing `paekupu` + `te_aka` neologisms.
- A reverse-lookup (English-headword) search surface in the app.
