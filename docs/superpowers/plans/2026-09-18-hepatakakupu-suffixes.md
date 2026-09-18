# hepatakakupu Suffix Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the 22,911 passive and nominalisation suffix tokens that
`05_hepataka_parse.py` currently discards, and write them into the `form`
table as ~22,882 typed derived forms.

**Architecture:** Three layers, in order. The parser keeps the suffix text it
already reads but throws away, storing it as a JSON array. The importer gains
a column and re-imports from the re-parsed JSON. The unify step reads that
column and writes `form` rows through the same `_add_suffix_forms` helper the
six sibling sources already use. No new extraction logic — `scripts/suffix_forms.py`
shipped on 2026-09-18 and is reused unchanged.

**Tech Stack:** Python 3, lxml, sqlite3, unittest (run under pytest). No new
dependencies.

**Spec:** `docs/superpowers/specs/2026-09-17-hepatakakupu-suffix-parse-design.md`

**Companion, already shipped:** `docs/superpowers/specs/2026-09-17-suffix-forms-design.md`
defines the storage contract, the 23-suffix vocabulary, the refusal rule and
the `Tally` report. 12,095 rows from six sources landed on 2026-09-18. This
plan adds a seventh source to that machinery.

## Global Constraints

- **Never run `05_hepataka_parse.py`, `05_hepataka_import.py`,
  `50_build_unified.py`, `59_rebuild_derived.py`, or any other `NN_*.py`
  script from a subagent, and never write to `data/staging_dictionary.db`.**
  Read-only access is fine: `sqlite3.connect('file:data/staging_dictionary.db?mode=ro', uri=True)`.
  The controller runs every pipeline step in Task 5 under calibration gates.
- **The four recorded calibration answers in `tests/test_concept_acceptance.py`
  are a gate, never a target.** Do not edit that file.
- `form` holds the COMPLETE word, never the fragment: `kakea`, not `-a`.
- `form_type` is exactly `'passive'` or `'nominalisation'`.
- `note` is `'-tia (hepatakakupu)'` — suffix, space, source in parentheses.
- An unrecognised suffix is **refused and counted**, never coerced to a near
  neighbour and never silently dropped.
- Store the ORIGINAL word with its macrons. Folding is for comparison only.
- **`suffix_forms.classify` must never fold.** A folding `classify` returns
  `'passive'` for `-ā`, and the corpus holds 167 non-suffix `-ā` tokens inside
  hyphenated compounds like `tū-ā-nuku`. Callers fold at the lookup site.
- Git identity is in the repo's local config. Use plain `git commit`; never
  pass `-c user.name=` or `-c user.email=`.
