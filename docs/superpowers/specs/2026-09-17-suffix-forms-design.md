# Derived forms: the storage contract, and the six sources that need no parser

**Status:** design, 2026-09-17
**Amends:** the `form` table's `form_type` vocabulary; the paekupu and te_aka
importers; the extraction step in `50_build_unified.py`
**Companion:** `2026-09-17-hepatakakupu-suffix-parse-design.md` — hepatakakupu
holds two thirds of the corpus, needs a parser rewrite, and is specced
separately. It consumes the storage contract in §2 of this document.
**Motivating requirement:** the app will surface derived forms in display, and
the corpus must answer "how many passives / nominalisations, by suffix".

---

## 1. What is being lost

Seven of the eleven dictionary sources record the derived forms of a word —
the passive (`whakarere` → `whakarerea`) and the nominalisation (`kake` →
`kakenga`) — and so does the pollex comparative dataset, which sits outside
`entry` in its own tables. **None of it reaches the database.** Measured
across every source, reading raw records end to end rather than scanning for
a guessed pattern:

| source | notation | where it lives | tokens | specced in |
|---|---|---|---|---|
| hepatakakupu | `-a -nga` | `<strong>` in raw HTML | **22,911** | companion |
| ngata | `whakarere, whakarerea` | `<B>` in `body_raw` | **4,462** | here |
| te_aka | `(-tia)`, `(-a,-hia)` | after the POS marker | **~3,950** | here |
| paekupu | `~a`, `~tanga` | headword | **1,407** | here |
| papakupu | `[-tia]` and `~tia` | headword **and** definition head | **185** | here |
| pollex † | `Awhi-tia` | headword / `maori_reflex` | **109** | here, optional |
| williams | `Pass. arohaina` | prose | **85 seen, 35 survive** | here |
| kimikupu_hou | `(-tia)` | `<B>` in `body_raw` | **18** | here |
| te_matatiki, taikupu, temarareo, tregear | — | — | 0, verified | — |

† pollex is not one of the eleven and has no `entry` rows; §3 covers what
that costs.

**≈32,100 tokens. Seven notations. Seven locations.** This document covers
the ~10,200 outside hepatakakupu.

Meanwhile the `form` table — which exists for precisely this — holds 654
rows, all `variant` and `plural`. The schema has been ready the whole time
and nothing has ever written a derived form into it.

**Every figure above is a token count, not a row count.** A token is one
suffix as the source wrote it; several senses of one word routinely repeat
the same suffix, and `form` is keyed on the entry. Where hepatakakupu has
been measured both ways, 22,911 tokens collapse to 14,775 distinct
word+suffix pairs — a 36% fall. **The other sources have been counted only
as tokens.** Expect each to yield fewer rows than its figure above, and see
§6 for how that is validated rather than assumed.

### Two consequences, one of them already measured

**The data is simply absent.** A user looking up `whakarere` cannot be shown
its passive `whakarerea`, because nothing reads the column it sits in.

**Two sources corrupt the matching key with it.** paekupu writes the suffix
into the headword (`ahu ~nga`) and te_aka sometimes does too (`āmine (-tia)`),
so `headword_search` becomes `ahu ~nga` and `amine (-tia)`. Those entries can
never meet the plain `ahu` and `amine` that four other sources hold.
**1,407 paekupu entries and 321 te_aka entries are severed this way** — the
only consequence of this defect with a measured cost today.

---

## 2. What gets stored — the contract both specs share

One row in `form` per derived form, per entry.

```sql
form (
    id, entry_id, form, form_search, form_type, note
)
```

No schema change is required. Four decisions about how it is used:

**`form` holds the COMPLETE word, never the fragment.** `whakarerea`, not
`-a`. The sources disagree about which they record — hepatakakupu gives the
fragment, ngata gives the whole word — and the complete form is the one a
reader needs and the one `form_search` can match on. Where a source gives
only a fragment, the form is composed as `headword + suffix`; where it gives
the whole word, it is taken as-is. §4 covers composition.

**`form_type` gains two values**, joining the existing `variant`,
`alt_spelling`, `plural`, `inflected`:

```
passive         -tia -hia -ina -ngia -ria -mia -kia -whia -na -a
                -ia -kina -whina
nominalisation  -nga -tanga -hanga -ranga -anga -manga -kanga
                -inga -unga
```

