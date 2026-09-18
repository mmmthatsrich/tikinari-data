# Irregular Whole Forms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the sixteen whole irregular derived forms paekupu prints after a tilde and the pipeline currently discards.

**Architecture:** A new pure reader in `scripts/suffix_forms.py` returns the tilde runs the suffix vocabulary does not recognise, classified by the suffix their first element ends with. A new sibling of `_add_suffix_forms` in `scripts/50_build_unified.py` writes them verbatim — these cannot be composed, which is the whole reason the source prints them in full. Wired into `build_paekupu` only.

**Tech Stack:** Python 3.12, SQLite, `unittest` via `pytest`, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-19-irregular-whole-forms-design.md`

## Global Constraints

- The suffix vocabulary is **23 spellings**: 14 in `PASSIVE`, 9 in `NOMINALISATION`. Do not add to it.
- `classify()` **never folds** — that is a standing contract of the module. Fold at the call site, look up the folded value, store the original spelling.
- Store the form **exactly as the source spells it**, macrons and all. Never compose a whole form.
- The note format is `'<suffix> (paekupu, whole)'` — for example `'-a (paekupu, whole)'`.
- `strip_suffix_notation` **must not change**. Seven existing tests depend on its truncation, and `headword_search` is built from it.
- The malformed-form guard in `tests/test_suffix_extraction.py` **must not be weakened**. It does not reject spaces and must not start to: 153 existing derived forms are legitimately multi-word.
- Never run `50_build_unified.py`, `59_rebuild_derived.py` or steps 52/08b/53/54/60 against the real database **from a subagent**. Task 3 is the controller's own work.
- `59_rebuild_derived.py` takes no flags and executes on any argument, including `--help`. Never pipe it through `head`; redirect to a file.
- Git identity is already set in the repo's local config. Use plain `git commit`, never `-c user.name=`.
- End every commit message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/suffix_forms.py` | Add `_classify_whole` and `read_whole_forms`. Pure strings; no DB. | 1 |
| `tests/test_whole_forms.py` | New. Unit tests for the reader, one per shape. | 1 |
| `scripts/50_build_unified.py` | Add `_add_whole_forms`; call it from `build_paekupu`. | 2 |
| `tests/test_whole_form_wiring.py` | New. Drives `build_paekupu` against an in-memory DB. | 2 |
| `tests/test_whole_forms_corpus.py` | New. Counts against the rebuilt database. | 3 |

---

### Task 1: The reader

**Files:**
- Modify: `scripts/suffix_forms.py` (add after `read_bracket_suffixes`, before `strip_suffix_notation`)
- Test: `tests/test_whole_forms.py` (create)