- End every commit message with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- Never commit anything under `.superpowers/` (gitignored).
- Run tests with `py -m pytest <path> -v` from the repo root. The interpreter
  is `py`, not `python3`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/hepataka_suffixes.py` | **Create.** One pure function splitting a `<strong>` text into (suffix tokens, semantic domain). Pure strings; no DB, no lxml, no `NN_*.py` import. Mirrors `scripts/suffix_forms.py` and `scripts/word_formation.py`. |
| `tests/test_hepataka_suffixes.py` | **Create.** Unit tests, including the verbatim raw strings. |
| `scripts/05_hepataka_parse.py` | **Modify.** Call the new splitter; emit `suffixes` into the record. |
| `scripts/05_hepataka_import.py` | **Modify.** DDL gains a column; `_INSERT_SQL` and the row tuple gain a field. |
| `scripts/50_build_unified.py` | **Modify.** `build_hepatakakupu` reads `suffixes` and writes `form` rows. |
| `tests/test_suffix_extraction.py` | **Modify.** Add a hepatakakupu floor. |

### Measured ground truth

Verified against the 14,996 local raw pages and the live database on
2026-09-18. These are the numbers the work must reproduce.

| | |
|---|---|
| raw pages on disk | **14,996** (no re-scrape needed) |
| `span.def` elements across them | **24,941** — exactly the `hepatakakupu_entries` row count |
| suffix tokens (sense level) | **22,911** |
| sense rows carrying ≥1 suffix token | **11,273** of 24,941 (45%) |
| expected `form` rows | **22,882** |
| distinct suffix types | **30** — 23 accepted, 7 refused across 8 tokens |
| rows in `hepatakakupu_entries` holding a suffix today | **3**, all incidental hyphens in a definition |
| `form` rows from hepatakakupu today | **0** |

**Why 22,882 and not 14,767:** `build_hepatakakupu` sets `seid = str(id_)`,
the sense-row primary key, so each sense becomes its own `entry`. `kake`'s
five senses are five entries, each carrying its own forms. Tokens and rows
are therefore nearly equal; the 29-token gap is tokens repeated inside one
sense plus the 8 refused. **A large gap would mean entries are wrongly
shared across senses.**

**One token is coerced, deliberately.** `_add_suffix_forms` looks the suffix
up as `classify(fold(suffix))`, which is how paekupu's legitimate `-hangā`
reaches `-hanga`. The same fold accepts hepatakakupu's single `-ā` as `-a`,
a passive. Māori has no `-ā` suffix, so that token is almost certainly a typo
for `-a` and the coercion is probably right — but it IS a coercion, it is one
row of 22,882, and it is the only token in this source whose fate folding
changes. Do not add a special case for it; record it.

### The single most important implementation detail

`<strong>` **has a child `<span>`** holding the part of speech:

```html
<strong>
    -tia -hia -ngia -tanga -nga
    [Tūmatauenga]
    <span class="class">mahw, ing, āhua</span>
</strong>
```

So `strong.text` returns exactly the suffixes and the bracket, stopping
before the child — which is what this work needs. `"".join(strong.itertext())`
would drag the POS text in and corrupt the parse.

**Use `strong.text`. Never `itertext()` here**, even though the same file
uses `itertext()` for usage examples a few lines below.

---

## Task 1: The `<strong>` splitter

**Files:**
- Create: `scripts/hepataka_suffixes.py`
- Create: `tests/test_hepataka_suffixes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `split_strong(text: str) -> tuple[list[str], str | None]` —
  returns `(suffix_tokens, semantic_domain)`. Tokens are `'-xxx'` strings in
  source order, unfiltered by vocabulary. The domain is the bracket contents,
  or `None`.

**Why unfiltered:** parse records what the source wrote; unify decides what it
means. The 8 malformed tokens (`-bga`, `-pukenga`) must survive into the JSON
so the refusal report can count them. Filtering here would hide them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_hepataka_suffixes.py`:

```python
"""Splitting a He Pātaka Kupu <strong> into its suffixes and its domain.

The parser has always read this element — it regexes the bracket out for
semantic_domain — and has always thrown the suffixes in front of it away.
Every string below is verbatim from sources/hepataka/raw/.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from hepataka_suffixes import split_strong


class SplitStrong(unittest.TestCase):
    def test_five_suffixes_and_a_domain(self):
        # sources/hepataka/raw/100.html
        text = ("\n   -tia -hia -ngia -tanga -nga\n   [Tūmatauenga]      ")
        self.assertEqual(split_strong(text),
                         (["-tia", "-hia", "-ngia", "-tanga", "-nga"],
                          "Tūmatauenga"))

    def test_two_suffixes_and_a_domain(self):
        # sources/hepataka/raw/1993.html — the 'kake' page
        self.assertEqual(split_strong("\n   -a -nga\n   [Tāne]   "),
                         (["-a", "-nga"], "Tāne"))

    def test_a_domain_with_no_suffixes(self):
        # 8,368 pages look like this. It is not an error.
        self.assertEqual(split_strong("\n   \n   [Tangaroa]   "),
                         ([], "Tangaroa"))

    def test_no_bracket_at_all(self):
        self.assertEqual(split_strong("   -tia   "), (["-tia"], None))

    def test_empty_and_none(self):
        self.assertEqual(split_strong(""), ([], None))
        self.assertEqual(split_strong(None), ([], None))

    def test_a_malformed_token_survives_the_split(self):
        # '-bga' is a typo for '-nga' in hepatakakupu's own text. Parse records
        # what the source wrote; the vocabulary filter at unify refuses it and
        # the refusal report counts it. Dropping it here would hide it.
        self.assertEqual(split_strong(" -bga [Tāne] "), (["-bga"], "Tāne"))

    def test_nothing_after_the_bracket_is_taken_as_a_suffix(self):
        # A hyphen inside the domain text must not become a token.
        self.assertEqual(split_strong(" -a [Tāne-nui] "), (["-a"], "Tāne-nui"))

    def test_macrons_are_preserved_in_a_token(self):
        self.assertEqual(split_strong(" -hangā [Tāne] "), (["-hangā"], "Tāne"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_hepataka_suffixes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hepataka_suffixes'`

- [ ] **Step 3: Write the implementation**

Create `scripts/hepataka_suffixes.py`:

```python
"""Split a He Pātaka Kupu <strong> into its suffixes and its domain.

