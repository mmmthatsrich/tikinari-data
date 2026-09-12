# Gloss Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `len(overlap)` gloss-evidence rule with two measured
quantities — Jaccard coverage and the document frequency of the overlap set —
so that terse agreement (`'Spoon'` / `'spoon.'`) stops being tiered as the
corpus's weakest evidence.

**Architecture:** A pure `GlossIndex` built from the corpus's English glosses
answers "how many glosses contain every one of these words". `positive_evidence`
takes that index and grades a pair on a disjunction of coverage and
distinctiveness instead of counting shared words. Both measurements are stored
per evidence row so thresholds can be re-fit later against sweep judgements.
Nothing in the export changes.

**Tech Stack:** Python 3.12, SQLite, `unittest` run under `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-13-gloss-evidence-design.md`

## Global Constraints

- Working dir `C:\AI Development\Dictionaries`, branch `wakareo-extraction`.
- Plain `git commit`. **Never** pass `-c user.name=` or `-c user.email=` — the
  repo's local config holds the right identity.
- End every commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- Never commit anything under `.superpowers/` (gitignored scratch).
- **Never run `scripts/59_rebuild_derived.py` or any of 52/08b/53/54/60 against
  the real database from a subagent** — the chain takes ~5 minutes and has
  killed a subagent on timeout. Task 7 is the controller's job.
- `scripts/concept_evidence.py` holds **no database code**. Its module docstring
  says "Pure strings and dicts; no DB" and that must stay true: `GlossIndex`
  takes an iterable of gloss strings, never a connection.
- The four recorded calibration answers in `tests/test_concept_acceptance.py`
  (`test_hiwi_is_many_words_not_one`, `test_hia_never_joins_hiia`,
  `test_himoemoe_unifies_its_sources`, `test_paekupu_soy_is_not_an_ear_lobe`)
  are hard constraints. **They must not be weakened to accommodate this change.**
  If one fails, the thresholds are wrong, not the test.
- Full suite green after every task: `python -m pytest tests/ -q`
  (~50s; 936 passed, 3 skipped at the start of this plan).
- TDD throughout: write the test, watch it fail, then implement.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/concept_evidence.py` | `GlossIndex`, `gloss_coverage`, the grading rule | 1, 2, 4 |
| `scripts/54_build_concepts.py` | builds the index once, threads it through | 3, 5 |
| `scripts/00_init_db.py` | two new columns on `concept_member_evidence` | 5 |
| `scripts/tune_gloss_thresholds.py` | **new** — grid search + scoreboard | 6 |
| `tests/test_concept_evidence.py` | unit tests for all three | 1, 2, 4 |
| `tests/test_concept_build.py` | 6 `form_concepts` call sites to update | 3 |
| `tests/test_source_field_coverage.py` | floors recalibrated after re-tier | 7 |

---

## Task 1: GlossIndex

**Files:**
- Modify: `scripts/concept_evidence.py` (add after `_content_words`, ~line 110)
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Consumes: `_content_words(text)` — existing, returns a `frozenset` of lowercase
  words longer than 2 characters that are not in `_STOPWORDS`.
- Produces: `GlossIndex(glosses)` where `glosses` is any iterable of strings;
  `.df(words) -> int`; `len(index) -> int` (number of glosses indexed).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_concept_evidence.py`. Import `GlossIndex` on the existing
`from concept_evidence import (...)` line at `tests/test_concept_evidence.py:15`.