**Interfaces:**
- Consumes: `PASSIVE`, `NOMINALISATION`, `fold`, `classify` — all already in the module.
- Produces: `read_whole_forms(headword) -> [(form, suffix, form_type), ...]` where `form` is the whole word as the source spells it, `suffix` is a vocabulary spelling like `'-tia'`, and `form_type` is `'passive'` or `'nominalisation'`. Task 2 consumes this exact triple.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_whole_forms.py`:

```python
"""paekupu prints a whole irregular derivation where no fragment could work.

'hau ~hāua' names 'hāua', not 'hau' + '-hāua'. The stem changes — the vowel
lengthens, or a reduplication is undone — so the form cannot be composed and
the source writes it out in full. read_whole_forms recovers those runs;
read_tilde_suffixes continues to own the runs that ARE recognised fragments.

See docs/superpowers/specs/2026-09-19-irregular-whole-forms-design.md §3.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import read_whole_forms, strip_suffix_notation


class ReadWholeForms(unittest.TestCase):
    def test_a_lengthened_vowel_is_read_whole(self):
        # 'hāua' is 'hau' with the vowel lengthened; no suffix fragment
        # could produce it from 'hau'.
        self.assertEqual(read_whole_forms("hau ~hāua ~tanga"),
                         [("hāua", "-a", "passive")])

    def test_a_contracted_stem_is_read_whole(self):
        self.assertEqual(read_whole_forms("kukuti ~nga ~kūtia"),
                         [("kūtia", "-tia", "passive")])

    def test_run_order_does_not_matter(self):
        # paekupu prints this entry twice with the runs in either order.
        self.assertEqual(read_whole_forms("kukuti ~kūtia ~nga"),
                         [("kūtia", "-tia", "passive")])

    def test_one_headword_can_name_both_classes(self):
        # The reduplication in 'momotu' is undone in both derivations.
        self.assertEqual(read_whole_forms("momotu ~motukia ~motuhanga"),
                         [("motukia", "-kia", "passive"),
                          ("motuhanga", "-hanga", "nominalisation")])

    def test_a_multi_word_form_keeps_its_particle(self):
        # 'kawea atu' is 'kawe' + '-a' plus the directional particle. The
        # suffix must be read off the FIRST element: the last characters of
        # the run are 'tu', which is not a suffix.
        self.assertEqual(read_whole_forms("kaweatu ~kawea atu"),
                         [("kawea atu", "-a", "passive")])

    def test_a_hyphenated_form_reads_its_first_element(self):
        self.assertEqual(
            read_whole_forms("tāpiri-atu ~tāpiritia-atu ~tāpiritanga-atu"),
            [("tāpiritia-atu", "-tia", "passive"),
             ("tāpiritanga-atu", "-tanga", "nominalisation")])

    def test_the_longest_matching_suffix_wins(self):
        # 'tākina' ends with '-ina' and with '-kina'; the longer is correct,
        # the same longest-match rule the rest of the module applies.
        self.assertEqual(read_whole_forms("taki ~tākina"),
                         [("tākina", "-kina", "passive")])

    def test_a_recognised_fragment_is_not_a_whole_form(self):
        # read_tilde_suffixes owns these. Returning them here would write the
        # fragment '-nga' into the form column as if it were a word.
        self.assertEqual(read_whole_forms("ahu ~nga"), [])

    def test_a_headword_with_no_tilde_yields_nothing(self):
        self.assertEqual(read_whole_forms("ahu"), [])

    def test_empty_input_is_tolerated(self):
        self.assertEqual(read_whole_forms(""), [])
        self.assertEqual(read_whole_forms(None), [])

    def test_a_parenthesised_fragment_is_still_a_fragment(self):
        # 'heke (~nga) atu' — the closing paren rides along on the token and
        # must not turn a known suffix into an unknown whole form.
        self.assertEqual(read_whole_forms("heke (~nga) atu"), [])
        self.assertEqual(read_whole_forms("rārangi (~tanga) kōrero"), [])

    def test_a_comma_separated_run_stops_at_the_comma(self):
        # papakupu separates with commas and semicolons, and a run must
        # never swallow the word after one. The head here must be OUTSIDE
        # the vocabulary: a recognised head is discarded before _RUN_TAIL
        # is ever consulted, so a case like 'pūrua ~tia, pūtoru' would pass
        # this test with the comma rule deleted.
        self.assertEqual(read_whole_forms("x ~kūtia, pūtoru"),
                         [("kūtia", "-tia", "passive")])

    def test_an_unclassifiable_run_writes_nothing(self):
        # The vocabulary is the only thing separating a real derivation from
        # a typo. '~xyzzy' ends in no known suffix and is refused.
        self.assertEqual(read_whole_forms("kupu ~xyzzy"), [])

    def test_a_run_that_is_only_a_suffix_is_not_a_word(self):
        # A bare '~ia' is a fragment, not a whole form: there is nothing in
        # front of the suffix for it to be a derivation OF.
        self.assertEqual(read_whole_forms("kupu ~ia"), [])


class StripIsUnchanged(unittest.TestCase):
    """The new reader must not disturb how the search key is built."""

    def test_the_base_is_still_truncated_at_an_irregular_tilde(self):
        self.assertEqual(strip_suffix_notation("hau ~hāua ~tanga"), "hau")

    def test_a_multi_word_base_is_still_kept_whole(self):
        self.assertEqual(strip_suffix_notation("tiki atu ~tīkina atu"),
                         "tiki atu")

    def test_a_recognised_suffix_is_still_stripped(self):
        self.assertEqual(strip_suffix_notation("ahu ~nga"), "ahu")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_whole_forms.py -q`

Expected: the `ReadWholeForms` tests fail with `ImportError: cannot import name 'read_whole_forms'`. If any `StripIsUnchanged` test fails, stop — `strip_suffix_notation` is already broken and that is not this task's doing.

- [ ] **Step 3: Add the regexes**

In `scripts/suffix_forms.py`, beside the existing pattern definitions (after `_HYPHEN_TOKEN`):

```python
# A tilde run reaching to the next tilde or the end of the string. The whole
# form may be several words ('~kawea atu') or hyphenated ('~tāpiritia-atu'),
# so _TILDE_TOKEN — which stops at the first non-letter — cannot express it.
_TILDE_RUN = re.compile(r"~\s*([^~]+)")
# papakupu separates its runs with commas and at least once a semicolon; a
# run must never swallow the word after the separator.
_RUN_TAIL = re.compile(r"\s*[,;].*$", re.S)
```

- [ ] **Step 4: Add the classifier and the reader**

After `read_bracket_suffixes`:

```python
def _classify_whole(word):
    """The longest vocabulary suffix *word* ends with, and its class.

    Unlike _keep_known, which matches a whole token against the vocabulary,
    this asks what a COMPLETE word ends with: 'kūtia' is not the suffix
    '-tia' but a word carrying it. Longest match first, so 'tākina' reads
    '-kina' rather than '-ina'.

    A word that is nothing but the suffix is refused: a bare '~ia' has no
    stem in front of it, so there is no word for it to be a derivation of.
    """
    folded = fold(word)
    for suffix in sorted(PASSIVE + NOMINALISATION, key=len, reverse=True):
        ending = suffix[1:]
        if len(folded) > len(ending) and folded.endswith(ending):
            return suffix, classify(suffix)
    return None, None


def read_whole_forms(headword):
    """[(form, suffix, form_type)] for each tilde run naming a WHOLE word.

    paekupu prints a whole irregular derivation after a tilde where no
    fragment could express it — the stem itself changes:

        hau    -> hāua      the vowel lengthens
        kukuti -> kūtia     the stem contracts
        momotu -> motukia   the reduplication is undone

    A run whose first element IS a known suffix is left alone:
    read_tilde_suffixes owns those, and returning '-nga' here would write a
    fragment into the form column as though it were a word.

    The suffix is read off the run's FIRST element, split on whitespace or
    hyphen, because the form may carry a directional particle: 'kawea atu'
    ends in 'tu', which is not a suffix, while its first element 'kawea'
    ends in '-a', which is.

    Takes no tally, deliberately. Every run here has already been seen and
    refused by read_tilde_suffixes on the same headword — _TILDE_TOKEN
    matches '~hāua' and _keep_known refuses it — so tallying again would
    count each token twice. The consequence is that the refusal report still
    lists these sixteen as refused; the report is a diagnostic, not data,
    and reconciling it belongs with the known Tally defect rather than here.

    See docs/superpowers/specs/2026-09-19-irregular-whole-forms-design.md.
    """
    out = []
    for match in _TILDE_RUN.finditer(headword or ""):
        run = _RUN_TAIL.sub("", match.group(1)).strip()
        if not run:
            continue
        # '(~nga)' leaves the paren riding on the token; strip it before the
        # vocabulary lookup or a known suffix reads as an unknown word.
        head = re.split(r"[\s\-]", run)[0].strip("().,;")
        if classify("-" + fold(head)):
            continue
        suffix, form_type = _classify_whole(head)
        if form_type:
            out.append((run, suffix, form_type))
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_whole_forms.py -q`
Expected: 16 passed.

- [ ] **Step 6: Verify nothing else regressed**

Run: `python -m pytest tests/test_suffix_forms.py tests/test_suffix_wiring.py -q`
Expected: all pass. `strip_suffix_notation` was not touched, so its seven tests must still be green.

- [ ] **Step 7: Commit**

```bash
git add scripts/suffix_forms.py tests/test_whole_forms.py
git commit -m "feat(suffixes): read paekupu's whole irregular derived forms

'hau ~hāua' names a whole word, not a fragment: the stem changes, so no
suffix could compose it from 'hau'. read_whole_forms returns the tilde runs
the vocabulary does not recognise, classified by the suffix their first
element ends with — the first element, because 'kawea atu' ends in 'tu'
while the word carrying the suffix is 'kawea'.

read_tilde_suffixes keeps the runs that ARE fragments, and
strip_suffix_notation is untouched: headword_search still keys on 'hau'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Writing the rows

**Files:**
- Modify: `scripts/50_build_unified.py` — add `_add_whole_forms` beside `_add_suffix_forms`; call it in `build_paekupu` (around line 711, immediately after the `composition_bases` loop)
- Test: `tests/test_whole_form_wiring.py` (create)

**Interfaces:**
- Consumes: `read_whole_forms(headword) -> [(form, suffix, form_type), ...]` from Task 1; `Builder.add_form(entry_id, form, form_type, note) -> bool`, which returns True only when a row actually landed.
- Produces: `_add_whole_forms(b, entry_id, forms, source)`, returning None.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_whole_form_wiring.py`:

```python
"""build_paekupu writes the whole form verbatim, never composed.