Pure strings; no DB, no lxml.

The element holds a word's derived-form suffixes and then its semantic
domain in brackets:

    -tia -hia -ngia -tanga -nga
    [Tūmatauenga]

05_hepataka_parse.py has always regexed the bracket out and discarded
everything in front of it, losing every suffix hepatakakupu records — 22,911
tokens across 14,996 pages.

Tokens come back UNFILTERED and in source order. Parse records what the
source wrote; the vocabulary filter lives at unify, where the refusal report
can count what it rejects. Filtering here would hide the 8 malformed tokens
hepatakakupu's own text contains.
"""
import re

# The bracket opens the domain; everything before it is the suffix field.
_DOMAIN = re.compile(r"\[([^\]]*)\]")
_TOKEN = re.compile(r"-[a-zāēīōū]+", re.I)


def split_strong(text):
    """(suffix_tokens, semantic_domain) for a <strong>'s text.

    Pass `strong.text`, NOT `"".join(strong.itertext())`: the element has a
    child <span> carrying the part of speech, and .text stops before it.
    """
    text = text or ""
    match = _DOMAIN.search(text)
    head = text[:match.start()] if match else text
    domain = match.group(1).strip() if match else None
    return (_TOKEN.findall(head), domain or None)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_hepataka_suffixes.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Verify the tests can fail (mutation check)**

Change `head = text[:match.start()] if match else text` to `head = text`, so
the domain is no longer excluded, and re-run.
`test_nothing_after_the_bracket_is_taken_as_a_suffix` must fail — it will
return `['-a', '-nui']`. Restore and confirm green. Record what you observed.

- [ ] **Step 6: Commit**

```bash
git add scripts/hepataka_suffixes.py tests/test_hepataka_suffixes.py
git commit -m "feat(hepataka): split a <strong> into its suffixes and its domain

The parser has always read this element for the bracketed domain and thrown
the suffixes in front of it away. Tokens come back unfiltered so the nine
malformed ones in hepatakakupu's own text survive to be counted at unify.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Keep the suffixes at parse

**Files:**
- Modify: `scripts/05_hepataka_parse.py` (imports, and the POS + semantic
  domain block around lines 90-102)

**Interfaces:**
- Consumes: `split_strong(text)` from Task 1.
- Produces: each record in `sources/hepataka/parsed/hepataka_entries.json`
  gains `"suffixes": ["-a", "-nga"]`, defaulting to `[]`.

**The semantic domain must come out unchanged.** This parser currently
produces 24,941 correct rows and 24,645 domain values. The suffix capture is
an addition beside the domain extraction, not a rewrite of it.

- [ ] **Step 1: Read the block you are changing**

Run: `py -c "print(open('scripts/05_hepataka_parse.py',encoding='utf-8').read()[2600:3400])"`

Find the block that currently reads:

```python
            strong = def_span.find("strong")
            if strong is not None:
                m = re.search(r"\[([^\]]+)\]", strong.text or "")
                if m:
                    semantic_domain = m.group(1).strip()
```

- [ ] **Step 2: Add the import**

Near the other local imports at the top of `scripts/05_hepataka_parse.py`:

```python
from hepataka_suffixes import split_strong
```

Confirm the file already does `sys.path.insert(0, str(Path(__file__).parent))`
before its local imports; it does, for `utils`.

- [ ] **Step 3: Replace the block**

Declare `suffixes` beside the existing `pos` and `semantic_domain`
declarations, then replace the `strong` block:

```python
        pos: str | None = None
        semantic_domain: str | None = None
        suffixes: list[str] = []
        def_span = div.find('.//span[@class="def"]')
        if def_span is not None:
            cls_span = def_span.find('.//span[@class="class"]')
            if cls_span is not None:
                pos = _ws(cls_span.text or "").rstrip(".").strip() or None
            strong = def_span.find("strong")
            if strong is not None:
                # .text, not itertext(): <strong> has a child <span> holding
                # the part of speech, and .text stops before it. The suffixes
                # sit in front of the bracketed domain and were discarded
                # here until now — 22,911 tokens across 14,996 pages.
                suffixes, semantic_domain = split_strong(strong.text)
```

- [ ] **Step 4: Add `suffixes` to the emitted record**

Find the dict literal that builds each record (it already carries
`"semantic_domain": semantic_domain`) and add beside it:

```python
            "suffixes": suffixes,
```

- [ ] **Step 5: Verify against the raw pages without running the parser**

The parser writes a 14,996-page JSON and a subagent must not run it. Instead
prove the new code path on two pages directly:

```bash
py -c "
import sys; sys.path.insert(0,'scripts'); sys.stdout.reconfigure(encoding='utf-8')
from lxml import html as LH
from hepataka_suffixes import split_strong
for f,want in (('100','Tūmatauenga'),('1993','Tāne')):
    doc=LH.fromstring(open(f'sources/hepataka/raw/{f}.html',encoding='utf-8',errors='replace').read())
    sp=doc.findall('.//span[@class=\"def\"]')[0]
    print(f, split_strong(sp.find('strong').text))
"
```

Expected: `100 (['-tia', '-hia', '-ngia', '-tanga', '-nga'], 'Tūmatauenga')`
and `1993 (['-a', '-nga'], 'Tāne')`.

- [ ] **Step 6: Commit**

```bash
git add scripts/05_hepataka_parse.py
git commit -m "fix(hepataka): keep the suffixes the parser was discarding

The <strong> regex took the bracketed domain and dropped the suffix tokens
in front of it. Both now come out of one split. .text is deliberate: the
element has a child <span> carrying the part of speech.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Carry the suffixes into the table

**Files:**
- Modify: `scripts/05_hepataka_import.py` — the DDL (around line 52), the
  `_INSERT_SQL` (around line 82), and the row tuple (around line 135)

**Interfaces:**
- Consumes: `"suffixes"` in each parsed record, from Task 2.
- Produces: `hepatakakupu_entries.suffixes`, a JSON array text column
  defaulting to `'[]'`.

**No `ALTER TABLE`.** This importer drops and recreates
`hepatakakupu_entries` on every run, so the column belongs in the DDL. The
spec's `ALTER TABLE` line describes a path this codebase does not use.

- [ ] **Step 1: Add the column to the DDL**

In the `CREATE TABLE hepatakakupu_entries` block, after `semantic_domain TEXT,`:

```sql
        suffixes         TEXT DEFAULT '[]',      -- JSON array of '-tia' tokens
```

This matches the table's existing convention for `usage_examples`,
`synonyms` and `synonym_senses`.

- [ ] **Step 2: Add it to the INSERT**

```python
_INSERT_SQL = """
    INSERT INTO hepatakakupu_entries
        (id, word_id, headword, headword_sort, headword_search,
         part_of_speech, definition, usage_examples,
         sense_number, synonyms, synonym_senses,
         master_word_id, master_sense, semantic_domain, suffixes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
```

Count the placeholders: **15**. The old statement had 14.

- [ ] **Step 3: Add it to the row tuple**

After `r.get("semantic_domain"),`:

```python
                    json.dumps(r.get("suffixes") or [], ensure_ascii=False),
```

- [ ] **Step 4: Verify the statement is consistent without running the import**

```bash
py -c "
import re
s=open('scripts/05_hepataka_import.py',encoding='utf-8').read()
sql=re.search(r'_INSERT_SQL = \"\"\"(.*?)\"\"\"', s, re.S).group(1)
cols=re.search(r'\((.*?)\)\s*VALUES', sql, re.S).group(1)
n_cols=len([c for c in cols.replace('\n',' ').split(',') if c.strip()])
n_q=sql.count('?')
print('columns:', n_cols, 'placeholders:', n_q, 'MATCH' if n_cols==n_q else 'MISMATCH')
print('suffixes in DDL:', 'suffixes         TEXT' in s)
"
```

Expected: `columns: 15 placeholders: 15 MATCH` and `suffixes in DDL: True`.

- [ ] **Step 5: Commit**

```bash
git add scripts/05_hepataka_import.py
git commit -m "feat(hepataka): carry the parsed suffixes into the table

A JSON array column beside semantic_domain, matching the table's existing
convention for usage_examples and synonyms. The importer drops and recreates
the table on every run, so the column belongs in the DDL, not an ALTER.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Write the form rows at unify

**Files:**
- Modify: `scripts/50_build_unified.py` — `build_hepatakakupu`
- Modify: `tests/test_suffix_extraction.py` — add the hepatakakupu floor
- Create: `tests/test_hepataka_wiring.py`

**Interfaces:**
- Consumes: `hepatakakupu_entries.suffixes` from Task 3, and these, already
  shipped in `scripts/50_build_unified.py`:
  - `_add_suffix_forms(b, entry_id, headword, suffixes, source)` — classifies
    each suffix (folding at the lookup site), composes it against `headword`,
    writes through `add_form`, and increments `b.derived_forms_written` only
    when a row actually lands
  - `b.suffix_tally` — the `Tally` the refusal report prints from
  - `jload(text)` — the file's JSON-array helper
- Produces: ~22,882 `form` rows with `source_id = 'hepatakakupu'`.

**The headword needs no stripping.** hepatakakupu writes its suffixes in a
separate element, so `hw` is already bare — unlike paekupu, whose headword
carries `~nga`. Do not route it through `strip_suffix_notation`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_hepataka_wiring.py`:

```python
"""hepatakakupu's suffixes reach the form table, one entry per sense.

These drive the shipped helper against an in-memory database, so no part of
the real pipeline runs. Per-source counts live in test_suffix_extraction.py,
which needs a built database.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "build_unified",
    Path(__file__).parent.parent / "scripts" / "50_build_unified.py")
build_unified = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_unified)


def _memory_db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
            headword TEXT, headword_sort TEXT, headword_search TEXT,
            homonym_no INTEGER, headword_en TEXT, part_of_speech TEXT,
            loan_marker TEXT, dialect TEXT, audio_url TEXT, locator TEXT,
            content_hash TEXT, first_seen TEXT, created_at TEXT,
            last_updated TEXT);
        CREATE TABLE form (
            id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT,
            form_search TEXT, form_type TEXT, note TEXT);
    """)
    return con


