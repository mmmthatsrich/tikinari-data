# hepatakakupu: recovering the 22,911 suffixes the parser throws away

**Status:** design, 2026-09-17
**Amends:** `05_hepataka_parse.py`; the `hepatakakupu_entries` schema;
`scripts/50_build_unified.py`; `scripts/hepataka_suffixes.py`
**Depends on:** `2026-09-17-suffix-forms-design.md` §2 — the storage
contract, the vocabulary, and the refusal rule are defined there and are
not restated here. **That spec has shipped** (12,095 rows from six sources,
merged 2026-09-18); this one writes into the `form_type` values it
established, reusing `scripts/suffix_forms.py` — `classify`, `compose`,
`fold` — and the `Tally` refusal report built alongside it.

The shipped vocabulary is **23** suffixes, not the 22 this document was
drafted against: `-hina` was added after the refusal report exposed it in
te_aka. It does not occur in hepatakakupu, so every count below is
unaffected — hepatakakupu exercises 22 of the 23.
**Why separate:** hepatakakupu is 71% of the corpus-wide suffix data and the
only source whose recovery needs a parser rewrite and a re-parse. Its six
siblings need neither. Bundling them would have made one plan where the
cheap two-thirds waited on the expensive third.

---

## 1. The defect

`05_hepataka_parse.py` reads each sense's definition span, finds the
`<strong>` element, and pulls the semantic domain out of it:

```python
strong = def_span.find("strong")
if strong is not None:
    m = re.search(r"\[([^\]]+)\]", strong.text or "")
    if m:
        semantic_domain = m.group(1).strip()
```

The element it is reading looks like this, from `sources/hepataka/raw/100.html`:

```html
<span class="def">
    <strong>
        -tia -hia -ngia -tanga -nga
        [Tūmatauenga]
```

The regex takes `[Tūmatauenga]` and the five suffixes in front of it are
discarded. **Every suffix hepatakakupu records is lost at this line.** Of
24,941 rows in `hepatakakupu_entries`, **3** contain a known suffix token
anywhere, and all three are incidental hyphenated text inside a definition —
not one recorded suffix survives the parse.

The data is not gone. All 14,996 raw pages are on disk and intact — **no
re-scrape is needed**, only a re-parse.

---

## 2. What is actually there

Measured by walking every `span.def > strong` in all 14,996 files:

| | |
|---|---|
| suffix tokens (sense level) | **22,911** |
| distinct (sense, suffix) pairs (`form` rows) | **22,883** |
| distinct (word, suffix) pairs, for comparison | 14,768 |
| pages carrying at least one suffix | **6,628** of 14,996 (44%) |
| distinct suffix types | **30** — 23 accepted spellings, 7 malformed |
| tokens the 23 accepted spellings account for | **22,903** of 22,911 (99.97%) |

The top of the distribution:

```
-tanga  7,816     -hia    1,422     -ina      223
-nga    6,087     -ngia     909     -na       211
-tia    3,063     -hanga    418     -ranga    148
-a      2,069     -ia       236     -ria      122
```

Three facts in that table drive the design.

**Nominalisations dominate.** 14,560 of the 22,911 tokens are nominalising,
8,343 passive — the inverse of what the other sources hold. hepatakakupu is
where the nominalisation half of the user's counting requirement will
actually come from.

**The tokens barely collapse, because hepatakakupu mints one entry per
SENSE.** An earlier draft of this document assumed a 36% fall to 14,768
word+suffix pairs, reasoning that `form` is keyed on the entry and a word's
senses repeat its suffixes — `kake` has five senses, three carrying `-a
-nga`. That reasoning is wrong for this source. `build_hepatakakupu` sets
`seid = str(id_)`, the sense-row primary key, so each of `kake`'s five
senses becomes its own `entry` row and each carries its own forms. The
expected output is therefore **22,883** rows, not 14,768 — the only
collapse is 21 tokens repeated within a single sense. See §5.