```python
class GlossIndexDf(unittest.TestCase):
    """Document frequency of a word SET, not of its individual words."""

    CORPUS = [
        "throw away, reject",
        "Throw away.",
        "throw a spear",
        "cast away from shore",
        "narcissism",
    ]

    def setUp(self):
        self.idx = GlossIndex(self.CORPUS)

    def test_it_counts_the_glosses_it_indexed(self):
        self.assertEqual(5, len(self.idx))

    def test_one_word_is_counted_in_every_gloss_holding_it(self):
        self.assertEqual(3, self.idx.df({"throw"}))
        self.assertEqual(3, self.idx.df({"away"}))

    def test_a_set_is_rarer_than_either_of_its_words(self):
        # The whole point: 'throw' is in 3 and 'away' is in 3, but only 2
        # glosses hold BOTH. A per-word measure cannot see this.
        self.assertEqual(2, self.idx.df({"throw", "away"}))

    def test_a_rare_word_is_rare(self):
        self.assertEqual(1, self.idx.df({"narcissism"}))

    def test_a_word_absent_from_the_corpus_is_in_no_gloss(self):
        self.assertEqual(0, self.idx.df({"supersonic"}))

    def test_a_set_with_an_absent_word_is_in_no_gloss(self):
        self.assertEqual(0, self.idx.df({"throw", "supersonic"}))

    def test_the_empty_set_is_not_evidence_of_anything(self):
        self.assertEqual(0, self.idx.df(set()))

    def test_stopwords_are_not_indexed(self):
        # 'a' is a stopword and 'of' is a stopword; neither may be a key.
        self.assertEqual(0, self.idx.df({"a"}))

    def test_a_none_gloss_is_tolerated(self):
        # sense.gloss_en is nullable; the index is built straight off it.
        idx = GlossIndex(["throw away", None, "throw"])
        self.assertEqual(3, len(idx))
        self.assertEqual(2, idx.df({"throw"}))

    def test_building_the_index_is_cheap_enough_to_do_once_per_run(self):
        # The guard against an accidental rebuild inside the pair loop: 54
        # does ~1.15M pair comparisons, so an index built per pair would be
        # catastrophic rather than merely slow. 2,000 glosses stands in for
        # the corpus's 150,037, which measures at 0.6s.
        import time
        corpus = [f"gloss number {i} of the corpus" for i in range(2000)]
        started = time.time()
        GlossIndex(corpus)
        self.assertLess(time.time() - started, 1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_concept_evidence.py::GlossIndexDf -v`
Expected: FAIL — `ImportError: cannot import name 'GlossIndex'`

- [ ] **Step 3: Implement**

Add to `scripts/concept_evidence.py`, immediately after `_content_words`:

```python
class GlossIndex:
    """How many glosses contain EVERY word of a set.

    Built from an iterable of gloss strings, never from a connection: this
    module holds no DB code (see the module docstring) and 54_build_concepts
    does the query.

    The measure is deliberately the document frequency of the SET, not of its
    words. 'throw' is in 214 glosses and 'away' in 371, but {throw, away} is
    in 15 — a per-word measure would call that pair common when it is
    specific. See the spec, §2.
    """

    def __init__(self, glosses):
        self._postings = {}
        self._n = 0
        for gloss in glosses:
            i = self._n
            self._n += 1
            for word in _content_words(gloss):
                self._postings.setdefault(word, set()).add(i)

    def __len__(self):
        return self._n

    def df(self, words):
        """Glosses containing every word. 0 for an empty or unknown set.

        A word absent from the index is in no gloss, so the answer is 0 — an
        honest reading, and unreachable in production, where the index is
        built from the same sense.gloss_en column the compared glosses came
        from. It is reachable in tests using a small inline corpus.
        """
        try:
            postings = [self._postings[w] for w in words]
        except KeyError:
            return 0
        if not postings:
            return 0
        postings.sort(key=len)          # intersect the smallest first
        hits = postings[0]
        for other in postings[1:]:
            hits = hits & other
            if not hits:
                return 0
        return len(hits)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_concept_evidence.py -q`
Expected: PASS, and every pre-existing test in the file still passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_evidence.py
git commit -m "feat(concepts): GlossIndex counts glosses holding a whole word set

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: gloss_coverage

**Files:**
- Modify: `scripts/concept_evidence.py` (add directly below `GlossIndex`)
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Produces: `gloss_coverage(a_words, b_words) -> float` taking two sets of
  content words (NOT raw gloss strings) and returning Jaccard in `[0.0, 1.0]`.

- [ ] **Step 1: Write the failing tests**

```python
class GlossCoverage(unittest.TestCase):
    """How much of what the two sources said is the same thing."""

    def _cov(self, a, b):
        from concept_evidence import _content_words
        return gloss_coverage(_content_words(a), _content_words(b))

    def test_identical_glosses_are_total_coverage(self):
        # The defect this whole change exists for: a one-word gloss can never
        # share more than one word, so a count calls this the weakest signal.
        self.assertEqual(1.0, self._cov("Spoon", "spoon."))

    def test_punctuation_and_case_do_not_matter(self):
        self.assertEqual(1.0, self._cov("Throw away.", "throw away"))

    def test_a_shared_word_in_two_long_glosses_is_low_coverage(self):
        # 'a' glossed two ways, sharing only 'form' — the noise case.
        cov = self._cov("used to form the passive of a verb",
                        "particle indicating a plural form")
        self.assertLess(cov, 0.3)

    def test_partial_agreement_is_partial(self):
        # {give} shared, {give, forth} union.
        self.assertAlmostEqual(0.5, self._cov("Give", "Give forth."))

    def test_no_shared_words_is_zero(self):
        self.assertEqual(0.0, self._cov("spoon", "battle"))

    def test_an_empty_gloss_is_zero_not_an_error(self):
        self.assertEqual(0.0, self._cov("spoon", ""))
        self.assertEqual(0.0, self._cov("", ""))

    def test_a_gloss_of_only_stopwords_is_zero(self):
        # 'of a the' must never link two senses, at any coverage.
        self.assertEqual(0.0, self._cov("of a the", "of a the"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_concept_evidence.py::GlossCoverage -v`