Twenty-two suffixes: thirteen passive, nine nominalising. **This vocabulary
was measured, not recalled** — it is the complete set of well-formed types
in hepatakakupu's 22,911 tokens, the largest sample in the corpus. An
earlier draft of this spec listed sixteen from memory and silently dropped
`-ia` (236 occurrences), `-kanga` (30), `-kina` (9), `-whina` (2), `-inga`
and `-unga`. A reader built to the recalled list would have discarded real
data and reported success.

**An unrecognised suffix is refused, never guessed.** The same measurement
found nine malformed tokens across eight types: `-bga` (a typo for `-nga`),
`-tiha`, `-ā`, `-rapā`, and four whole words mis-marked as suffixes —
`-pukenga`, `-pihanga`, `-pukea`, `-rapaia`. These are source defects, not
morphology. The reader must drop them and **report the count and the
values**; a silent drop would hide the day a real suffix falls outside the
list.

**Where the suffix must be recovered from a whole word, the longest match
wins.** The suffix sets overlap, and the sources that record a derived word
whole — ngata, williams — never say which suffix produced it. So the rule is
stated rather than left to the reader: strip the known base, then classify
the remainder against the longest suffix it matches. `-tanga` before
`-kanga` before `-anga` before `-nga`; `-ina` before `-na` before `-a`;
`-kia`/`-ria`/`-mia`/`-hia` before `-ia` before `-a`.

**`note` carries the suffix and its provenance**, as `-tia (te_aka)`. This
is what makes the required query cheap: counting by suffix reads `note`,
counting by class reads `form_type`, and provenance survives for the sweep
to judge. A dedicated column was considered and rejected — `note` already
exists, and the suffix is recoverable from `form` minus `headword` anyway.

### The query the requirement asks for

```sql
-- how many of each class
SELECT form_type, COUNT(*) FROM form
 WHERE form_type IN ('passive','nominalisation') GROUP BY 1;

-- how many of each suffix
SELECT substr(note, 1, instr(note,' ')-1) AS suffix, COUNT(*)
  FROM form WHERE form_type = 'passive' GROUP BY 1 ORDER BY 2 DESC;
```

`60_export_app_db.py` already copies `form` to the app database, so display
needs no new plumbing.

---

## 3. Where the work happens