Drives the real builder against an in-memory database, so no part of the
pipeline runs. Corpus counts live in tests/test_whole_forms_corpus.py.
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


class AddWholeForms(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "paekupu", None, {})
        self.eid = self.b.add_entry("hau-3", "hau ~hāua ~tanga", "hau", "hau")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_the_form_is_stored_exactly_as_printed(self):
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        self.assertEqual(self._rows(), [("hāua", "passive", "-a (paekupu, whole)")])

    def test_the_note_marks_it_as_printed_not_composed(self):
        # The suffix in the note is our inference from the spelling, not a
        # fragment the source wrote; ', whole' is what records that.
        build_unified._add_whole_forms(
            self.b, self.eid, [("motuhanga", "-hanga", "nominalisation")],
            "paekupu")
        self.assertEqual(self._rows()[0][2], "-hanga (paekupu, whole)")

    def test_the_note_still_matches_the_per_suffix_query_shape(self):
        # tests/test_suffix_extraction.py requires every derived form's note
        # to match '-%(%)%'; the per-suffix counts depend on it.
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM form WHERE note NOT LIKE '-%(%)%'"
        ).fetchone()[0], 0)

    def test_a_multi_word_form_is_not_split(self):
        build_unified._add_whole_forms(
            self.b, self.eid, [("kawea atu", "-a", "passive")], "paekupu")
        self.assertEqual(self._rows()[0][0], "kawea atu")

    def test_nothing_is_composed_onto_the_headword(self):
        # The bug this guards: reusing _add_suffix_forms would store
        # 'hauhāua', a word attested nowhere in the corpus.
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        self.assertNotIn("hauhāua", [r[0] for r in self._rows()])

    def test_an_empty_list_writes_nothing(self):
        build_unified._add_whole_forms(self.b, self.eid, [], "paekupu")
        self.assertEqual(self._rows(), [])

    def test_the_row_counter_counts_rows_that_landed(self):
        before = self.b.derived_forms_written
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        # add_form dedupes on (entry, form, type): the second is not a row.
        self.assertEqual(self.b.derived_forms_written - before, 1)


