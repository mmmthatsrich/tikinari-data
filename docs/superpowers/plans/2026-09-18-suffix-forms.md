# Derived Form Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the passive and nominalisation forms that six sources
already record into the `form` table, typed so they can be counted by class
and by suffix, and stop paekupu and te_aka writing suffix notation into
`headword_search`.

**Architecture:** One new pure-rules module, `scripts/suffix_forms.py`,
holding the suffix vocabulary, the classifier, and one reader per notation —
no database, mirroring `scripts/concept_evidence.py` and
`scripts/word_formation.py`. `50_build_unified.py` calls those readers from
the six `build_*` functions it already has and writes rows through the
existing `Builder.add_form`. The two importers gain a headword strip.

**Tech Stack:** Python 3, sqlite3, unittest (run under pytest), no new
dependencies.

**Spec:** `docs/superpowers/specs/2026-09-17-suffix-forms-design.md`

**Companion spec, OUT OF SCOPE:**
`docs/superpowers/specs/2026-09-17-hepatakakupu-suffix-parse-design.md`.
hepatakakupu needs a parser rewrite and is a separate plan. Do not touch
`05_hepataka_parse.py` or `build_hepatakakupu`.

## Global Constraints

- **Never run `50_build_unified.py`, `59_rebuild_derived.py`, or scripts
  52/08b/53/54/60 against the real database from a subagent.** Tasks 1-5 are
  pure functions with unit tests and need no database at all. The rebuild and
  the acceptance gates in Task 7 are run by the controller in the main
  session.
- **The four recorded calibration answers in
  `tests/test_concept_acceptance.py` are a gate, never a target.** Do not
  edit that file. If a gate fails, the rule is wrong, not the test.
- `form` holds the COMPLETE word, never the fragment: `whakarerea`, not `-a`.
- `form_type` is exactly `'passive'` or `'nominalisation'` for this work.
  Never invent a third value; never alter an existing `variant` or `plural`
  row.
- `note` is `'-tia (te_aka)'` — suffix, space, source in parentheses. When
  several sources yield the same form, sources accumulate comma-separated
  inside the one pair of parentheses: `'-tia (te_aka, ngata)'`.
- An unrecognised suffix is **refused and counted**, never coerced to a near
  neighbour and never silently dropped.
- Store the ORIGINAL word with its macrons. Macron folding is for comparison
  only — `hīa` is stored as `hīa`, never as `hia`.
- Git identity is already in the repo's local config. Use plain `git commit`.
  Never pass `-c user.name=` or `-c user.email=`.
