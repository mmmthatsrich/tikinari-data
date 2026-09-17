# hepatakakupu: recovering the 22,911 suffixes the parser throws away

**Status:** design, 2026-09-17
**Amends:** `05_hepataka_parse.py`; the `hepatakakupu_entries` schema
**Depends on:** `2026-09-17-suffix-forms-design.md` §2 — the storage
contract, the 22-suffix vocabulary, and the refusal rule are defined there
and are not restated here. **That spec ships first**; this one writes into
the `form_type` values it establishes.
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
24,941 rows in `hepatakakupu_entries`, 24 carry anything resembling a suffix,
and those arrived by other accidents.

The data is not gone. All 14,996 raw pages are on disk and intact — **no
re-scrape is needed**, only a re-parse.

---

## 2. What is actually there

Measured by walking every `span.def > strong` in all 14,996 files:

| | |
|---|---|
| suffix tokens (sense level) | **22,911** |
| distinct word+suffix pairs (`form` rows) | **14,775** |
| pages carrying at least one suffix | **6,628** of 14,996 (44%) |
| distinct suffix types | **30** — 22 well-formed, 8 malformed |
| tokens the 22 well-formed types account for | **22,902** of 22,911 (99.96%) |

The top of the distribution:

```
-tanga  7,816     -hia    1,422     -ina      223
-nga    6,087     -ngia     909     -na       211
-tia    3,063     -hanga    418     -ranga    148
-a      2,069     -ia       236     -ria      122
```

Three facts in that table drive the design.

**Nominalisations dominate.** 14,560 of the 22,911 tokens are nominalising,
8,342 passive — the inverse of what the other sources hold. hepatakakupu is
where the nominalisation half of the user's counting requirement will
actually come from.

**The count in the table is not the row count.** 22,911 tokens collapse to
14,775 distinct word+suffix pairs, because a word's senses repeat its
suffixes: `kake` has five senses, three of which carry `-a -nga`. `form` is
keyed on the entry, so the same pair must be written once. **A 36% fall
between tokens and rows is expected, not a bug** — see §5.

**Fewer than half the pages carry anything.** 8,368 pages have an empty
`<strong>` or none at all. That is hepatakakupu's own editorial choice, and
a reader that treats the empty case as a parse failure will report 8,368
false errors.

---

## 3. The fix

**Schema.** Add one column:

```sql
ALTER TABLE hepatakakupu_entries ADD COLUMN suffixes TEXT DEFAULT '[]';
```

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
`form` rows — the same code path the six sibling sources use. hepatakakupu
contributes a reader and nothing more.

---

## 4. Composition

`kake` + `-a` → `kakea`; `kake` + `-nga` → `kakenga`. Straight
concatenation against the row's own headword.

This is the same composition the companion spec defines for te_aka,
paekupu, papakupu and kimikupu_hou, and it is checked the same way: where
a hepatakakupu word also appears in ngata or williams — which record the
derived word whole — the composed form must equal the recorded one.
hepatakakupu's 14,775 pairs make it the largest contributor to that
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
spec's §6: 22,911 tokens seen, 14,775 rows written, 9 refused. The gap
between the first two is the expected sense-level duplication — if tokens
and rows come out equal, the dedup is not running.

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
- **Dedup:** a word whose five senses each carry `-a -nga` yields two `form`
  rows, not ten.
- **Re-parse idempotence:** running the parser twice over the same raw files
  produces the same table.

---

## 7. What this does not fix

- **Whether hepatakakupu's 8,368 suffix-less pages should have suffixes.**
  44% coverage is low enough to wonder about, but the pages are intact and
  the empty `<strong>` is present and deliberate-looking. Treated as
  editorial until someone shows otherwise.
- **The eight malformed types.** `-bga`, `-tiha`, `-ā`, `-rapā` and the four
  whole words mis-marked as suffixes (`-pukenga`, `-pihanga`, `-pukea`,
  `-rapaia`) are defects in hepatakakupu's own text. Reported, not repaired,
  and not corrected toward a guess.
- **The 1,004 bracketed headwords** elsewhere in this source. A separate
  known issue; the bracket handled here is the one inside `<strong>`.