class BuildPaekupuWiring(unittest.TestCase):
    """The reader reaches the builder for a real paekupu headword."""

    def setUp(self):
        self.con = _memory_db()
        self.con.executescript("""
            CREATE TABLE paekupu_entries (
                id INTEGER PRIMARY KEY, slug TEXT, headword TEXT,
                headword_sort TEXT, headword_search TEXT, headword_en TEXT,
                part_of_speech TEXT, definition TEXT, definition_mi TEXT,
                usage_examples TEXT, audio_url TEXT, alternative_words TEXT,
                subject_areas TEXT, subject_area TEXT, subject_area_en TEXT);
            CREATE TABLE sense (
                id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
                parent_sense_id INTEGER, gloss_en TEXT, gloss_mi TEXT,
                definition_raw TEXT, part_of_speech TEXT,
                part_of_speech_en TEXT, register TEXT, sort_no INTEGER,
                note TEXT);
            CREATE TABLE example (
                id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
                text_mi TEXT, text_en TEXT, source_abbrev TEXT,
                citation TEXT, sort_no INTEGER);
            CREATE TABLE relation (
                id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
                target_headword TEXT, target_entry_id INTEGER,
                target_sense_id INTEGER, note TEXT);
            CREATE TABLE entry_domain (
                id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
                domain TEXT, domain_lang TEXT);
            INSERT INTO paekupu_entries
                (slug, headword, headword_sort, headword_search, headword_en,
                 part_of_speech, definition, definition_mi, usage_examples,
                 audio_url, alternative_words, subject_areas, subject_area,
                 subject_area_en)
            VALUES ('hau-3', 'hau ~hāua ~tanga', 'hau', 'hau', 'wind',
                    'v', NULL, NULL, '[]', NULL, '[]', '[]', NULL, NULL);
        """)
        self.b = build_unified.Builder(self.con, "paekupu", None, {})
        build_unified.build_paekupu(self.con, self.b)

    def test_both_the_composed_and_the_whole_form_are_written(self):
        # '~tanga' is a recognised fragment and composes to 'hautanga';
        # '~hāua' is the whole irregular form. The entry needs both.
        self.assertEqual(
            self.con.execute("SELECT form, form_type, note FROM form "
                             "ORDER BY form").fetchall(),
            [("hautanga", "nominalisation", "-tanga (paekupu)"),
             ("hāua", "passive", "-a (paekupu, whole)")])

    def test_the_entry_still_keys_on_the_bare_base(self):
        # strip_suffix_notation feeds headword_search; the whole form must
        # not leak into it.
        self.assertEqual(self.con.execute(
            "SELECT headword_search FROM entry").fetchone()[0], "hau")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_whole_form_wiring.py -q`
Expected: FAIL with `AttributeError: module 'build_unified' has no attribute '_add_whole_forms'`.

- [ ] **Step 3: Add `_add_whole_forms`**

In `scripts/50_build_unified.py`, immediately after `_add_suffix_forms`:

```python
def _add_whole_forms(b, entry_id, forms, source):
    """Write a whole irregular derived form exactly as the source printed it.

    _add_suffix_forms cannot be reused: it composes, and these forms exist
    precisely because composing does not work — 'hau' + '-hāua' is
    'hauhāua', a word no dictionary in the corpus holds.

    Where the corpus can corroborate the whole-form reading it does, by
    EXACT spelling: 'motuhanga' is a headword in four sources, 'tākina' in
    two, 'kūtia' and 'wetekina' in ngata. 'hāua' itself rests on paekupu
    alone — it is attested in no other source, and the eight entries that
    share its FOLDED key are 'hauā' and 'Hauā', a different word. Never
    count attestation on headword_search; that key strips macrons and
    collapses doubled vowels, and reading a count off it is the specific
    error the spec's §2 exists to warn about.

    The note carries ', whole' because the suffix in it is read off the
    form's spelling rather than printed by the source as a fragment. The
    '<suffix> (<source>...)' shape is preserved so the per-suffix counts
    keep working.
    """
    for form, suffix, form_type in forms or []:
        if b.add_form(entry_id, form, form_type, f"{suffix} ({source}, whole)"):
            b.derived_forms_written += 1