Expected: FAIL — `NameError: name 'gloss_coverage' is not defined`

- [ ] **Step 3: Implement**

```python
def gloss_coverage(a_words, b_words):
    """Jaccard of two content-word sets: |A∩B| / |A∪B|.

    The axis a word count cannot see. Two sources both glossing a word as
    exactly 'name' agree completely, however common 'name' is elsewhere in
    the corpus; two long glosses that happen to share 'form' do not.

    0.0 when either side has no content words, so a gloss of nothing but
    stopwords links to nothing.
    """
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / len(a_words | b_words)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_concept_evidence.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_evidence.py
git commit -m "feat(concepts): gloss_coverage measures how much two glosses agree

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Thread the index through (pure refactor, no behaviour change)

This task changes signatures ONLY. The grading rule is untouched, so **every
existing test must pass unmodified except for the call-site updates**. That is
the check: if a behavioural test changes here, something is wrong.

**Files:**
- Modify: `scripts/concept_evidence.py:114` — `positive_evidence` signature
- Modify: `scripts/54_build_concepts.py:111` — `form_concepts` signature
- Modify: `scripts/54_build_concepts.py:132` — the call
- Modify: `scripts/54_build_concepts.py:382-401` — `run()` builds the index
- Modify: `tests/test_concept_evidence.py` — **every** `positive_evidence(a, b)`
  call site (12 at the time of writing: lines 78, 86, 92, 101, 107, 115, 129,
  130, 141, 146, 154, 170). Find them with
  `grep -n "positive_evidence(" tests/test_concept_evidence.py` rather than
  trusting the list.
- Modify: `tests/test_concept_build.py` — **every** `form_concepts` call site
  (6 at the time of writing: lines 156, 185, 207, 220, 351, 575). Find them
  with `grep -n "form_concepts(" tests/test_concept_build.py`.

**Line numbers in this plan are approximate** — the first edit to a file shifts
every number below it. Locate edits by content: function name, test name, or a
unique string from the snippet.

**Interfaces:**
- Consumes: `GlossIndex` (Task 1).
- Produces: `positive_evidence(a, b, index)`; `form_concepts(views, index)`.

- [ ] **Step 1: Change the signatures**

In `scripts/concept_evidence.py`, change `def positive_evidence(a, b):` to
`def positive_evidence(a, b, index):` and add to its docstring:

```
    `index` is a GlossIndex over the corpus the two senses came from. It is
    required rather than optional: a default would silently give two
    different grading rules depending on the call site.
```

In `scripts/54_build_concepts.py`, change `def form_concepts(views):` to
`def form_concepts(views, index):`, and line 132 to
`found = positive_evidence(s, e, index)`.

- [ ] **Step 2: Build the index in run()**

Replace `scripts/54_build_concepts.py:384-387` with:

```python
    views = load_senses(con)
    # Once per run, not once per pair: 0.6s over 150,037 glosses against
    # ~1.15M pair comparisons. Built here rather than in concept_evidence so
    # that module stays free of DB code.
    index = GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
    print(f"gloss index: {len(index):,} glosses")
    concepts = []
    for key in sorted(views):
        concepts.extend(form_concepts(views[key], index))
```

Add `GlossIndex` to the import at `scripts/54_build_concepts.py:25`.

- [ ] **Step 3: Update the test call sites**

In `tests/test_concept_evidence.py`, every `positive_evidence(a, b)` becomes
`positive_evidence(a, b, self.idx)`. Add to `class PositiveEvidence` a
`setUp` building an index from the glosses those tests use, so behaviour is
unchanged in this task:

```python
    def setUp(self):
        # Task 3 is a pure refactor: the index is accepted but the grading
        # rule still counts shared words, so its contents cannot yet change
        # any outcome. Task 4 is where it starts to matter.
        self.idx = GlossIndex(["ridge of a hill", "the hill ridge",
                               "ridge of a mountain", "of a the"])