Two layers, and neither touches a parser. (The parse-layer work is the
companion spec's whole subject.)

**Layer 2.5 — import. paekupu and te_aka only**, for the key strip in §5.

**Layer 3 — extraction at unify. All six.** Their tokens already survive
into the per-source tables and die only because nothing reads them:

```
ngata         4,462 pairs  body_raw      (comma-separated complete forms)
te_aka        3,504 rows   senses JSON   (definition_raw, leading '(-tia)')
paekupu       1,407 rows   headword      (trailing '~a')
williams         85 rows   definition    ('Pass. arohaina', 35 survive the
                                          morphological test)
papakupu        153 rows   definition    (leading '~tia') + 13 headword
kimikupu_hou     29 rows   body_raw      ('(-tia)' inside <B>)
```

Nothing upstream is touched. `50_build_unified.py` reads fields it currently
ignores and writes `form` rows.

### pollex was dropped

pollex has no `entry` rows. It reaches entries only through
`pollex_entry_links`, a many-to-many table carrying `match_confidence` and
matching on `headword_exact` — **34,558 entries are linked, and one entry
can carry up to 8 links.** A pollex form therefore has no single
unambiguous `entry_id`: writing `Awhi-tia` means writing it once per linked
entry keyed `awhi`.

That is defensible — each of those entries genuinely has that passive — but
it is a different operation from the other six, it is the one place where a
`form` row would rest on a probabilistic match rather than on a source's own
filing, and it is worth **109 tokens, 0.3% of the corpus**. The draft ruling
was to gate pollex behind a `match_confidence` threshold, but that threshold
does not exist to gate on: all 57,792 `pollex_entry_links` rows carry
`match_confidence = 1.0` and `match_method = 'headword_exact'` — every link
is nominally "full confidence," including the **12,686 of 34,558 linked
entries that carry 2+ links (up to 8)**, which is exactly the ambiguity a
confidence threshold would have needed to resolve. With nothing to gate on,
**pollex was dropped**, per the standing fallback ("drop it without argument
if it complicates the rest"). The other six carry the requirement on their
own.

---

## 4. Extracting each notation

Each source needs its own reader because each records something different.
The readers are pure functions over a string, testable without a database.

**ngata — complete forms, already whole.** `<B>whakaranu, whakaranua,
tūkino, tūkinotia</B>` is a comma list that mixes base+derived pairs with
synonyms. The discriminator is morphological and was validated on the
corpus: form B is a derived form of A only when `B.startswith(A)` and the
remainder is a known suffix. That test separated **3,665 records holding
genuine pairs from 4,655 that are synonym lists only** — `whakamā,
pōrahu, pōrahurahu` is correctly rejected. Store B whole; `note` records the
suffix the longest-match rule identified.

**te_aka — fragment, two locations.** `(-tia)` appears after the POS marker
and at the head of `definition_raw`. It may hold several: `(-a,-hia)`.
Compose each against the headword.

**paekupu — fragment, in the headword.** `ahu ~nga` → base `ahu`, suffix
`-nga`, form `ahunga`. **The base also replaces the headword for
`headword_search` purposes — see §5.**

**papakupu — both.** `tāpiri [-tia]` in the headword and `~tia, ~tanga`
leading the definition. Same composition.

**williams — complete form, in prose.** `Pass. arohaina, be the object of
love` gives the whole word after the marker. Take the first token after
`Pass.`/`pass.`; store it whole; derive the suffix by longest match.

**kimikupu_hou — fragment, anywhere in `body_raw`.** `tūtōkai (-tia)`. The
shipped reader runs `read_paren_suffixes` over the entire `body_raw` blob,
not just its `<B>` region — there is no region-scoping, so a suffix marker
elsewhere in the raw HTML is read the same way. Note its `body_text` column
is empty for 2,823 of 2,831 rows, so the reader must use `body_raw`; that gap
is recorded in §7 and is not fixed here.

**pollex — joined, if built at all.** `Awhi-tia` splits at the hyphen into
base and suffix; `Aroha-ina, -tia` carries two. The base is the Māori
reflex, not necessarily the pollex headword. See §3 for why this one is
last and optional.

---

## 5. The key severance, fixed as a consequence

Once the suffix is extracted, the headword it was attached to is the bare
word, and `headword_search` follows from that. `ahu ~nga` keys as `ahu`;
`āmine (-tia)` keys as `amine`. That un-severs the **1,407 paekupu and 322
te_aka entries** that currently cannot meet their own base form in four
other sources.

`headword_search` is computed per-importer, so the strip belongs in the
importers for correctness. Doing it at unify instead would leave the
per-source tables disagreeing with the unified one. **The importers are the
right place and this spec puts it there**, accepting that paekupu and te_aka
need re-importing from their existing per-source tables.

This is the only part of the change with a measured benefit today. It is
also the only part that alters an existing key, so §6 gates it accordingly.

---

## 6. Validating

**Hard gate — the recorded calibration answers.** All four in
`tests/test_concept_acceptance.py` must hold after the rebuild: `hiwi` ≥ 6
concepts, `hia` never joins `hīa`, `himoemoe` unifies ≥ 4 sources,
`paekupu:hoi` stays single-source. A failure means the key change
over-merged and the rule is wrong, not the test.

**Second gate — `hoi` ≥ 7 concepts**, the chaining canary.

**Counts, measured both ways before they are judged.** §1's figures are
token counts, and rows will be fewer. So each reader reports rows written
plus, **per kind**, tokens seen and tokens refused. A reader whose
tokens-seen falls more than 10% below §1 is missing a shape in the source. A
reader whose **suffix-kind** refusals exceed 1% of its suffix tokens has a
vocabulary problem, not a source problem — hepatakakupu's refusal rate is 9
in 22,911, and anything near a percent means the §2 list is wrong. Neither
number is a target; both are tripwires.

**The kinds are not comparable and are never summed.** One counter carrying
all of them put four of six sources over the 1% threshold without one of
them having the fault it names, which is how a tripwire stops being read:

| kind | what a refusal means | tripwire |
|---|---|---|
| `suffix` | a token the source WROTE as suffix notation is outside the vocabulary. The `-hina` signal. | **yes** |
| `pair` | `derived_pair` tested two spellings and they are not base + suffix. The ngata and williams discriminator declining a compound. | no |
| `base` | a headword carries a parenthesis, so nothing can be composed onto it. Unrelated to the vocabulary. | no |
| `whole` | an irregular form stored verbatim. These are rows we WROTE. | no |

Measured after the split: only papakupu is flagged, at 8.23%, and its 19
refused tokens are reduplications and appends — a different morphological
process, deferred by `2026-09-21-reduplication-design.md` §2. Every other
source is clean. Before the split the same report flagged williams (2.78%,
one rejected pair test), ngata (2.80%, pair tests), paekupu (0.89%, all of
it rows it had written) and hepatakakupu's bases (100%, four parentheses).

**Composition is checked against the sources that give both.** ngata and
williams supply complete derived forms; te_aka, paekupu, papakupu and
kimikupu_hou supply fragments to compose. Where the same word appears in
both groups, the composed form must equal the recorded one. `whakarere` +
`-a` must equal ngata's `whakarerea`. That is a free correctness check on
the composition rule and it should be a test.

**No silent duplicates.** Dedup is real, but it operates WITHIN a source, not
across sources: te_aka routinely writes the same form twice, once from the
headword and once from each sense that repeats the suffix marker. Cross-source
accumulation onto one row cannot occur in the current pipeline — `unify_source`
calls `delete_source_slice` and then builds a fresh `Builder` per source, and
every `entry` row carries the `source_id` it was minted under, so no
`entry_id` is ever shared between two sources' passes. (Empirically, 0 of the
12,095 derived-form notes contain a comma or semicolon, which is what two
sources landing on the same row would look like.) Rows are per
`(entry_id, form, form_type)`; provenance accumulates in `note` for the
within-source case. Counting queries must not double-count a form because one
source mentioned it three times.

---

## 7. What this does not fix

- **`kimikupu_hou.body_text` is empty for 2,823 of 2,831 rows**, against
  ~100% for every sibling Wakareo source. Its raw HTML is intact in
  `body_raw`, so this reader works — but any other rule reading `body_text`
  sees almost nothing from that source. A separate backfill, recorded here
  because this work is what found it.
- **Derived forms filed as their own entries.** `whakairia` and `tikina`
  exist as standalone headwords in ngata and papakupu with nothing linking
  them to `whakairi` and `tiki`. That is an eighth representation and needs
  a relation, not a `form` row. Out of scope.
- **Irregular and suppletive forms.** Composition assumes concatenation.
  Where a source records a derived form that is not `base + suffix`, only
  the sources that give the complete word will carry it correctly. The §6
  cross-check will reveal how often that happens; it does not fix it.
- **tregear.** Its raw HTML holds **5** `Pass.` mentions, in the same prose
  notation williams uses, and the imported `tregear_exceptions` slice — 321
  entries — carries **none** of them. Five tokens do not justify a reader
  or a re-import.
- **The eight malformed suffixes in §2.** They are typos and mis-marked
  words in hepatakakupu's own text. Reported, not repaired.

---

## 8. Testing

- **Unit, per reader, against the real strings from §4** — one test per
  source using a verbatim sample from its raw data, including the
  multi-suffix cases (`(-a,-hia)`, `Aroha-ina, -tia`) and the negative
  cases that must not match: ngata's synonym lists, kimikupu_hou's
  `(-waro)` chemistry, temarareo's `~` meaning "reflects as", pollex's
  `*qati(-afi)` reconstruction, and the English word *pass* in an ordinary
  gloss. **Every one of those classes produced a false positive during the
  survey; each earns a test.**
- **Composition:** `base + suffix` against the sources that record the whole
  word, per §6.
- **Classification:** the longest-match rule in §2 — `kakenga` resolves to
  `-nga` and not `-a`; `tūkinotia` to `-tia` and not `-ia`; `whakamātanga`
  to `-tanga` and not `-anga`. Each of the 22 recognised suffixes maps to
  exactly one `form_type`.
- **Refusal:** `-bga` and `-pukenga` are dropped AND counted, not silently
  skipped and not coerced to a near neighbour.
- **Key severance:** `ahu ~nga` keys as `ahu`; a paekupu entry and its
  te_aka base land in one concept after the rebuild.
- **Acceptance, against the real database:** §6's gates, unweakened.