```

- [ ] **Step 4: Wire it into `build_paekupu`**

Find this block (around line 709):

```python
        suffixes = suffix_forms.read_tilde_suffixes(hw, b.suffix_tally)
        for base in suffix_forms.composition_bases(hw):
            _add_suffix_forms(b, eid, base, suffixes, "paekupu")
```

Replace with:

```python
        suffixes = suffix_forms.read_tilde_suffixes(hw, b.suffix_tally)
        for base in suffix_forms.composition_bases(hw):
            _add_suffix_forms(b, eid, base, suffixes, "paekupu")
        # A tilde run the vocabulary does not recognise is a whole irregular
        # derivation, not a suffix — 'hau ~hāua'. It is stored as printed;
        # composing it would assert a word no source holds.
        _add_whole_forms(b, eid, suffix_forms.read_whole_forms(hw), "paekupu")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_whole_form_wiring.py -q`
Expected: 9 passed.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`

Expected: everything passes except `tests/test_whole_forms_corpus.py`, which does not exist yet. The corpus counts in `tests/test_suffix_extraction.py` read the database, which Task 3 has not rebuilt — they must still pass, because the floors are floors.

- [ ] **Step 7: Commit**

```bash
git add scripts/50_build_unified.py tests/test_whole_form_wiring.py
git commit -m "feat(unified): store paekupu's whole irregular forms verbatim

_add_suffix_forms composes, which is exactly what these sixteen forms
cannot survive: 'hau' + '-hāua' is 'hauhāua', attested nowhere, while the
source's own 'hāua' is attested in paekupu alone — and the eight entries
sharing its folded key are 'hauā', a different word. _add_whole_forms
writes the string the source printed and marks the note ', whole' to record
that its suffix is our reading of the spelling rather than a fragment
paekupu wrote.

Ten of the thirteen affected entries held no derived form at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Rebuild and pin the corpus

**Controller-only.** This task touches the real 568MB database. Do not dispatch it to a subagent.

**Files:**
- Test: `tests/test_whole_forms_corpus.py` (create)
- Data: `data/judgements.json` (snapshot), `data/staging_dictionary.db`, `data/maori_dict.db`

- [ ] **Step 1: Snapshot the judgements**

```bash
python scripts/61_export_judgements.py
git diff --stat data/judgements.json
```

Expected: only `last_applied_at` timestamps move, and the summary still reports 18 judgements. If judgement *content* changed, stop and investigate before rebuilding.

- [ ] **Step 2: Back up the database**

```bash
cp data/staging_dictionary.db \
   "data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-prewhole"