class HepatakakupuSuffixes(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "hepatakakupu", None, {})

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_a_passive_and_a_nominalisation_are_typed_apart(self):
        eid = self.b.add_entry("1", "kake", "kake", "kake")
        build_unified._add_suffix_forms(self.b, eid, "kake", ["-a", "-nga"],
                                        "hepatakakupu")
        self.assertEqual(self._rows(),
                         [("kakea", "passive", "-a (hepatakakupu)"),
                          ("kakenga", "nominalisation", "-nga (hepatakakupu)")])

    def test_each_sense_is_its_own_entry_and_carries_its_own_forms(self):
        # build_hepatakakupu keys entries on the sense row id, so kake's
        # senses do NOT share an entry and their forms do not collapse.
        first = self.b.add_entry("10281", "kake", "kake", "kake")
        second = self.b.add_entry("25391", "kake", "kake", "kake")
        for eid in (first, second):
            build_unified._add_suffix_forms(self.b, eid, "kake", ["-a"],
                                            "hepatakakupu")
        self.assertEqual(len(self._rows()), 2)

    def test_a_malformed_suffix_writes_nothing_but_is_counted(self):
        eid = self.b.add_entry("1", "kake", "kake", "kake")
        build_unified._add_suffix_forms(self.b, eid, "kake", ["-bga"],
                                        "hepatakakupu")
        self.assertEqual(self._rows(), [])
        self.assertEqual(self.b.suffix_tally.refused, ["-bga"])

    def test_macrons_survive_composition(self):
        eid = self.b.add_entry("1", "tūkino", "tukino", "tukino")
        build_unified._add_suffix_forms(self.b, eid, "tūkino", ["-tia"],
                                        "hepatakakupu")
        self.assertIn(("tūkinotia", "passive", "-tia (hepatakakupu)"),
                      self._rows())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_hepataka_wiring.py -v`
Expected: `test_a_malformed_suffix_writes_nothing_but_is_counted` FAILS —
`_add_suffix_forms` does not populate a tally the test can read, or the
attribute name differs.

**Before changing anything, read `_add_suffix_forms` and the `Tally` class in
`scripts/50_build_unified.py` and `scripts/suffix_forms.py`.** They shipped on
2026-09-18. Adjust this test to the real attribute names rather than changing
the shipped helper — the other three tests must pass as written. Say in your
report what the real names are.

- [ ] **Step 3: Add `suffixes` to the SELECT**

In `build_hepatakakupu`, the query currently ends
`"... master_word_id, master_sense, semantic_domain "`. Add the column:

```python
    sql = ("SELECT id, word_id, headword, headword_sort, headword_search, "
           "part_of_speech, definition, usage_examples, sense_number, synonyms, "
           "synonym_senses, master_word_id, master_sense, semantic_domain, "
           "suffixes "
           "FROM hepatakakupu_entries ORDER BY word_id, sense_number, id")