**Why 22,883 and not the 22,882 the plan predicted:** **+2** because the
multi-base rule composes `'tīkona, tīkoina'` onto both spellings where the
prediction counted one, and **−1** because `'hohou (i te) rongo'`'s only
base is refused (it still carries the phrase's parenthesis) so its single
`-hia` token writes nothing.

**Fewer than half the pages carry anything.** 8,368 pages have an empty
`<strong>` or none at all. That is hepatakakupu's own editorial choice, and
a reader that treats the empty case as a parse failure will report 8,368
false errors.

---

## 3. The fix

**Schema.** Add one column:

```sql
suffixes TEXT DEFAULT '[]'
```

The importer drops and recreates `hepatakakupu_entries` on every run, so
this column lives in the table's own `CREATE TABLE` DDL — no `ALTER TABLE`
is issued or needed.

A JSON array, matching the table's existing convention for `usage_examples`,
`synonyms` and `synonym_senses`. It holds the raw suffix tokens as the page
wrote them — `["-a", "-nga"]` — not composed forms and not classifications.
Parse records what the source said; unify decides what it means.

**Parser.** Split the `<strong>` text at the first `[`. What precedes it is
the suffix field; what the bracket encloses is the semantic domain, exactly
as today. Tokenise the suffix field on whitespace, keep tokens matching
`-[a-zāēīōū]+`, store the list. The domain extraction is unchanged — this
is an addition beside it, not a rewrite of it.

The attachment point is already correct and this is the fix's main piece of
luck: the parser walks one `span.def` per sense and writes one row per
sense, so the suffixes land on the same row as the `semantic_domain` from
the same bracket. **No new join, no new key, no ambiguity about which sense
a suffix belongs to.**

**Re-parse.** Run `05_hepataka_parse.py` over the 14,996 local files, then
re-import. No network access.

**Extraction.** `50_build_unified.py` reads `suffixes`, composes each token
against the headword, classifies it per the companion spec's §2, and writes
`form` rows through `_add_suffix_forms` — the same code path the six sibling
sources already use, including the `Tally` that reports tokens seen, rows
written and tokens refused. hepatakakupu contributes no reader at all: its
suffixes arrive already parsed in the `suffixes` column, so there is
nothing here to tokenise out of running text. That absence is exactly why
the work added an optional `tally` parameter to the shared
`_add_suffix_forms` (the other six sources tally inside their own readers)
plus a new `_hepataka_bases` helper to split hepatakakupu's own comma- and
parenthesis-bearing headwords before composition.

---

## 4. Composition

`kake` + `-a` → `kakea`; `kake` + `-nga` → `kakenga`. Straight
concatenation against the row's own headword.

This is the same composition the companion spec defines for te_aka,
paekupu, papakupu and kimikupu_hou, and it is checked the same way: where
a hepatakakupu word also appears in ngata or williams — which record the
derived word whole — the composed form must equal the recorded one.
hepatakakupu's 22,883 rows make it the largest contributor to that
cross-check, so it is the source most likely to expose an irregular form
that concatenation gets wrong.

---

## 5. Validating

**The re-parse must not disturb what already works.** This is the real risk:
the change touches a parser that currently produces 24,941 correct rows.
Before and after the re-parse, these must be identical:

- row count in `hepatakakupu_entries` (24,941)
- the set of `(word_id, sense_number)` pairs
- every existing `semantic_domain` value

A single changed domain means the bracket split broke the extraction it was
supposed to leave alone. **This check comes first**; the suffix counts are
worthless if the rest of the parse regressed.

**Then the suffix counts**, reported as three numbers per the companion
spec's §6: **22,914 tokens seen, 22,883 rows written, 12 refused** (8
unrecognised suffix tokens across 7 malformed types, plus 4 refused bases).
Because each sense mints its own entry, seen and written are expected to be
very nearly equal here — the 21-row gap is tokens repeated inside one
sense. A large gap would mean entries are being shared across senses, which
would be a regression in `build_hepatakakupu`, not a dedup success.

`seen` is not simply the raw token count (22,911): `Tally.refuse()`
increments `seen` on every call, so the four refused *bases* —
`_hepataka_bases` rejecting a headword that still carries a parenthesis —
are counted alongside suffix tokens, pushing seen to 22,914. And one token
is never counted at all: `'hohou (i te) rongo'` has no surviving base, so
its single `-hia` token never reaches `_add_suffix_forms` and is neither
kept nor refused. A maintainer reconciling 22,914 against the 22,911 raw
tokens otherwise loses an hour to that gap.

**The empty case is not an error.** 8,368 pages carry no suffix. The reader
reports that as a count, not as 8,368 warnings.

**The `form` table's existing 654 rows are untouched.** This adds
`passive` and `nominalisation` rows beside the `variant` and `plural` ones;
no existing row changes type.

**No calibration gate here.** This spec does not alter `headword_search` —
hepatakakupu's headwords are already clean, the suffix sits in a separate
element. The four recorded calibration answers are the companion spec's
concern, because the key strip is. This one cannot over-merge.

---

## 6. Testing

- **Parser, against verbatim raw fragments** — the five-suffix case from
  `100.html` (`-tia -hia -ngia -tanga -nga [Tūmatauenga]`), the two-suffix
  case from `1993.html` (`-a -nga [Tāne]`), the empty-with-domain case
  (`[Tāne]` alone, which must yield `[]` and still set the domain), and a
  `<strong>` absent entirely.
- **The domain must survive every one of those.** A test that checks the
  suffixes without also asserting the semantic domain would pass while the
  regression in §5 shipped.
- **Malformed input is refused and counted, not coerced:** `-bga` does not
  become `-nga`.
- **Composition:** `kake` + `-a` → `kakea`, against the headword on the row.
- **No cross-sense dedup:** senses do NOT collapse — `kake` ships **6**
  `form` rows (three senses carrying `-a -nga`, keyed per sense, not two).
  A large gap between tokens seen and rows written would signal entries
  wrongly shared across senses, not a dedup success; see §5.
- **Re-parse idempotence:** running the parser twice over the same raw files
  produces the same table.

---

## 7. What this does not fix

- **Whether hepatakakupu's 8,368 suffix-less pages should have suffixes.**
  44% coverage is low enough to wonder about, but the pages are intact and
  the empty `<strong>` is present and deliberate-looking. Treated as
  editorial until someone shows otherwise.
- **The seven malformed types (8 refused tokens).** `-bga`, `-tiha`, `-rapā`
  and the four whole words mis-marked as suffixes (`-pukenga`, seen twice,
  `-pihanga`, `-pukea`, `-rapaia`) are defects in hepatakakupu's own text.
  Reported, not repaired, and not corrected toward a guess.
- **`-ā` is not among them, and is not refused.** `classify('-ā')` returns
  `None` — the vocabulary is keyed on unmacronned `-a` — but
  `_add_suffix_forms` looks up `classify(fold(suffix))`, and `fold('-ā')`
  folds to `'-a'`, a passive. So `-ā` is silently accepted and ships:
  `mārui` + `-ā` composes to `māruiā`, written as `passive` with note
  `-ā (hepatakakupu)`. This is a coercion through folding, not a refusal —
  described here rather than repaired, per this section's own rule, but it
  is one accepted spelling among the 23, not one of the 7 malformed types.
- **The 1,004 bracketed headwords** elsewhere in this source. A separate
  known issue; the bracket handled here is the one inside `<strong>`.