```

- [ ] **Step 3: Rebuild paekupu's slice**

```bash
python scripts/50_build_unified.py --source paekupu > /tmp/paekupu_build.log 2>&1
echo "exit=$?"; tail -20 /tmp/paekupu_build.log
```

Expected: `form` in the `[paekupu] cleared … -> ` line is **16 higher** than the previous run's. Exit 0.

- [ ] **Step 4: Rebuild the derived chain**

```bash
python scripts/59_rebuild_derived.py > /tmp/rebuild.log 2>&1
echo "exit=$?"; grep -E "^===|derivation|concept|FAILED|All derived" /tmp/rebuild.log
```

Expected: exit 0, `derivation rows: 11,424` (unchanged — these are `form` rows), `concepts: 91,140`, and `{'concepts': 91140, 'members': 175083, 'kept': 18, 'excluded': 0}`.

Never pipe this script through `head`: it takes no flags, executes on any argument, and a broken pipe can kill it mid-chain.

- [ ] **Step 5: Write the corpus test**

Create `tests/test_whole_forms_corpus.py`:

```python
"""The sixteen whole irregular forms, counted against the built database.

paekupu prints these in full because the stem changes and no suffix
fragment could compose them. Measured on 2026-09-19 after the rebuild:

    paekupu derived forms   1,823 -> 1,839
    corpus derived forms   34,978 -> 34,994
    passive                19,743 -> 19,756
    nominalisation         15,235 -> 15,238

Ten of the thirteen affected entries held no derived form before this.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

# (form, suffix, class) — the complete set, spec §3.
EXPECTED = (
    ("hāua", "-a", "passive"),
    ("kawea atu", "-a", "passive"),
    ("kawea mai", "-a", "passive"),
    ("kūtia", "-tia", "passive"),
    ("motukia", "-kia", "passive"),
    ("motuhanga", "-hanga", "nominalisation"),
    ("tākina", "-kina", "passive"),
    ("tāpiritia-atu", "-tia", "passive"),
    ("tāpiritanga-atu", "-tanga", "nominalisation"),
    ("tīkina atu", "-kina", "passive"),
    ("tīkina ake", "-kina", "passive"),
    ("tukuna atu", "-na", "passive"),
    ("utaina anō", "-ina", "passive"),
    ("wetekina", "-kina", "passive"),
    ("wetekanga", "-kanga", "nominalisation"),
)


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class WholeForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_every_expected_form_is_present_with_its_class(self):
        for form, suffix, form_type in EXPECTED:
            with self.subTest(form=form):
                row = self.con.execute(
                    "SELECT f.form_type, f.note FROM form f "
                    "JOIN entry e ON e.id = f.entry_id "
                    "WHERE e.source_id = 'paekupu' AND f.form = ?",
                    (form,)).fetchone()
                self.assertIsNotNone(row, f"{form!r} was not written")
                self.assertEqual(row[0], form_type)
                self.assertEqual(row[1], f"{suffix} (paekupu, whole)")

    def test_there_are_exactly_sixteen_whole_form_rows(self):
        # Sixteen rows from fifteen distinct spellings: 'kūtia' is written
        # for both of paekupu's two 'kukuti' entries.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form WHERE note LIKE '%, whole)'"), 16)

    def test_the_whole_forms_split_thirteen_passive_three_nominalisation(self):
        got = dict(self.con.execute(
            "SELECT form_type, COUNT(*) FROM form "
            "WHERE note LIKE '%, whole)' GROUP BY 1").fetchall())
        self.assertEqual(got, {"passive": 13, "nominalisation": 3})

    def test_paekupu_gained_exactly_sixteen_derived_forms(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'paekupu' "
            "  AND f.form_type IN ('passive', 'nominalisation')"), 1839)

    def test_no_whole_form_was_composed_onto_its_headword(self):
        # The failure this catches: reusing _add_suffix_forms would store
        # 'hauhāua' and 'kukutikūtia', words no source holds.
        for bad in ("hauhāua", "kukutikūtia", "momotumotuhanga",
                    "wewetewetekina", "takitākina"):
            with self.subTest(form=bad):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM form WHERE form = ?", (bad,)), 0)

    def test_the_affected_entries_still_key_on_their_bare_base(self):
        # A whole form leaking into headword_search would sever the entry
        # from the plain word other sources hold.
        for slug, key in (("hau-3", "hau"), ("tiki-atu", "tiki atu"),
                          ("wewete", "wewete")):
            with self.subTest(slug=slug):
                self.assertEqual(self._one(
                    "SELECT headword_search FROM entry "
                    "WHERE source_id = 'paekupu' AND source_entry_id = ?",
                    (slug,)), key)

    def test_the_corpus_totals_moved_by_sixteen(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form "
            "WHERE form_type IN ('passive', 'nominalisation')"), 34994)

    def test_the_existing_composed_rows_survived(self):
        # Three entries carry a composed form AND a whole one; the new writer
        # must not have displaced the old.
        for form, note in (("hautanga", "-tanga (paekupu)"),
                           ("kukutinga", "-nga (paekupu)")):
            with self.subTest(form=form):
                self.assertGreater(self._one(
                    "SELECT COUNT(*) FROM form WHERE form = ? AND note = ?",
                    form, note), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run the corpus test**

Run: `python -m pytest tests/test_whole_forms_corpus.py -q`
Expected: 8 passed.

If `test_there_are_exactly_sixteen_whole_form_rows` reports 15, the two `kukuti` entries deduped into one — check that `kukuti` and `kukuti-2` minted separate entries.

- [ ] **Step 7: Run the full suite and verify invariants**

Run: `python -m pytest tests/ -q`
Expected: all pass, including the calibration gate at 17/17.

Then confirm nothing else moved:

```bash
python - <<'PY'
import sqlite3, sys
sys.path.insert(0, "scripts")
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH
con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
WANT = {"entry": 153440, "sense": 175101, "relation": 175407,
        "derivation": 11424, "concept": 91140, "form": 35638}
for t, want in WANT.items():
    got = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:<12} {got:>7}  want {want:>7}  {'OK' if got == want else '*** DRIFT ***'}")
j = con.execute("SELECT COUNT(*) FROM concept_member WHERE status='confirmed'").fetchone()[0]
print(f"  judgements   {j:>7}  want      18  {'OK' if j == 18 else '*** DRIFT ***'}")
PY
```

Expected: every line OK.

- [ ] **Step 8: Commit**

```bash
git add tests/test_whole_forms_corpus.py data/judgements.json
git commit -m "test(corpus): pin the sixteen whole forms after the rebuild

paekupu 1,823 -> 1,839 derived forms, 13 passive and 3 nominalisation, and
the corpus 34,978 -> 34,994. The composed-form guard names the five words a
reuse of _add_suffix_forms would have fabricated.

entry, sense, relation, derivation and concept are unchanged, and all 18
confirmed judgements survived the rebuild.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** §1 and §3 are Tasks 1–2 (the reader, its classification, all sixteen forms). §2's replace-versus-append finding is why the wiring in Task 2 Step 4 touches `build_paekupu` alone. §4.1 is Task 1 Step 4, §4.2 is the `StripIsUnchanged` class in Task 1, §4.3 is Task 2 Step 3, §4.4 is the note asserted in Task 2 and Task 3. §5 is Task 3 Steps 6–7. §6 (reduplication) requires no task by design — it is deferred, and the four unattested appends stay refused. §7 is the tests throughout; §8 is Task 3 Steps 1–4.

**Placeholder scan.** No TBD, no "add error handling", no "similar to Task N". Every code step carries the code; every test step carries the assertions.

**Type consistency.** `read_whole_forms` returns `[(form, suffix, form_type)]` in Task 1 and is unpacked as exactly that triple by `_add_whole_forms` in Task 2. `add_form` returns a bool in both. The note string `f"{suffix} ({source}, whole)"` is written in Task 2 and asserted verbatim in Task 3.

**Known limitation, accepted.** The refusal report still lists these sixteen tokens as refused, because `read_tilde_suffixes` already refuses them and `read_whole_forms` deliberately takes no tally to avoid double-counting. The report is a diagnostic rather than data. Reconciling it belongs with the existing `Tally` defect, where `seen` already does not equal written plus refused.