```

and add `suffixes` to the end of the unpacking tuple:

```python
    for (id_, wid, hw, hs, hse, pos, d, ux, sn, syn, syn_senses,
         master_wid, master_sn, dom, suffixes) in con.execute(sql):
```

- [ ] **Step 4: Write the form rows**

Immediately after the existing `eid = b.add_entry(...)` call in that loop:

```python
        # hepatakakupu records its suffixes in a separate element, so hw is
        # already bare — no strip_suffix_notation, unlike paekupu. Each row
        # here is one SENSE and mints its own entry, so these forms do not
        # collapse across a word's senses.
        _add_suffix_forms(b, eid, hw, jload(suffixes), "hepatakakupu")
```

- [ ] **Step 5: Run the wiring tests**

Run: `py -m pytest tests/test_hepataka_wiring.py tests/test_hepataka_suffixes.py -v`
Expected: PASS.

- [ ] **Step 6: Add the hepatakakupu floor**

In `tests/test_suffix_extraction.py`, extend `FLOORS`:

```python
FLOORS = (("hepatakakupu", 20500), ("ngata", 4100), ("te_aka", 4800),
          ("paekupu", 1600), ("papakupu", 185), ("williams", 31),
          ("kimikupu_hou", 15))
```

20,500 is ~90% of the measured 22,882, the same margin the other six use.
Update the module docstring's simulated-totals line to include
`hepatakakupu 22,882` and a corpus total of `34,977`.

**This floor fails until the controller rebuilds in Task 5.** That is
expected. Do not weaken it.

- [ ] **Step 7: Run the unit suites**

Run: `py -m pytest tests/test_hepataka_suffixes.py tests/test_hepataka_wiring.py tests/test_suffix_forms.py tests/test_suffix_wiring.py tests/test_form_dedupe.py tests/test_build_unified_fk.py -v`
Expected: PASS. Report `tests/test_suffix_extraction.py` separately as
failing-by-design pending the rebuild.

- [ ] **Step 8: Commit**

```bash
git add scripts/50_build_unified.py tests/test_hepataka_wiring.py tests/test_suffix_extraction.py
git commit -m "feat(unified): write hepatakakupu's derived forms