```

In `tests/test_concept_build.py`, each of the 6 call sites gains an index
built from the fixture DB. Add a module-level helper next to `_fixture_db`:

```python
def _fixture_index(con):
    """A GlossIndex over the fixture's own glosses, as 54 builds one."""
    mod = importlib.import_module("concept_evidence")
    return mod.GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
```

and each call becomes e.g. `self.mod.form_concepts(views["hiwi"], _fixture_index(con))`.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS — 936 passed, 3 skipped. **No assertion changed.** If a
behavioural assertion had to change, stop and report it: this task is not
supposed to alter any outcome.

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py scripts/54_build_concepts.py tests/
git commit -m "refactor(concepts): thread a GlossIndex through to positive_evidence

Signature change only; the grading rule still counts shared words, so every
behavioural assertion passes unmodified. Built once per run in 54 rather
than per pair, and out of concept_evidence, which holds no DB code.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: The grading rule

The behavioural change. Everything before this was scaffolding.

**Files:**
- Modify: `scripts/concept_evidence.py:84-107` (the `GLOSS_OVERLAP_MIN` block)
  and `scripts/concept_evidence.py:153-160` (the grading in `positive_evidence`)
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Consumes: `GlossIndex.df`, `gloss_coverage`.
- Produces: evidence dicts gain two keys — `coverage` (float) and
  `distinctiveness` (int) on gloss kinds, both `None` on every other kind.

**Start with these threshold values and do not tune them here.** Task 6 sets
them properly against the full corpus; this task only has to make the rule
work and the unit tests pass.

```python
COVERAGE_FLOOR = 0.5
DISTINCT_CEILING = 20
```

- [ ] **Step 1: Write the failing tests**

Replace `test_two_shared_words_are_ordinary_evidence` at
`tests/test_concept_evidence.py:121-136`. Its comment is worth keeping — it
correctly insists on testing both sides of the boundary in one test — but the
boundary it pins is the count rule this task removes.

```python
class GlossGrading(unittest.TestCase):
    """Both sides of the boundary, on both axes.

    Asserting only that a strong pair yields 'gloss_overlap' would pass
    against a build with no weak kind at all, which pins nothing. What has to
    hold is that the two cases DIFFER — in kind, in weight, and in the
    confidence a membership earns.
    """

    def _pair(self, ga, gb, corpus):
        idx = GlossIndex(corpus)
        a = _sense(source_id="te_aka", gloss_en=ga)
        b = _sense(source_id="papakupu", gloss_en=gb)
        return positive_evidence(a, b, idx)

    def test_identical_terse_glosses_are_ordinary_evidence(self):
        # The defect: one shared word, but it is the WHOLE of both glosses.
        # 'spoon' is deliberately common in this corpus (df 21 > ceiling), so
        # only coverage can rescue it.
        corpus = ["Spoon", "spoon."] + ["a spoon of sorts"] * 19
        got = self._pair("Spoon", "spoon.", corpus)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])
        self.assertEqual("probable", confidence_for(got, []))

    def test_a_rare_shared_word_is_ordinary_evidence(self):
        # The other axis: coverage is LOW (one word out of six), but the
        # shared word is decisive. Only distinctiveness can rescue this.
        long_gloss = "narcissism, vanity, pride, conceit, self-regard"
        corpus = [long_gloss, "narcissism", "narcissism of a sort"]
        got = self._pair(long_gloss, "narcissism", corpus)
        self.assertEqual(["gloss_overlap"], [e["kind"] for e in got])
        self.assertLess(got[0]["coverage"], 0.5)      # coverage did not save it
        self.assertLessEqual(got[0]["distinctiveness"], 20)

    def test_one_common_word_in_two_long_glosses_is_weak(self):
        # Weak on BOTH axes: the 'a'/'form' noise case.
        corpus = (["used to form the passive of a verb",
                   "particle indicating a plural form"]
                  + ["some other form of thing"] * 40)
        got = self._pair("used to form the passive of a verb",
                         "particle indicating a plural form", corpus)
        self.assertEqual(["gloss_overlap_weak"], [e["kind"] for e in got])
        self.assertEqual("uncertain", confidence_for(got, []))

    def test_the_weak_kind_weighs_less_than_the_ordinary_one(self):
        strong = self._pair("Spoon", "spoon.", ["Spoon", "spoon."])
        weak = self._pair("used to form the passive of a verb",
                          "particle indicating a plural form",
                          ["form"] * 40)
        self.assertGreater(strong[0]["weight"], weak[0]["weight"])

    def test_no_shared_words_is_no_evidence_at_all(self):
        self.assertEqual([], self._pair("spoon", "battle", ["spoon", "battle"]))

    def test_both_measurements_are_carried_on_the_evidence(self):
        # Task 5 stores these; a later re-tune reads them back. If they are
        # not carried here, re-fitting thresholds means recomputing the corpus.
        got = self._pair("Spoon", "spoon.", ["Spoon", "spoon."])[0]
        self.assertEqual(1.0, got["coverage"])
        self.assertEqual(2, got["distinctiveness"])

    def test_a_non_gloss_kind_carries_no_measurements(self):
        a = _sense(source_id="te_matatiki", entry_id=10, cites=frozenset({99}))
        b = _sense(source_id="williams", entry_id=99)
        got = positive_evidence(a, b, GlossIndex([]))[0]
        self.assertEqual("cites_source", got["kind"])
        self.assertIsNone(got["coverage"])
        self.assertIsNone(got["distinctiveness"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_concept_evidence.py::GlossGrading -v`
Expected: FAIL — `test_identical_terse_glosses_are_ordinary_evidence` gets
`['gloss_overlap_weak']` (the count rule sees one shared word), and
`test_both_measurements_are_carried_on_the_evidence` raises `KeyError:
'coverage'`.

- [ ] **Step 3: Replace the threshold constants**

Delete `GLOSS_OVERLAP_MIN = 1` at `scripts/concept_evidence.py:107`. Keep the
long comment above it — it is evidence, not commentary — but retitle it as
superseded and add the new constants:

```python
# SUPERSEDED by COVERAGE_FLOOR / DISTINCT_CEILING below. Kept because its
# findings are why this design exists: the himoemoe and huripari cases
# recorded here are the ones a single count threshold cannot hold together.
#
# [the existing comment body, unchanged]

# Set by grid search against the recorded calibration answers — see
# docs/superpowers/specs/2026-09-13-gloss-evidence-design.md §5 and
# scripts/tune_gloss_thresholds.py. A pair earns ordinary gloss_overlap when
# it is strong on EITHER axis; weak on both makes it gloss_overlap_weak.
COVERAGE_FLOOR = 0.5
DISTINCT_CEILING = 20
```

- [ ] **Step 4: Replace the grading**

`scripts/concept_evidence.py:153-160` becomes:

```python
    a_words, b_words = _content_words(a["gloss_en"]), _content_words(b["gloss_en"])
    overlap = a_words & b_words
    if overlap:
        coverage = gloss_coverage(a_words, b_words)
        distinct = index.df(overlap)
        shown = ", ".join(sorted(overlap)[:4])
        if coverage >= COVERAGE_FLOOR or distinct <= DISTINCT_CEILING:
            found.append(("gloss_overlap", f"glosses share {shown}",
                          coverage, distinct))
        else:
            # Weak on both axes: a common word incidental to two long
            # glosses. Its own kind so a reviewer sees WHY it is weak.
            found.append(("gloss_overlap_weak",
                          f"glosses share only {shown}", coverage, distinct))

    return [{"kind": k, "detail": d, "weight": EVIDENCE_WEIGHT[k],
             "coverage": c, "distinctiveness": n}
            for k, d, c, n in found]
```

Every earlier `found.append((kind, detail))` in the function — `cites_source`,
`shared_example`, `attributed_quote` — becomes a 4-tuple with `None, None`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_concept_evidence.py -q` then
`python -m pytest tests/ -q`.
Expected: PASS. `tests/test_concept_acceptance.py` runs against the real
database, which has not been rebuilt yet, so it still reflects the old rule —
that is expected and Task 7 is where it is re-checked.

- [ ] **Step 6: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_evidence.py
git commit -m "feat(concepts): grade gloss evidence on coverage and distinctiveness

A count cannot see how much of each gloss the overlap represents, so a
one-word gloss could never score above the floor however exactly two sources
agreed: 'Spoon'/'spoon.' was tiered as the corpus's weakest evidence.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Store both measurements

**Files:**
- Modify: `scripts/00_init_db.py:1093-1099`
- Modify: `scripts/54_build_concepts.py:268-272` (the evidence INSERT)
- Test: `tests/test_concept_build.py`

**Interfaces:**
- Consumes: evidence dicts carrying `coverage` and `distinctiveness` (Task 4).

- [ ] **Step 1: Write the failing test**

Add to `class Persist` in `tests/test_concept_build.py`:

```python
    def test_it_stores_both_gloss_measurements(self):
        # Stored so a later re-tune is a re-tier, not a recomputation of the
        # whole corpus. See the spec, §6.
        con = _fixture_db()
        views = self.mod.load_senses(con)
        idx = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], idx))
        self.mod.persist(con, allc)
        rows = con.execute(
            "SELECT coverage, distinctiveness FROM concept_member_evidence "
            " WHERE kind LIKE 'gloss_overlap%'").fetchall()
        self.assertTrue(rows, "no gloss evidence in the fixture")
        for coverage, distinct in rows:
            self.assertIsNotNone(coverage)
            self.assertIsNotNone(distinct)
            self.assertGreaterEqual(coverage, 0.0)
            self.assertLessEqual(coverage, 1.0)

    def test_a_non_gloss_kind_stores_no_measurements(self):
        con = _fixture_db()
        views = self.mod.load_senses(con)
        idx = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], idx))
        self.mod.persist(con, allc)
        rows = con.execute(
            "SELECT coverage, distinctiveness FROM concept_member_evidence "
            " WHERE kind NOT LIKE 'gloss_overlap%'").fetchall()
        for coverage, distinct in rows:
            self.assertIsNone(coverage)
            self.assertIsNone(distinct)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_concept_build.py::Persist -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: coverage`

- [ ] **Step 3: Add the columns**

In `scripts/00_init_db.py:1093`, the table becomes:

```sql
        CREATE TABLE IF NOT EXISTS concept_member_evidence (
            id                INTEGER PRIMARY KEY,
            member_id         INTEGER NOT NULL REFERENCES concept_member(id),
            kind              TEXT NOT NULL,
            detail            TEXT NOT NULL,
            weight            REAL NOT NULL,
            -- Measured, not derived: stored so re-fitting COVERAGE_FLOOR and
            -- DISTINCT_CEILING against sweep judgements is a re-tier rather
            -- than a recomputation. NULL on non-gloss kinds.
            coverage          REAL,
            distinctiveness   INTEGER
        );
```

`CREATE TABLE IF NOT EXISTS` will not alter an existing table, so the existing
database needs the columns added explicitly. Run once, from the repo root:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/staging_dictionary.db'); \
[c.execute(s) for s in ('ALTER TABLE concept_member_evidence ADD COLUMN coverage REAL', \
 'ALTER TABLE concept_member_evidence ADD COLUMN distinctiveness INTEGER')]; c.commit()"
```

- [ ] **Step 4: Write them in persist()**

`scripts/54_build_concepts.py:268-272` becomes:

```python
            for e in m["evidence"]:
                con.execute(
                    "INSERT INTO concept_member_evidence (member_id, kind, "
                    " detail, weight, coverage, distinctiveness) "
                    " VALUES (?,?,?,?,?,?)",
                    (mid, e["kind"], e["detail"], e["weight"],
                     e["coverage"], e["distinctiveness"]))
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/00_init_db.py scripts/54_build_concepts.py tests/test_concept_build.py
git commit -m "feat(concepts): store coverage and distinctiveness per evidence row

Re-fitting the thresholds against accumulated sweep judgements is then a
re-tier and a rebuild of 54, not a recomputation of the corpus.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Grid search and set the thresholds

**Files:**
- Create: `scripts/tune_gloss_thresholds.py`
- Modify: `scripts/concept_evidence.py` — the two constants, with reasoning
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Consumes: `load_senses`, `form_concepts` from `54_build_concepts`;
  `GlossIndex`, `COVERAGE_FLOOR`, `DISTINCT_CEILING`.

The script runs `form_concepts` **in memory without persisting**, so a grid
point costs seconds. It never writes to any database.

- [ ] **Step 1: Write the failing test**

The script's scoreboard is the thing worth testing — the hard constraints must
be evaluated correctly, or the grid picks a point that breaks them.

```python
class ScoreboardConstraints(unittest.TestCase):
    """The hard constraints of the spec, §5, as the tuner evaluates them."""

    def test_a_point_that_merges_hiwi_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        # hiwi is eight words plus two loans; anything under 6 concepts on
        # that key means the thresholds over-merge.
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 3, "hia_joined": False,
             "himoemoe_sources": 6, "hoi_soy_sources": 1}))

    def test_a_point_that_joins_hia_and_hiia_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": True,
             "himoemoe_sources": 6, "hoi_soy_sources": 1}))

    def test_a_point_that_fragments_himoemoe_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": False,
             "himoemoe_sources": 2, "hoi_soy_sources": 1}))

    def test_a_point_that_merges_paekupu_soy_is_rejected(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertFalse(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": False,
             "himoemoe_sources": 6, "hoi_soy_sources": 3}))

    def test_a_point_satisfying_all_four_is_accepted(self):
        tune = importlib.import_module("tune_gloss_thresholds")
        self.assertTrue(tune.constraints_hold(
            {"hiwi_concepts": 8, "hia_joined": False,
             "himoemoe_sources": 6, "hoi_soy_sources": 1}))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_concept_evidence.py::ScoreboardConstraints -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tune_gloss_thresholds'`

- [ ] **Step 3: Write the script**

`scripts/tune_gloss_thresholds.py`:

```python
"""Grid-search COVERAGE_FLOOR and DISTINCT_CEILING against recorded answers.

Read-only. Runs form_concepts in memory and persists nothing, so a grid point
costs seconds rather than a full build of 54.

The four hard constraints are the recorded calibration answers in
tests/test_concept_acceptance.py. A point failing any one is rejected outright,
however well it scores elsewhere: those answers were reasoned one cluster at a
time and they outrank any aggregate.
"""
import importlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

import concept_evidence
from utils import DB_PATH

build = importlib.import_module("54_build_concepts")

COVERAGES = (0.3, 0.4, 0.5, 0.6, 0.7)
CEILINGS = (5, 10, 20, 40, 80)


def constraints_hold(score):
    """The four recorded answers. All must hold."""
    return (score["hiwi_concepts"] >= 6
            and not score["hia_joined"]
            and score["himoemoe_sources"] >= 4
            and score["hoi_soy_sources"] == 1)


def _concepts_for(views, index, keys):
    out = {}
    for key in keys:
        if key in views:
            out[key] = build.form_concepts(views[key], index)
    return out


def score_point(views, index):
    """The scoreboard for the thresholds currently set on concept_evidence."""
    got = _concepts_for(views, index, ("hiwi", "hia", "himoemoe", "hoi"))

    hiwi = len(got.get("hiwi", []))

    hia_joined = False
    for c in got.get("hia", []):
        hws = {m["view"]["headword"].lower() for m in c["members"]}
        if {"hia", "hīa"} <= hws:
            hia_joined = True

    himoemoe = max((len({m["view"]["source_id"] for m in c["members"]})
                    for c in got.get("himoemoe", [])), default=0)

    soy = 1
    for c in got.get("hoi", []):
        if any(m["view"]["source_id"] == "paekupu"
               and m["view"]["source_entry_id"] == "hoi" for m in c["members"]):
            soy = len({m["view"]["source_id"] for m in c["members"]})

    return {"hiwi_concepts": hiwi, "hia_joined": hia_joined,
            "himoemoe_sources": himoemoe, "hoi_soy_sources": soy}


def corpus_effects(views, index):
    """Total concepts and the tier split, so a point's cost is visible."""
    tiers = {"certain": 0, "probable": 0, "uncertain": 0}
    total = 0
    for key in views:
        for c in build.form_concepts(views[key], index):
            total += 1
            tiers[c["confidence"]] += 1
    return total, tiers


def main():
    con = sqlite3.connect(DB_PATH)
    views = build.load_senses(con)
    index = concept_evidence.GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
    print(f"gloss index: {len(index):,} glosses\n")

    print(f"{'cov':>5} {'ceil':>5} {'hiwi':>5} {'hia':>5} {'himo':>5} "
          f"{'soy':>4} {'ok':>3} {'concepts':>9} {'ships':>8}")
    for cov in COVERAGES:
        for ceil in CEILINGS:
            concept_evidence.COVERAGE_FLOOR = cov
            concept_evidence.DISTINCT_CEILING = ceil
            s = score_point(views, index)
            ok = constraints_hold(s)
            total, tiers = corpus_effects(views, index)
            ships = tiers["certain"] + tiers["probable"]
            print(f"{cov:>5} {ceil:>5} {s['hiwi_concepts']:>5} "
                  f"{str(s['hia_joined']):>5} {s['himoemoe_sources']:>5} "
                  f"{s['hoi_soy_sources']:>4} {'OK' if ok else 'no':>3} "
                  f"{total:>9,} {ships:>8,}")
    con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_concept_evidence.py -q`
Expected: PASS.

- [ ] **Step 5: Run the grid and record the result**

Run: `python scripts/tune_gloss_thresholds.py`

Choose the point that satisfies all four hard constraints with the largest
`ships` figure. Ties break toward the **tighter** pair (lower coverage floor is
looser; higher ceiling is looser — prefer the more conservative of two points
that ship the same number).

Write the chosen values into `scripts/concept_evidence.py`, replacing the
provisional `0.5 / 20`, with a comment recording: the grid that was run, the
point chosen, its scoreboard line, and the runner-up with why it lost. Follow
the style of the `GLOSS_OVERLAP_MIN` comment it supersedes — that comment is
the model for how a tuned parameter is documented in this repo.

Save the full grid output to `docs/superpowers/specs/2026-09-13-gloss-threshold-grid.txt`
and reference it from the comment.

- [ ] **Step 6: Commit**

```bash
git add scripts/tune_gloss_thresholds.py scripts/concept_evidence.py \
        tests/test_concept_evidence.py docs/superpowers/specs/2026-09-13-gloss-threshold-grid.txt
git commit -m "feat(concepts): set the gloss thresholds by grid search

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Rebuild, recalibrate, verify

**Controller task — do not dispatch this to a subagent.** It runs the full
derived chain against the real database (~5 minutes), which has killed a
subagent on timeout.

**Files:**
- Modify: `tests/test_source_field_coverage.py:133-140` (the `FLOORS` table)

- [ ] **Step 1: Record the before state**

```bash
python -c "import sqlite3; c=sqlite3.connect('data/staging_dictionary.db'); \
print(c.execute('SELECT confidence, COUNT(*) FROM concept GROUP BY 1').fetchall()); \
print(c.execute('SELECT COUNT(*) FROM concept').fetchone())"
```

- [ ] **Step 2: Rebuild the derived chain**

Run: `python scripts/59_rebuild_derived.py`
Expected: the full chain 52 → 08b → 53 → 54 → 60, ending "All derived tables
rebuilt." It stops at the first failure.

- [ ] **Step 3: Check the hard constraints against the rebuilt database**

Run: `python -m pytest tests/test_concept_acceptance.py -v`
Expected: PASS — all four recorded answers hold. **If one fails, the thresholds
chosen in Task 6 are wrong. Do not weaken the test.** Go back to the grid,
pick the next-best point that satisfies the constraints, and rebuild.

- [ ] **Step 4: Recalibrate the derived-table floors**

`tests/test_source_field_coverage.py:133-140` carries floors with the current
counts in trailing comments. The `concept` and `concept_member` floors are set
well below their values so ordinary drift is quiet. Update the trailing
comments to the new counts, and raise a floor only if the new count is more
than double it. Record in the test's docstring that the counts moved because
the gloss-evidence rule changed, with the commit that did it.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_source_field_coverage.py
git commit -m "test(concepts): recalibrate the derived floors after the re-tier

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.** §2 the measure → Tasks 1, 2, 4. §3 validation → the grid in
Task 6 and the acceptance run in Task 7. §4 `concept_evidence.py` changes →
Tasks 1–4; `54_build_concepts.py` → Task 3; schema → Task 5;
`60_export_app_db.py` unchanged → no task, correctly. §5 threshold setting →
Task 6. §6 re-tuning → Task 5 stores the measurements, Task 6 builds the
script. §7 known failure modes → no task; they are recorded limits, not work.
§8 testing → the tests in each task, plus Task 7 step 3 and the cost ceiling.

**Gap found and closed inline:** §8 asks for an index-build cost ceiling so an
accidental rebuild inside the pair loop is loud rather than merely slow. It was
in no task; `test_building_the_index_is_cheap_enough_to_do_once_per_run` is now
the last test of Task 1, Step 1.

**Placeholder scan:** clean — every code step carries real code, and the one
genuinely unknown pair of values (the thresholds) is given provisionally in
Task 4 and set by a defined procedure in Task 6.

**Type consistency:** `GlossIndex(glosses)` / `.df(words) -> int` / `len()`
used identically in Tasks 1, 3, 4, 6. `gloss_coverage(a_words, b_words)` takes
sets, not strings, in Tasks 2 and 4. `positive_evidence(a, b, index)` and
`form_concepts(views, index)` consistent from Task 3 onward. Evidence dict keys
`coverage` / `distinctiveness` consistent in Tasks 4, 5, 6.