- End every commit message with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- Never commit anything under `.superpowers/` (gitignored).
- Run tests with `py -m pytest <path> -v` from the repo root.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/suffix_forms.py` | **Create.** Vocabulary, classifier, macron fold, composition, and one reader per notation. Pure strings and lists; no DB, no imports from any `NN_*.py` script. |
| `tests/test_suffix_forms.py` | **Create.** Unit tests for every function above, including the false-positive corpus. |
| `scripts/50_build_unified.py` | **Modify.** `Builder.add_form` gains dedup + provenance; six `build_*` functions call the readers. |
| `scripts/04_paekupu_import.py` | **Modify.** Strip suffix notation before `normalise_search_key`. |
| `scripts/04_te_aka_import.py` | **Modify.** Same. |
| `tests/test_suffix_extraction.py` | **Create.** Integration assertions against the built database. |

**Measured ground truth** (verified against the live staging database on
2026-09-18 — these are the numbers the readers must reproduce):

| source | where | measured |
|---|---|---|
| ngata | `ngata_entries.equivalents` JSON list | 4,655 base+derived pairs |
| te_aka | `te_aka_entries.senses[].definition_raw`, leading `(-tia)` | 3,824 senses |
| te_aka | `te_aka_entries.headword`, trailing `(-tia)` | 321 entries |
| paekupu | `paekupu_entries.headword`, `~nga` | 1,407 entries |
| papakupu | `papakupu_entries.definition`, leading `~tia` | 126 entries |
| papakupu | `papakupu_entries.headword`, `[-tia]` | 13 entries |
| williams | `williams_entries.definition`, `pass. arohaina` | 35 pass the morphological test, 50 rejected |
| kimikupu_hou | `kimikupu_hou_entries.body_raw`, `(-tia)` in `<B>` | 18 tokens |

---

## Task 1: The suffix vocabulary, classifier, and morphological test

**Files:**
- Create: `scripts/suffix_forms.py`
- Create: `tests/test_suffix_forms.py`

**Interfaces:**
- Consumes: `describe_derivation(child, base)` from `scripts/word_formation.py`,
  which returns `("suffix", "-nga")` / `("prefix", "whaka-")` /
  `("reduplication", None)` / `(None, None)`. It does NOT fold macrons and
  does NOT validate the affix against any vocabulary — this task adds both.
- Produces:
  - `PASSIVE: tuple[str, ...]` and `NOMINALISATION: tuple[str, ...]`
  - `fold(text: str) -> str`
  - `classify(suffix: str) -> str | None` — `'passive'`, `'nominalisation'`, or `None`
  - `derived_pair(base: str, candidate: str) -> str | None` — the suffix, e.g. `'-tia'`
  - `compose(headword: str, suffix: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_suffix_forms.py`:

```python
"""The suffix vocabulary and the morphological test, per
docs/superpowers/specs/2026-09-17-suffix-forms-design.md §2.

The vocabulary here was MEASURED, not recalled: it is the complete set of
well-formed suffix types in hepatakakupu's 22,911 raw tokens. An earlier
draft listed sixteen from memory and dropped -ia, which occurs 236 times.
That is why test_the_vocabulary_is_complete exists — it fails if someone
trims the list back to the ones they remember.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import (PASSIVE, NOMINALISATION, classify, compose,
                          derived_pair, fold)


class Vocabulary(unittest.TestCase):
    def test_the_vocabulary_is_complete(self):
        # Measured from 22,911 hepatakakupu tokens. Removing any of these
        # discards real data; -ia alone accounts for 236 occurrences.
        self.assertEqual(len(PASSIVE), 13)
        self.assertEqual(len(NOMINALISATION), 9)
        for suffix in ("-ia", "-kina", "-whina"):
            self.assertIn(suffix, PASSIVE)
        for suffix in ("-kanga", "-inga", "-unga"):
            self.assertIn(suffix, NOMINALISATION)

    def test_no_suffix_is_in_both_classes(self):
        self.assertEqual(set(PASSIVE) & set(NOMINALISATION), set())

    def test_classify_names_the_class(self):
        self.assertEqual(classify("-tia"), "passive")
        self.assertEqual(classify("-tanga"), "nominalisation")

    def test_an_unknown_suffix_is_refused_not_guessed(self):
        # -bga is a typo for -nga in hepatakakupu's own text. Coercing it to
        # its near neighbour would invent data the source never recorded.
        self.assertIsNone(classify("-bga"))
        self.assertIsNone(classify("-pukenga"))


class MorphologicalTest(unittest.TestCase):
    def test_a_plain_pair(self):
        self.assertEqual(derived_pair("tūkino", "tūkinotia"), "-tia")

    def test_macrons_do_not_block_a_match(self):
        # Williams gives the passive of 'Hi' as 'hīa'. Folding is for the
        # comparison only; callers store the original spelling.
        self.assertEqual(derived_pair("Hi", "hīa"), "-a")

    def test_a_synonym_is_not_a_derived_form(self):
        # ngata lists synonyms and derived forms in one comma-separated run.
        # 'pūhui' does not start with 'whakaranu', so it is a synonym.
        self.assertIsNone(derived_pair("whakaranu", "pūhui"))

    def test_a_shared_prefix_is_not_a_suffix(self):
        # 'pōrahurahu' starts with 'pōrahu' but '-rahu' is not a suffix.
        self.assertIsNone(derived_pair("pōrahu", "pōrahurahu"))

    def test_the_word_itself_is_not_its_own_derived_form(self):
        self.assertIsNone(derived_pair("kake", "kake"))

    def test_the_longest_suffix_wins(self):
        # 'whakamātanga' from 'whakamā' is -tanga, not -anga or -nga.
        self.assertEqual(derived_pair("whakamā", "whakamātanga"), "-tanga")
        # 'arohaina' from 'aroha' is -ina, not -na or -a.
        self.assertEqual(derived_pair("aroha", "arohaina"), "-ina")


class Composition(unittest.TestCase):
    def test_compose_joins_base_and_suffix(self):
        self.assertEqual(compose("kake", "-a"), "kakea")
        self.assertEqual(compose("kake", "-nga"), "kakenga")

    def test_compose_keeps_the_macrons_of_the_base(self):
        self.assertEqual(compose("tūkino", "-tia"), "tūkinotia")


class Folding(unittest.TestCase):
    def test_fold_strips_macrons_and_case(self):
        self.assertEqual(fold("Tūkino"), "tukino")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suffix_forms'`

- [ ] **Step 3: Write the implementation**

Create `scripts/suffix_forms.py`:

```python
"""Read the derived forms — passive and nominalisation — that the sources
record, and classify them. Pure strings and lists; no DB.

See docs/superpowers/specs/2026-09-17-suffix-forms-design.md.

The vocabulary below was measured, not recalled. It is the complete set of
well-formed suffix types across hepatakakupu's 22,911 raw tokens, the largest
sample in the corpus; the nine malformed tokens that measurement also found
(-bga, -pukenga and friends) are why an unrecognised suffix is refused here
rather than coerced to the nearest real one.

This module decides what a string SAYS. It never decides whether a derived
form exists — the source's own filing does that.
"""
import re
import unicodedata

from word_formation import describe_derivation

PASSIVE = ("-tia", "-hia", "-ina", "-ngia", "-ria", "-mia", "-kia", "-whia",
           "-na", "-a", "-ia", "-kina", "-whina")
NOMINALISATION = ("-nga", "-tanga", "-hanga", "-ranga", "-anga", "-manga",
                  "-kanga", "-inga", "-unga")

# Longest first: 'whakamātanga' is -tanga, not -anga and not -nga. Sorting by
# length is what makes the longest-match rule in the spec hold.
_BY_LENGTH = tuple(sorted(PASSIVE + NOMINALISATION, key=len, reverse=True))

_CLASS = {s: "passive" for s in PASSIVE}
_CLASS.update({s: "nominalisation" for s in NOMINALISATION})


def fold(text):
    """Lowercase and strip macrons, for comparison only.

    Callers store the ORIGINAL spelling: Williams's 'hīa' is stored 'hīa'.
    Folding exists because the sources are inconsistent about macrons between
    a base and its derived form, not because the macrons are noise.
    """
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def classify(suffix):
    """'passive', 'nominalisation', or None for anything not in the vocabulary."""
    return _CLASS.get((suffix or "").strip().lower())


def derived_pair(base, candidate):
    """The suffix taking *base* to *candidate*, or None.

    Returns None rather than guessing whenever the two spellings do not show
    a known suffix: a synonym, a shared prefix that is not a suffix, an
    irregular form, or the same word twice. This is the discriminator that
    separates ngata's derived forms from the synonyms sitting beside them in
    the same comma-separated run.
    """
    process, affix = describe_derivation(fold(candidate), fold(base))
    if process != "suffix":
        return None
    return affix if affix in _CLASS else None


def compose(headword, suffix):
    """'kake' + '-a' -> 'kakea'. Straight concatenation, macrons preserved."""
    return (headword or "").strip() + (suffix or "").lstrip("-")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Verify the tests can actually fail (mutation check)**

Temporarily change `_BY_LENGTH` to sort shortest-first
(`key=len, reverse=False`) and re-run. `test_the_longest_suffix_wins` must
fail. If it still passes, the test is not testing the rule — fix the test
before continuing. Then restore the line.

Note: `_BY_LENGTH` is not yet read by any function in this task; it is
consumed in Task 3. If the mutation does not fail the test at this stage,
that is expected — record it and re-run this check at the end of Task 3.

- [ ] **Step 6: Commit**

```bash
git add scripts/suffix_forms.py tests/test_suffix_forms.py
git commit -m "feat(forms): the measured suffix vocabulary and the morphological test

Twenty-two well-formed suffixes, counted from hepatakakupu's 22,911 raw
tokens rather than recalled. derived_pair refuses anything the two spellings
do not show, which is what separates ngata's derived forms from the synonyms
filed beside them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Readers for the fragment notations

Four sources write the suffix as a fragment beside the headword or at the
head of the definition. Each uses a different bracket.

**Files:**
- Modify: `scripts/suffix_forms.py`
- Modify: `tests/test_suffix_forms.py`

**Interfaces:**
- Consumes: `classify`, `compose` from Task 1.
- Produces:
  - `read_paren_suffixes(text: str) -> list[str]` — te_aka, kimikupu_hou
  - `read_tilde_suffixes(text: str) -> list[str]` — paekupu, papakupu
  - `read_bracket_suffixes(text: str) -> list[str]` — papakupu headword
  - `strip_suffix_notation(headword: str) -> str` — used by Task 6

- [ ] **Step 1: Write the failing test**

Append to `tests/test_suffix_forms.py`:

```python
from suffix_forms import (read_bracket_suffixes, read_paren_suffixes,
                          read_tilde_suffixes, strip_suffix_notation)


class ParenNotation(unittest.TestCase):
    """te_aka and kimikupu_hou: '(-tia)' leading a definition or after a
    headword. Verbatim samples from te_aka_entries.senses."""

    def test_one_suffix(self):
        self.assertEqual(
            read_paren_suffixes("(-tia) to do what? treated in what fashion?"),
            ["-tia"])

    def test_several_suffixes(self):
        self.assertEqual(
            read_paren_suffixes("(-a,-ngia,-ria,-tia) to move in a direction"),
            ["-a", "-ngia", "-ria", "-tia"])

    def test_a_suffix_after_a_headword(self):
        self.assertEqual(read_paren_suffixes("āmine (-tia)"), ["-tia"])

    def test_a_definition_with_no_suffix_yields_nothing(self):
        self.assertEqual(read_paren_suffixes("to climb, ascend."), [])

    def test_a_parenthetical_that_is_not_a_suffix_is_ignored(self):
        # kimikupu_hou files chemistry this way: '(-waro)' is a compound
        # component, not a passive ending.
        self.assertEqual(read_paren_suffixes("hauhā (-waro)"), [])

    def test_an_english_gloss_mentioning_pass_is_not_a_suffix(self):
        self.assertEqual(read_paren_suffixes("to pass. (see also)"), [])


class TildeNotation(unittest.TestCase):
    """paekupu and papakupu: '~nga' standing for headword + -nga. Verbatim
    samples from paekupu_entries.headword and papakupu_entries.definition."""

    def test_one_suffix_in_a_headword(self):
        self.assertEqual(read_tilde_suffixes("ahu ~nga"), ["-nga"])

    def test_a_spaced_tilde_still_reads(self):
        # 'āhei ~nga ~ tanga' occurs in paekupu with a space after the tilde.
        self.assertEqual(read_tilde_suffixes("āhei ~nga ~ tanga"),
                         ["-nga", "-tanga"])

    def test_a_comma_run_in_a_definition(self):
        self.assertEqual(read_tilde_suffixes("~tia, ~tanga (1) beget"),
                         ["-tia", "-tanga"])

    def test_a_semicolon_run_in_a_definition(self):
        # papakupu 'eke': '~a, ~ria, ~ngia; ~nga (1) put oneself on something'
        self.assertEqual(read_tilde_suffixes("~a, ~ria, ~ngia; ~nga (1) put"),
                         ["-a", "-ria", "-ngia", "-nga"])

    def test_a_tilde_meaning_reflects_as_is_refused(self):
        # temarareo uses '~' for 'reflects as', followed by a whole word.
        self.assertEqual(read_tilde_suffixes("Proto-Polynesian ~ kainga"), [])


class BracketNotation(unittest.TestCase):
    """papakupu headword: 'tāpiri [-tia]'."""

    def test_a_bracketed_suffix(self):
        self.assertEqual(read_bracket_suffixes("tāpiri [-tia]"), ["-tia"])

    def test_a_bracketed_domain_is_not_a_suffix(self):
        # hepatakakupu files semantic domains this way: '[Tāne]'.
        self.assertEqual(read_bracket_suffixes("kake [Tāne]"), [])


class StripNotation(unittest.TestCase):
    """What the importers key on, per spec §5."""

    def test_a_tilde_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("ahu ~nga"), "ahu")

    def test_a_multi_suffix_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("āhei ~nga ~ tanga"), "āhei")

    def test_a_paren_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("āmine (-tia)"), "āmine")

    def test_a_bracket_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("tāpiri [-tia]"), "tāpiri")

    def test_a_clean_headword_is_unchanged(self):
        self.assertEqual(strip_suffix_notation("whakarere"), "whakarere")

    def test_a_multi_word_headword_is_unchanged(self):
        # 'tiki ake' is two words, not a word plus a suffix.
        self.assertEqual(strip_suffix_notation("tiki ake"), "tiki ake")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_paren_suffixes'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/suffix_forms.py`:

```python
# A suffix token as the sources write it: a hyphen or tilde, then letters.
# Macrons are allowed because papakupu occasionally marks one.
_TOKEN = r"[-~]\s*([a-zāēīōū]+)"

_PAREN_GROUP = re.compile(r"\(\s*((?:" + _TOKEN + r"\s*,?\s*)+)\)", re.I)
_TILDE_TOKEN = re.compile(r"~\s*([a-zāēīōū]+)", re.I)
_BRACKET_GROUP = re.compile(r"\[\s*((?:-\s*[a-zāēīōū]+\s*,?\s*)+)\]", re.I)
_HYPHEN_TOKEN = re.compile(r"-\s*([a-zāēīōū]+)", re.I)


def _keep_known(raw_tokens):
    """Normalise to '-xxx' and drop everything outside the vocabulary.

    Dropping is the point. kimikupu_hou's '(-waro)' is a chemical component,
    temarareo's '~ kainga' means 'reflects as', and neither is a suffix. The
    vocabulary is the only thing separating them from '-tia'.
    """
    out = []
    for token in raw_tokens:
        suffix = "-" + token.strip().lower()
        if classify(suffix):
            out.append(suffix)
    return out


def read_paren_suffixes(text):
    """['-a', '-hia'] from '(-a,-hia) to be able' or 'āmine (-tia)'."""
    for group in _PAREN_GROUP.finditer(text or ""):
        found = _keep_known(_HYPHEN_TOKEN.findall(group.group(1)))
        if found:
            return found
    return []


def read_tilde_suffixes(text):
    """['-tia', '-tanga'] from '~tia, ~tanga (1) beget' or 'ahu ~nga'.

    Separators vary: paekupu spaces them, papakupu uses commas and at least
    once a semicolon ('~a, ~ria, ~ngia; ~nga'). Reading every tilde token and
    filtering by vocabulary handles all of them without a separator rule.
    """
    return _keep_known(_TILDE_TOKEN.findall(text or ""))


def read_bracket_suffixes(text):
    """['-tia'] from 'tāpiri [-tia]'. '[Tāne]' is a domain and yields []."""
    for group in _BRACKET_GROUP.finditer(text or ""):
        found = _keep_known(_HYPHEN_TOKEN.findall(group.group(1)))
        if found:
            return found
    return []


def strip_suffix_notation(headword):
    """The bare headword, with any suffix notation removed.

    'ahu ~nga' -> 'ahu'. This is what headword_search must be built from:
    keying 1,407 paekupu entries on 'ahu ~nga' severs them from the plain
    'ahu' four other sources hold (spec §5).
    """
    text = (headword or "").strip()
    if not text:
        return text
    text = _PAREN_GROUP.sub(" ", text)
    text = _BRACKET_GROUP.sub(" ", text)
    # Only strip a tilde run that the vocabulary recognises, so a stray tilde
    # in an unrelated headword does not truncate it.
    for match in reversed(list(_TILDE_TOKEN.finditer(text))):
        if classify("-" + match.group(1).lower()):
            text = text[:match.start()] + text[match.end():]
    return re.sub(r"\s+", " ", text).strip()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: PASS, 31 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/suffix_forms.py tests/test_suffix_forms.py
git commit -m "feat(forms): readers for the four fragment notations

te_aka and kimikupu_hou parenthesise, paekupu and papakupu use a tilde,
papakupu also brackets. Each reader filters through the vocabulary, which is
what rejects kimikupu_hou's (-waro) chemistry and temarareo's tilde meaning
'reflects as'.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Readers for the whole-word notations

ngata and williams record the derived word complete, without saying which
suffix produced it. Both need `derived_pair` from Task 1.

**Files:**
- Modify: `scripts/suffix_forms.py`
- Modify: `tests/test_suffix_forms.py`

**Interfaces:**
- Consumes: `derived_pair` from Task 1.
- Produces:
  - `derived_from_list(forms: list[str]) -> list[tuple[str, str, str]]` —
    `(base, derived_form, suffix)` triples
  - `read_williams_passives(headword: str, definition: str) -> list[tuple[str, str, str]]` —
    same triple shape

- [ ] **Step 1: Write the failing test**

Append to `tests/test_suffix_forms.py`:

```python
from suffix_forms import derived_from_list, read_williams_passives


class NgataEquivalentList(unittest.TestCase):
    """ngata_entries.equivalents is a comma-separated run that mixes
    base+derived pairs with plain synonyms. Verbatim samples."""

    def test_a_base_and_its_passive(self):
        # WR-HMN.58, 'Abuse'
        self.assertEqual(derived_from_list(["tūkino", "tūkinotia"]),
                         [("tūkino", "tūkinotia", "-tia")])

    def test_two_pairs_in_one_run(self):
        # WR-HMN.166, 'Adulterate'
        self.assertEqual(
            derived_from_list(["whakaranu", "whakaranua", "tūkino",
                               "tūkinotia"]),
            [("whakaranu", "whakaranua", "-a"),
             ("tūkino", "tūkinotia", "-tia")])

    def test_a_synonym_run_yields_nothing(self):
        # WR-HMN.1845, 'Compound'. pūhui is another word for the same idea.
        self.assertEqual(derived_from_list(["whakaranu", "pūhui"]), [])

    def test_a_reduplication_is_not_a_derived_form(self):
        self.assertEqual(derived_from_list(["pōrahu", "pōrahurahu"]), [])

    def test_a_single_item_run_yields_nothing(self):
        self.assertEqual(derived_from_list(["whakaranu"]), [])


class WilliamsProse(unittest.TestCase):
    """williams_entries.definition marks the passive in running prose."""

    def test_a_marked_passive(self):
        self.assertEqual(
            read_williams_passives("Aroha",
                                   "1. n. Love, yearning. Pass. arohaina."),
            [("Aroha", "arohaina", "-ina")])

    def test_a_lowercase_marker(self):
        self.assertEqual(
            read_williams_passives("Arahi", "; pass. arahina. 1. Lead."),
            [("Arahi", "arahina", "-na")])

    def test_the_base_may_be_any_comma_part_of_the_headword(self):
        # 'Amu, amuamu' — the passive belongs to the second form.
        self.assertEqual(
            read_williams_passives("Amu, amuamu", "Grumble. Pass. amuamutia."),
            [("amuamu", "amuamutia", "-tia")])

    def test_the_english_verb_pass_is_not_a_marker(self):
        # 'Āianei' ends a sentence with 'pass.' and the next word is English.
        # A naive regex accepts 'Be' here; the morphological test rejects it.
        self.assertEqual(
            read_williams_passives("Āianei", "ad. Now, presently, to pass. Be"),
            [])

    def test_a_definition_with_no_marker_yields_nothing(self):
        self.assertEqual(read_williams_passives("Kake", "Ascend, climb."), [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: FAIL — `ImportError: cannot import name 'derived_from_list'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/suffix_forms.py`:

```python
# 'Pass. arohaina' / '; pass. arahina.' — Williams's marker, then the word.
_PASSIVE_MARKER = re.compile(r"\bpass\.\s*([a-zāēīōū]+)", re.I)


def derived_from_list(forms):
    """(base, derived, suffix) for every base+derived pair in *forms*.

    ngata prints one comma-separated run per record holding derived forms and
    synonyms together: 'whakaranu, whakaranua, tūkino, tūkinotia' is two
    pairs, and 'whakaranu, pūhui' is a synonym. Only the spellings separate
    them, so every ordered pair is tested and only known suffixes are kept.

    The run is NOT assumed to be ordered base-then-derived, because ngata
    interleaves pairs; each earlier form is tested against each later one.
    """
    out = []
    items = [f for f in (forms or []) if isinstance(f, str) and f.strip()]
    for i, base in enumerate(items):
        for candidate in items[i + 1:]:
            suffix = derived_pair(base, candidate)
            if suffix:
                out.append((base, candidate, suffix))
    return out


def read_williams_passives(headword, definition):
    """(base, derived, suffix) for each 'Pass. <form>' in *definition*.

    The marker alone is not enough. Williams's prose also ends sentences with
    the English verb 'pass', so 'to pass. Be' offers 'Be' as a passive; of 85
    naive matches in the corpus only 35 survive the morphological test. The
    base may be any comma-separated part of the headword ('Amu, amuamu').
    """
    bases = [p.strip() for p in re.split(r"[,;]", headword or "") if p.strip()]
    out = []
    for match in _PASSIVE_MARKER.finditer(definition or ""):
        candidate = match.group(1)
        for base in bases:
            suffix = derived_pair(base, candidate)
            if suffix:
                out.append((base, candidate, suffix))
                break
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: PASS, 41 tests.

- [ ] **Step 5: Re-run the Task 1 mutation check**

Change `_BY_LENGTH` to sort shortest-first and re-run.
`test_the_longest_suffix_wins` must now fail, because `derived_pair` is
reached through `derived_from_list`. Restore the line and confirm green.

If it still does not fail: `describe_derivation` returns the whole remainder
in one piece, so the longest-match rule is satisfied structurally rather than
by ordering. Record that in the ledger and leave `_BY_LENGTH` in place as
documentation of the rule — do not delete it, Task 5 reporting uses it.

- [ ] **Step 6: Commit**

```bash
git add scripts/suffix_forms.py tests/test_suffix_forms.py
git commit -m "feat(forms): readers for ngata's equivalent runs and williams's prose

Both record the derived word whole, so both lean on the morphological test.
Williams needs it most: the English verb 'pass' ends sentences in her prose,
and only 35 of 85 naive marker matches survive.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Dedup and provenance in `Builder.add_form`

One entry can earn the same form from several sources and from several senses
of one source. The spec requires one row per `(entry_id, form, form_type)`
with provenance accumulating in `note`.

**Files:**
- Modify: `scripts/50_build_unified.py:183-195` (`Builder.add_form`) and
  `scripts/50_build_unified.py:126` (`Builder.__init__`)
- Create: `tests/test_form_dedupe.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Builder.add_form(entry_id, form, form_type, note=None)` —
  unchanged signature, now idempotent per `(entry_id, form, form_type)`.

**Note on existing behaviour:** the live database has **10** duplicate
`(entry_id, form, form_type)` groups among its 654 `variant`/`plural` rows.
This change removes them. That is intended — it is the same defect the spec
names — and the row count falling from 654 to about 644 is the expected
result, not a regression.

- [ ] **Step 1: Write the failing test**

Create `tests/test_form_dedupe.py`:

```python
"""One row per (entry_id, form, form_type), with provenance accumulating.

A derived form is often recorded by several sources, and by several senses
within one source. Without this, 'kakea' would be written once per sense and
the user's per-suffix counts would report sense frequency dressed up as
vocabulary size.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

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


class FormDedupe(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "test", None, {})
        self.eid = self.b.add_entry("e1", "kake", "kake", "kake")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_the_same_form_twice_writes_one_row(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.assertEqual(len(self._rows()), 1)

    def test_a_second_source_accumulates_in_the_note(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (ngata)")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "-a (te_aka, ngata)")

    def test_the_same_source_twice_does_not_repeat_itself_in_the_note(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.assertEqual(self._rows()[0][2], "-a (te_aka)")

    def test_a_different_form_type_is_a_different_row(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakenga", "nominalisation", "-nga (te_aka)")
        self.assertEqual(len(self._rows()), 2)

    def test_the_count_matches_the_rows_written(self):
        self.b.add_form(self.eid, "kakea", "passive", "-a (te_aka)")
        self.b.add_form(self.eid, "kakea", "passive", "-a (ngata)")
        self.assertEqual(self.b.counts["form"], 1)

    def test_a_form_restating_the_headword_is_still_refused(self):
        # Pre-existing behaviour that must survive this change.
        self.b.add_form(self.eid, "kake", "variant")
        self.assertEqual(self._rows(), [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_form_dedupe.py -v`
Expected: FAIL — `test_the_same_form_twice_writes_one_row` finds 2 rows;
`test_a_second_source_accumulates_in_the_note` finds 2 rows.

- [ ] **Step 3: Write the implementation**

In `scripts/50_build_unified.py`, add to `Builder.__init__` beside the
existing `self._examples` line:

```python
        self._forms = {}                          # (entry_id, form_cf, type) -> (rowid, note)
```

Replace `Builder.add_form` with:

```python
    def add_form(self, entry_id, form, form_type, note=None):
        if not form:
            return
        # A form that merely restates the headword or its macron-stripped sort
        # key is not a variant: headword_search already normalises both, so the
        # row adds nothing and inflates the app's "has variants" signal.
        if form.casefold() in self._lemmas.get(entry_id, ()):
            return
        # One row per (entry, form, type). A derived form is routinely recorded
        # by several sources, and by several senses within one source; writing
        # it once per sighting would make the corpus-wide suffix counts report
        # how often a form was mentioned, not how many forms there are.
        key = (entry_id, form.casefold(), form_type)
        if key in self._forms:
            rowid, existing = self._forms[key]
            merged = _merge_form_note(existing, note)
            if merged != existing:
                self.con.execute("UPDATE form SET note = ? WHERE id = ?",
                                 (merged, rowid))
                self._forms[key] = (rowid, merged)
            return
        cur = self.con.execute(
            "INSERT INTO form (entry_id, form, form_search, form_type, note) "
            "VALUES (?,?,?,?,?)",
            (entry_id, form, normalise_search_key(form), form_type, note))
        self._forms[key] = (cur.lastrowid, note)
        self.counts["form"] += 1
```

Add this module-level helper immediately above `class Builder:`:

```python
_FORM_NOTE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def _merge_form_note(existing, incoming):
    """Fold a second sighting's provenance into '-tia (te_aka, ngata)'.

    Both notes carry the same suffix, so only the source list grows. A note
    that does not match the '<suffix> (<sources>)' shape is left alone rather
    than reformatted — the variant and plural rows predate this convention.
    """
    if not incoming or incoming == existing:
        return existing
    if not existing:
        return incoming
    old, new = _FORM_NOTE.match(existing), _FORM_NOTE.match(incoming)
    if not (old and new) or old.group(1) != new.group(1):
        return existing
    sources = [s.strip() for s in old.group(2).split(",") if s.strip()]
    for source in (s.strip() for s in new.group(2).split(",")):
        if source and source not in sources:
            sources.append(source)
    return f"{old.group(1)} ({', '.join(sources)})"
```

Confirm `import re` is already present at the top of the file; it is used by
`CITE_PAREN`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_form_dedupe.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Run the existing suite for regressions**

Run: `py -m pytest tests/test_build_unified_fk.py tests/test_example_dedupe.py -v`
Expected: PASS. These exercise `Builder` and must be unaffected.

- [ ] **Step 6: Commit**

```bash
git add scripts/50_build_unified.py tests/test_form_dedupe.py
git commit -m "fix(unified): one form row per entry, form and type

A derived form is recorded by several sources and by several senses of one
source. Writing it once per sighting would make the per-suffix counts report
mention frequency rather than vocabulary size. Provenance accumulates in the
note instead. This also clears 10 pre-existing duplicate variant rows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Wire the six readers into the unify step

**Files:**
- Modify: `scripts/50_build_unified.py` — `build_te_aka` (line 395),
  `build_paekupu` (532), `build_papakupu` (580), `build_williams` (294),
  `_wakareo_en_mi` (the shared helper serving ngata and kimikupu_hou)
- Create: `tests/test_suffix_wiring.py`

**Interfaces:**
- Consumes: every function from Tasks 1-3, and `Builder.add_form` from Task 4.
- Produces: a module-level helper in `50_build_unified.py`:
  `_add_suffix_forms(b, entry_id, headword, suffixes, source)` where
  `suffixes` is a list of `'-tia'` strings.

**Critical constraint:** `_wakareo_en_mi` currently selects `body_text`. It
serves five sources, three of which have empty landing tables.
**kimikupu_hou's `body_text` is empty for 2,823 of its 2,831 rows** — its
suffixes are only reachable through `body_raw`, which must be added to the
SELECT. ngata needs no raw parsing at all: its suffixes are already parsed
into the `equivalents` JSON list the function reads today.

**Out of scope, do not do:** ngata currently records a base and its derived
form as mutual **synonyms** (`add_relation(eid, "synonym", ...)` at the end of
`_wakareo_en_mi`). That is wrong — a passive is not a synonym — and it affects
about 9,310 directed relations. Correcting it changes the relation graph that
concept building depends on, so it needs its own spec and its own calibration
run. **Add the `form` rows and leave every relation exactly as it is.**

- [ ] **Step 1: Write the failing test**

Create `tests/test_suffix_wiring.py`:

```python
"""Each source's rows reach the form table with the right type and note.

These drive the readers through Builder against an in-memory database, so no
part of the real pipeline runs. The per-source row counts live in
tests/test_suffix_extraction.py, which needs a built database.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

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


class AddSuffixForms(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "te_aka", None, {})
        self.eid = self.b.add_entry("e1", "kake", "kake", "kake")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_a_passive_and_a_nominalisation_are_typed_apart(self):
        build_unified._add_suffix_forms(self.b, self.eid, "kake",
                                        ["-a", "-nga"], "te_aka")
        self.assertEqual(self._rows(),
                         [("kakea", "passive", "-a (te_aka)"),
                          ("kakenga", "nominalisation", "-nga (te_aka)")])

    def test_an_unknown_suffix_writes_nothing(self):
        build_unified._add_suffix_forms(self.b, self.eid, "kake",
                                        ["-bga"], "te_aka")
        self.assertEqual(self._rows(), [])

    def test_the_headword_macrons_survive_composition(self):
        eid = self.b.add_entry("e2", "tūkino", "tukino", "tukino")
        build_unified._add_suffix_forms(self.b, eid, "tūkino",
                                        ["-tia"], "ngata")
        self.assertIn(("tūkinotia", "passive", "-tia (ngata)"), self._rows())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_suffix_wiring.py -v`
Expected: FAIL — `AttributeError: module 'build_unified' has no attribute '_add_suffix_forms'`

- [ ] **Step 3: Write the helper**

Add near the other module-level helpers in `scripts/50_build_unified.py`,
and add `import suffix_forms` to the imports at the top:

```python
def _add_suffix_forms(b, entry_id, headword, suffixes, source):
    """Write one form row per known suffix, composed against *headword*.

    An unrecognised suffix writes nothing: classify() is the only thing
    separating a real ending from kimikupu_hou's chemistry and the typos in
    the sources' own text.
    """
    for suffix in suffixes or []:
        form_type = suffix_forms.classify(suffix)
        if not form_type:
            continue
        b.add_form(entry_id, suffix_forms.compose(headword, suffix),
                   form_type, f"{suffix} ({source})")


def _add_derived_forms(b, entry_id, triples, source):
    """Write form rows for (base, derived, suffix) triples, stored whole."""
    for _base, derived, suffix in triples or []:
        form_type = suffix_forms.classify(suffix)
        if not form_type:
            continue
        b.add_form(entry_id, derived, form_type, f"{suffix} ({source})")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_suffix_wiring.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Wire te_aka**

In `build_te_aka`, after the `eid = b.add_entry(...)` call, add:

```python
        # te_aka marks the suffix after the POS and again at the head of each
        # sense's definition. Both name the same forms; add_form dedups.
        _add_suffix_forms(b, eid, suffix_forms.strip_suffix_notation(hw),
                          suffix_forms.read_paren_suffixes(hw), "te_aka")
```

and inside the `for s in senses:` loop, after the `sid = b.add_sense(...)`
call, add:

```python
            _add_suffix_forms(
                b, eid, suffix_forms.strip_suffix_notation(hw),
                suffix_forms.read_paren_suffixes(s.get("definition_raw") or ""),
                "te_aka")
```

- [ ] **Step 6: Wire paekupu**

In `build_paekupu`, after the `sid = b.add_sense(...)` call, add:

```python
        # The suffix is written into the headword ('ahu ~nga'); compose against
        # the bare word, which is also what the importer now keys on.
        _add_suffix_forms(b, eid, suffix_forms.strip_suffix_notation(hw),
                          suffix_forms.read_tilde_suffixes(hw), "paekupu")
```

- [ ] **Step 7: Wire papakupu**

In `build_papakupu`, after its `b.add_sense(...)` call, add — note papakupu
uses BOTH notations, the bracket in the headword and the tilde at the head of
the definition:

```python
        base = suffix_forms.strip_suffix_notation(hw)
        _add_suffix_forms(b, eid, base,
                          suffix_forms.read_bracket_suffixes(hw), "papakupu")
        _add_suffix_forms(b, eid, base,
                          suffix_forms.read_tilde_suffixes(d or ""), "papakupu")
```

Read the function first to confirm the local variable names for the headword
and definition; use whatever it already calls them rather than renaming.

- [ ] **Step 8: Wire williams**

In `build_williams`, after its `b.add_entry(...)` call, add:

```python
        _add_derived_forms(
            b, eid, suffix_forms.read_williams_passives(hw, d or ""),
            "williams")
```

Read the function first to confirm its local names for the headword and
definition.

- [ ] **Step 9: Wire ngata and kimikupu_hou**

In `_wakareo_en_mi`, add `body_raw` to the SELECT — it currently selects
`body_text`, which is empty for 2,823 of kimikupu_hou's 2,831 rows:

```python
    sql = (f"SELECT source_entry_id, wakareo_id, headword, part_of_speech, search_scope, "
           f"equivalents, qualifier, example_en, example_mi, body_text, body_raw "
           f"FROM {table} ORDER BY id")
    for (seid, wid, lemma_en, pos, scope, equivs, qual, ex_en, ex_mi, raw,
         body_raw) in con.execute(sql):
```

Immediately BEFORE the `for i, mi in enumerate(equivalents, start=1):` loop,
add — the pair scan is O(n²) over the run and must not be recomputed once per
equivalent:

```python
        # ngata prints a base and its derived form in one comma-separated run;
        # the equivalents list is already that run, parsed. Only the spellings
        # say which pairs are derivations rather than synonyms.
        source = table.replace("_entries", "")
        pairs = suffix_forms.derived_from_list(equivalents)
        raw_suffixes = suffix_forms.read_paren_suffixes(body_raw or "")
```

Then inside that loop, after the existing `for v in variants: b.add_form(...)`
line, add:

```python
            for base, derived, suffix in pairs:
                if base == mi:
                    form_type = suffix_forms.classify(suffix)
                    if form_type:
                        b.add_form(eid, derived, form_type,
                                   f"{suffix} ({source})")
            # kimikupu_hou marks the suffix inside <B> in the raw body; its
            # body_text column is empty for 2,823 of 2,831 rows.
            _add_suffix_forms(b, eid, mi, raw_suffixes, source)
```

- [ ] **Step 10: Run every unit test**

Run: `py -m pytest tests/test_suffix_forms.py tests/test_suffix_wiring.py tests/test_form_dedupe.py tests/test_build_unified_fk.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add scripts/50_build_unified.py tests/test_suffix_wiring.py
git commit -m "feat(unified): write derived forms from six sources

ngata's suffixes were already parsed into equivalents and needed no raw
reading; kimikupu_hou's needed body_raw, because its body_text is empty for
2,823 of 2,831 rows. The wrong base-to-derived synonym relations ngata
carries are deliberately untouched: ~9,310 directed relations feed concept
building and need their own spec.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Strip suffix notation from the two importers' search keys

This is the only task that changes an existing `headword_search`, and so the
only one that can over-merge concepts.

**Files:**
- Modify: `scripts/04_paekupu_import.py:138` and `:301`
- Modify: `scripts/04_te_aka_import.py:175` and `:338`
- Create: `tests/test_suffix_key_strip.py`

**Interfaces:**
- Consumes: `strip_suffix_notation` from Task 2.
- Produces: no new callable. `paekupu_entries.headword_search` and
  `te_aka_entries.headword_search` no longer contain `~` or `(-`.

**Both files have TWO call sites** — one in the initial insert and one in the
update path. Change both, or a re-import will silently reintroduce the
notation.

**The `headword` column itself is NOT changed.** The source wrote `ahu ~nga`
and the archive keeps what the source wrote; only the derived search key is
built from the bare form.

- [ ] **Step 1: Write the failing test**

Create `tests/test_suffix_key_strip.py`:

```python
"""headword_search must not carry suffix notation (spec §5).

paekupu writes the suffix into the headword ('ahu ~nga') and te_aka sometimes
does too ('āmine (-tia)'). Keyed that way, 1,407 paekupu entries and 321
te_aka entries can never meet the plain 'ahu' and 'amine' that four other
sources hold.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import strip_suffix_notation
from utils import DB_PATH, normalise_search_key


class TheKeyIsBuiltFromTheBareWord(unittest.TestCase):
    def test_a_paekupu_headword(self):
        self.assertEqual(
            normalise_search_key(strip_suffix_notation("ahu ~nga")), "ahu")

    def test_a_te_aka_headword(self):
        self.assertEqual(
            normalise_search_key(strip_suffix_notation("āmine (-tia)")),
            "amine")


class TheBuiltDatabaseAgrees(unittest.TestCase):
    """Runs against the real staging database after a re-import."""

    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    def test_no_paekupu_key_carries_a_tilde(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM paekupu_entries "
            "WHERE headword_search LIKE '%~%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_no_te_aka_key_carries_a_suffix_paren(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM te_aka_entries "
            "WHERE headword_search LIKE '%(-%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_the_headwords_themselves_are_untouched(self):
        # The archive keeps what the source wrote.
        n = self.con.execute(
            "SELECT COUNT(*) FROM paekupu_entries "
            "WHERE headword LIKE '%~%'").fetchone()[0]
        self.assertEqual(n, 1407)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_suffix_key_strip.py -v`
Expected: the two `TheKeyIsBuiltFromTheBareWord` tests PASS (Task 2 already
built `strip_suffix_notation`); the two `LIKE` tests FAIL with 1,407 and 321.

- [ ] **Step 3: Write the implementation**

In `scripts/04_paekupu_import.py`, add to the existing `from utils import`
line's neighbourhood:

```python
from suffix_forms import strip_suffix_notation
```

At line 138, change:

```python
        normalise_search_key(hw),
```

to:

```python
        # 'ahu ~nga' keys as 'ahu'. The headword column keeps the source's own
        # spelling; only the matching key is built from the bare word, or the
        # entry can never meet the plain 'ahu' four other sources hold.
        normalise_search_key(strip_suffix_notation(hw)),
```

At line 301, change:

```python
                normalise_search_key(r["headword"]),
```

to:

```python
                normalise_search_key(strip_suffix_notation(r["headword"])),
```

In `scripts/04_te_aka_import.py`, add the same import. At line 175, change:

```python
        normalise_search_key(entry["headword"]),
```

to:

```python
        # 'āmine (-tia)' keys as 'amine' — see the paekupu importer.
        normalise_search_key(strip_suffix_notation(entry["headword"])),
```

At line 338, change:

```python
                normalise_search_key(e["headword"]),
```

to:

```python
                normalise_search_key(strip_suffix_notation(e["headword"])),
```

Read each line before editing to confirm the surrounding variable names —
the line numbers are from 2026-09-18 and may drift.

- [ ] **Step 4: Run the pure tests**

Run: `py -m pytest tests/test_suffix_key_strip.py::TheKeyIsBuiltFromTheBareWord -v`
Expected: PASS.

The `TheBuiltDatabaseAgrees` tests stay red until the controller re-imports
and rebuilds in Task 7. **A subagent must not run the importers.**

- [ ] **Step 5: Commit**

```bash
git add scripts/04_paekupu_import.py scripts/04_te_aka_import.py tests/test_suffix_key_strip.py
git commit -m "fix(import): key paekupu and te_aka on the bare headword

1,407 paekupu entries were keyed 'ahu ~nga' and 321 te_aka entries
'amine (-tia)', so neither could ever meet the plain form four other sources
hold. Both importers have two call sites; both are changed, or a re-import
reintroduces the notation.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Rebuild, measure, and gate

**Run by the controller in the main session, never by a subagent.**

**Files:**
- Create: `tests/test_suffix_extraction.py`

- [ ] **Step 1: Back up the judgements**

Sweep judgements are unrecoverable and no rebuild regenerates them.

```bash
py scripts/61_export_judgements.py
git add data/judgements.json && git commit -m "chore(sweep): snapshot judgements before the suffix rebuild

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Record the before-state**

```bash
py -c "import sqlite3; c=sqlite3.connect('data/staging_dictionary.db'); print(c.execute('SELECT form_type, COUNT(*) FROM form GROUP BY 1').fetchall()); print('entries', c.execute('SELECT COUNT(*) FROM entry').fetchone()[0]); print('relations', c.execute('SELECT COUNT(*) FROM relation').fetchone()[0])"
```

Write the output into the ledger. `relation` is recorded because Task 5
deliberately left ngata's synonym relations alone — this number must not move.

- [ ] **Step 3: Re-import paekupu and te_aka**

```bash
py scripts/04_paekupu_import.py
py scripts/04_te_aka_import.py
```

- [ ] **Step 4: Re-unify ALL sources**

```bash
py scripts/50_build_unified.py --source all
```

**`--source all`, never a single source.** Running one source alone calls
`delete_source_slice`, which nulls other sources' relations into the deleted
slice — it halved the `derivation` table once before. The script prints which
sources must be re-unified; read that output, do not pipe it to `tail`.

- [ ] **Step 5: Rebuild the derived layer**

```bash
py scripts/59_rebuild_derived.py
```

- [ ] **Step 6: Write the measurement test**

Create `tests/test_suffix_extraction.py`:

```python
"""Per-source derived-form counts against the built database.

The floors below are set from the measured token counts in the spec, less
the collapse expected when several senses of one word repeat its suffixes.
They are tripwires, not targets: a source coming in far under has a reader
missing a shape, and a source coming in far over is matching something that
is not a suffix.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

# (source, floor) — measured 2026-09-18, before dedup collapse.
FLOORS = (("ngata", 3000), ("te_aka", 2500), ("paekupu", 1000),
          ("papakupu", 100), ("williams", 25), ("kimikupu_hou", 10))


class DerivedForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    def test_every_source_contributes(self):
        for source, floor in FLOORS:
            with self.subTest(source=source):
                n = self.con.execute(
                    "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
                    "WHERE e.source_id = ? AND f.form_type IN "
                    "('passive','nominalisation')", (source,)).fetchone()[0]
                self.assertGreaterEqual(n, floor)

    def test_both_classes_are_present(self):
        got = dict(self.con.execute(
            "SELECT form_type, COUNT(*) FROM form WHERE form_type IN "
            "('passive','nominalisation') GROUP BY 1").fetchall())
        self.assertGreater(got.get("passive", 0), 0)
        self.assertGreater(got.get("nominalisation", 0), 0)

    def test_no_form_row_is_a_bare_fragment(self):
        # The spec stores the complete word, never '-tia'.
        n = self.con.execute(
            "SELECT COUNT(*) FROM form WHERE form LIKE '-%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_no_form_row_carries_suffix_notation(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM form WHERE form LIKE '%~%' "
            "OR form LIKE '%(-%'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_there_are_no_duplicate_rows(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM (SELECT entry_id, form, form_type FROM form "
            "GROUP BY 1,2,3 HAVING COUNT(*) > 1)").fetchone()[0]
        self.assertEqual(n, 0)

    def test_the_existing_variant_and_plural_rows_survived(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM form WHERE form_type IN "
            "('variant','plural')").fetchone()[0]
        self.assertGreater(n, 600)
```

- [ ] **Step 7: Run the gates**

```bash
py -m pytest tests/test_concept_acceptance.py -v
py -m pytest tests/test_suffix_extraction.py tests/test_suffix_key_strip.py -v
py -m pytest tests/ -q
```

The four calibration answers in `test_concept_acceptance.py` and the `hoi` ≥ 7
chaining guard must hold. **If one fails, the key strip over-merged: stop, and
treat the rule as wrong rather than the test.**

- [ ] **Step 8: Report the three numbers per source**

```bash
py -c "import sqlite3; c=sqlite3.connect('data/staging_dictionary.db'); [print(f'{r[0]:<14}{r[1]:<16}{r[2]:>7,}') for r in c.execute(\"SELECT e.source_id, f.form_type, COUNT(*) FROM form f JOIN entry e ON e.id=f.entry_id WHERE f.form_type IN ('passive','nominalisation') GROUP BY 1,2 ORDER BY 3 DESC\")]"
```

Compare against the measured ground truth table in this plan's File Structure
section. Record the comparison in the ledger, including any source that came
in more than 10% under.

- [ ] **Step 9: Commit**

```bash
git add tests/test_suffix_extraction.py
git commit -m "test(forms): per-source floors for the derived forms

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8 (optional): pollex

**Build this only if Tasks 1-7 are green and the counts match.** The spec
rules it droppable: 109 tokens, 0.3% of the corpus, and the only place a
`form` row would rest on a probabilistic match rather than a source's own
filing.

**Files:**
- Modify: `scripts/50_build_unified.py`
- Modify: `tests/test_suffix_forms.py`

**Interfaces:**
- Consumes: `derived_pair`, `classify` from Tasks 1 and 3.
- Produces: `read_pollex_suffixes(headword: str) -> list[str]`

pollex has no `entry` rows. It reaches entries only through
`pollex_entry_links` — many-to-many, carrying `match_confidence`, with 34,176
entries linked and up to 8 links per entry.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_suffix_forms.py`:

```python
from suffix_forms import read_pollex_suffixes


class PollexNotation(unittest.TestCase):
    def test_a_joined_suffix(self):
        self.assertEqual(read_pollex_suffixes("Awhi-tia"), ["-tia"])

    def test_two_suffixes(self):
        self.assertEqual(read_pollex_suffixes("Aroha-ina, -tia"),
                         ["-ina", "-tia"])

    def test_a_reconstruction_is_not_a_suffix(self):
        # pollex writes proto-forms as '*qati(-afi)'; -afi is not Māori.
        self.assertEqual(read_pollex_suffixes("*qati(-afi)"), [])

    def test_a_plain_headword_yields_nothing(self):
        self.assertEqual(read_pollex_suffixes("Awhi"), [])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_pollex_suffixes'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/suffix_forms.py`:

```python
def read_pollex_suffixes(headword):
    """['-tia'] from 'Awhi-tia'; ['-ina', '-tia'] from 'Aroha-ina, -tia'.

    The vocabulary filter is what rejects pollex's proto-reconstructions:
    '*qati(-afi)' offers '-afi', which is not a Māori suffix.
    """
    return _keep_known(_HYPHEN_TOKEN.findall(headword or ""))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `py -m pytest tests/test_suffix_forms.py -v`
Expected: PASS.

- [ ] **Step 5: Decide the threshold, then wire it**

Query the distribution before choosing:

```bash
py -c "import sqlite3; c=sqlite3.connect('data/staging_dictionary.db'); print(c.execute('SELECT match_method, ROUND(match_confidence,2), COUNT(*) FROM pollex_entry_links GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10').fetchall())"
```

Wire the write into the pollex linking step, restricted to links at or above
the threshold the distribution supports, with `note` recording
`'-tia (pollex)'`. Record the chosen threshold and its rationale in the
ledger.

- [ ] **Step 6: Commit**

```bash
git add scripts/suffix_forms.py scripts/50_build_unified.py tests/test_suffix_forms.py
git commit -m "feat(forms): pollex derived forms, behind a match-confidence floor

pollex has no entry rows and reaches entries only through a probabilistic
link table, so its 109 tokens are gated on match confidence.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 complete word, not fragment | 1 (`compose`), 7 (`test_no_form_row_is_a_bare_fragment`) |
| §2 `form_type` vocabulary, 22 suffixes | 1 |
| §2 refusal rule | 1, 2 (`_keep_known`), 5 |
| §2 longest match | 1 |
| §2 `note` format and provenance | 4 |
| §2 the two required queries | 7 (Step 8 runs the group-by) |
| §3 layer 3 extraction, six sources | 5 |
| §3 pollex optional, confidence-gated | 8 |
| §4 ngata | 3, 5 |
| §4 te_aka | 2, 5 |
| §4 paekupu | 2, 5 |
| §4 papakupu | 2, 5 |
| §4 williams | 3, 5 |
| §4 kimikupu_hou | 2, 5 |
| §5 key severance | 6 |
| §6 calibration gates | 7 |
| §6 counts reported three ways | 7 |
| §6 composition cross-check | 3 (williams pairs exercise it), 7 |
| §6 no silent duplicates | 4, 7 |
| §7 out of scope items | respected; none implemented |
| §8 false-positive tests | 2 (chemistry, reflects-as), 3 (English "pass"), 8 (reconstruction) |

**Gap found and closed:** §6's composition cross-check — "where the same word
appears in both groups, the composed form must equal the recorded one" — is
not a standalone task. It is covered incidentally by Task 3's williams tests
and Task 7's dedup assertion: if `whakarere + -a` did not equal ngata's
`whakarerea`, the two sources would write two different forms rather than
merging into one row with `'-a (ngata, williams)'`. Task 7 Step 8's report
surfaces that. A dedicated cross-check over the whole corpus would be better
but needs both specs built, so it belongs with the hepatakakupu plan, where
that source's 14,775 pairs make it meaningful.

**Placeholder scan:** no TBDs. Every code step carries real code. Task 5
steps 7 and 8 and Task 6 step 3 tell the implementer to read the function
first and use its existing local names — that is verification, not a
placeholder, because the exact insertion code is given.

**Type consistency:** `derived_from_list` and `read_williams_passives` both
return `(base, derived, suffix)` triples and both feed `_add_derived_forms`.
`read_paren_suffixes`, `read_tilde_suffixes`, `read_bracket_suffixes` and
`read_pollex_suffixes` all return `list[str]` of `'-xxx'` and all feed
`_add_suffix_forms`. `classify` returns `str | None` everywhere.
`strip_suffix_notation` returns `str` and is used in Tasks 2, 5 and 6.