Reuses _add_suffix_forms unchanged — hepatakakupu contributes a reader and
nothing more. Its headword needs no stripping because the suffixes live in a
separate element, and each row is one sense with its own entry, so the forms
do not collapse across a word's senses.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Re-parse, rebuild, and gate

**Run by the controller in the main session, never by a subagent.**

- [ ] **Step 1: Snapshot the judgements**

```bash
py scripts/61_export_judgements.py
git add data/judgements.json && git commit -m "chore(sweep): snapshot judgements before the hepatakakupu rebuild

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

If the file is byte-identical there is nothing to commit; say so and move on.

- [ ] **Step 2: Record the before-state**

```bash
py -c "
import sqlite3
c=sqlite3.connect('file:data/staging_dictionary.db?mode=ro',uri=True)
for t in ('entry','sense','relation','form','concept','derivation'):
    print(f'{t:<12}{c.execute(f\"SELECT COUNT(*) FROM {t}\").fetchone()[0]:>9,}')
print('judged', c.execute(\"SELECT COUNT(*) FROM concept_member WHERE status<>'proposed'\").fetchone()[0])
print(c.execute(\"SELECT form_type, COUNT(*) FROM form GROUP BY 1 ORDER BY 2 DESC\").fetchall())
"
```

Expected before: `entry` 153,440 · `sense` 175,101 · `relation` 180,053 ·
`form` 12,739 · `derivation` 6,778 · judged 18.

- [ ] **Step 3: Re-parse the 14,996 local pages**

```bash
py scripts/05_hepataka_parse.py
```

No network access. Then confirm the JSON carries suffixes:

```bash
py -c "
import json
r=json.load(open('sources/hepataka/parsed/hepataka_entries.json',encoding='utf-8'))
n=sum(1 for x in r if x.get('suffixes'))
t=sum(len(x.get('suffixes') or []) for x in r)
print(f'records {len(r):,}  with suffixes {n:,}  tokens {t:,}')
print('domains still populated:', sum(1 for x in r if x.get('semantic_domain')))
"
```

Expected: `records 24,941`, `with suffixes 11,273`, `tokens 22,911`.
**`domains still populated` must be ~24,645** — if it dropped, the split
broke the extraction it was meant to leave alone. Stop and investigate.

- [ ] **Step 4: Re-import**

```bash
py scripts/05_hepataka_import.py
```

Then verify the regression guard the spec demands — the row count and the
domain values must be untouched:

```bash
py -c "
import sqlite3
c=sqlite3.connect('file:data/staging_dictionary.db?mode=ro',uri=True)
print('rows', c.execute('SELECT COUNT(*) FROM hepatakakupu_entries').fetchone()[0], '(want 24,941)')
print('domains', c.execute('SELECT COUNT(*) FROM hepatakakupu_entries WHERE semantic_domain IS NOT NULL').fetchone()[0])
print('with suffixes', c.execute('SELECT COUNT(*) FROM hepatakakupu_entries WHERE suffixes <> \'[]\'').fetchone()[0], '(want 11,271)')
"
```

- [ ] **Step 5: Re-unify ALL sources**

```bash
py scripts/50_build_unified.py --source all
```

**`--source all`, never a single source.** Running one alone calls
`delete_source_slice`, which nulls other sources' relations into the deleted
slice — it halved the `derivation` table once before. Read the script's
output; do not pipe it to `tail`. The `[hepatakakupu] suffix-forms:` line
should read **22,911 seen, 22,882 written, 8 refused** — the refused values
being `-bga`, `-tiha`, `-rapā`, `-rapaia`, `-pukea`, `-pihanga` and
`-pukenga` (×2), all typos or whole words mis-marked as suffixes in
hepatakakupu's own text.

- [ ] **Step 6: Rebuild the derived layer**

```bash
py scripts/59_rebuild_derived.py
```

- [ ] **Step 7: Run the gates**

```bash
py -m pytest tests/test_concept_acceptance.py -v
py -m pytest tests/test_suffix_extraction.py tests/test_hepataka_wiring.py -v
py -m pytest tests/ -q
```

The four calibration answers and the `hoi` ≥ 7 chaining guard must hold.
**If one fails, stop** — this plan does not touch `headword_search`, so a
calibration failure means something unexpected moved and the rule is wrong,
not the test.

- [ ] **Step 8: Report the corpus**

```bash
py -c "
import sqlite3
c=sqlite3.connect('file:data/staging_dictionary.db?mode=ro',uri=True)
D=('passive','nominalisation')
for r in c.execute('SELECT e.source_id, COUNT(*) FROM form f JOIN entry e ON e.id=f.entry_id WHERE f.form_type IN (?,?) GROUP BY 1 ORDER BY 2 DESC',D): print(r)
print('TOTAL', c.execute('SELECT COUNT(*) FROM form WHERE form_type IN (?,?)',D).fetchone()[0])
print(c.execute('SELECT form_type, COUNT(*) FROM form WHERE form_type IN (?,?) GROUP BY 1',D).fetchall())
"
```

Expected total **~34,977**, with `nominalisation` rising from 693 to roughly
15,250 — hepatakakupu is 14,560 nominalising against 8,342 passive, the
inverse of every other source. Confirm `entry`, `sense`, `relation` and
`derivation` match Step 2, and that the 18 judgements survived.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 the defect, `.text` not `itertext()` | 1, 2 |
| §2 measured counts, 22,882 expected rows | File Structure, 4 (floor), 5 (Step 8) |
| §3 schema column | 3 |
| §3 parser | 2 |
| §3 re-parse of 14,996 local pages | 5 (Step 3) |
| §3 extraction reusing `_add_suffix_forms` | 4 |
| §4 composition against the headword | 4 (Step 4) |
| §5 re-parse must not disturb the domain | 5 (Steps 3, 4) |
| §5 the three-number report | 5 (Step 5) |
| §5 empty case is not an error | 1 (`test_a_domain_with_no_suffixes`) |
| §5 existing `form` rows untouched | 5 (Step 8) |
| §5 no calibration gate needed here | 5 (Step 7), stated |
| §6 parser tests against verbatim raw | 1 |
| §6 domain must survive every case | 1, 5 (Steps 3, 4) |
| §6 malformed refused and counted | 1, 4 |
| §6 composition | 4 |
| §6 dedup | 4 (`test_each_sense_is_its_own_entry...`) |
| §6 re-parse idempotence | see gap below |

**Gap found and closed:** §6 asks for a re-parse idempotence test — running
the parser twice yields the same table. No task owns it, because a subagent
cannot run the parser and the controller runs it once. **Task 5 Step 3's
record/token/domain assertions serve the same purpose**: they pin the
parser's output to exact counts, so a second run producing anything different
fails there. A standalone idempotence test would need two full 14,996-page
runs to prove what those three numbers already pin.

**Placeholder scan:** none. Every code step carries real code. Task 4 Step 2
directs the implementer to read the shipped helper and adapt the test's
attribute names — that is verification against code that already exists, not
a placeholder, and the other three tests are exact.

**Type consistency:** `split_strong` returns `tuple[list[str], str | None]`
in Task 1, is consumed that way in Task 2, and its list is JSON-encoded in
Task 3 and `jload`-decoded in Task 4. `_add_suffix_forms(b, entry_id,
headword, suffixes, source)` matches the shipped signature. `suffixes` names
the same thing in the parser record, the column, the SELECT and the loop.
