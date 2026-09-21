# Reduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harvest the 18 reduplications papakupu states, and correct 61 derivation rows whose affix a vowel-collapsing normalisation got wrong.

**Architecture:** A new pure module parses papakupu's prose reduplication statements and filters them against a deliberately loose spelling test. A second pass in `build_papakupu` turns the surviving pairs into `derived_from` relations marked `note='reduplication'`. `53_build_word_origin` learns two things: to honour that marker instead of re-deriving the process, and to try a strict macron-only fold before falling back to the collapsing search key.

**Tech Stack:** Python 3.12, SQLite, `unittest` via `pytest`, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-21-reduplication-design.md`

## Global Constraints

- **Infer nothing.** Every row rests on a papakupu sentence. The spelling test is a filter that rejects statements about other words; it never generates a pair.
- **Never collapse doubled vowels in the reduplication filter.** `normalise_search_key` folds `ekeeke` to `ekeke`, destroying the seam. The filter folds macrons only.
- The filter is **deliberately loose** (`base in child`). A tighter rule rejected eight genuine source statements while this was being designed. Do not tighten it.
- `process` for these rows is **asserted from the source**, never read off the spellings. `describe_derivation('ekeeke','eke')` returns `('suffix','-ke')`, which is wrong.
- In `53_build_word_origin`, the normalisation is **strict first, collapsing key as fallback** — never one or the other alone. Williams writes a long vowel as a doubled letter (`Paaha` is `pāha`), so removing the collapse breaks three rows.
- Only the `derived_from` path uses `describe_derivation`. The 5,271 `compound` rows set their process directly and **must not change**.
- Never run `50_build_unified.py`, `59_rebuild_derived.py` or steps 52/08b/53/54/60 against the real database **from a subagent**. Task 4 is the controller's own work.
- `59_rebuild_derived.py` takes no flags and executes on any argument, including `--help`. Never pipe it through `head`; redirect to a file.
- Git identity is already in the repo's local config. Use plain `git commit`, never `-c user.name=`.
- End every commit message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `scripts/reduplication.py` | New. Parse papakupu's statements; the containment filter. Pure strings, no DB. | 1 |
| `tests/test_reduplication.py` | New. Both shapes, the three traps, the five reduplication shapes. | 1 |
| `scripts/53_build_word_origin.py` | Strict-then-fallback normalisation; honour `note='reduplication'`; papakupu warrant. | 2 |
| `tests/test_derivation_normalisation.py` | New. The affix corrections and the fallback. | 2 |
| `scripts/50_build_unified.py` | Second pass in `build_papakupu` emitting `derived_from`. | 3 |
| `tests/test_papakupu_reduplication_wiring.py` | New. Drives `build_papakupu` against an in-memory DB. | 3 |
| `tests/test_reduplication_corpus.py` | New. Counts against the rebuilt database. | 4 |

---

### Task 1: The parser

**Files:**
- Create: `scripts/reduplication.py`
- Test: `tests/test_reduplication.py`

**Interfaces:**
- Produces, all consumed by Task 3:
  - `fold(text) -> str` — lowercase, macrons stripped, doubled vowels **kept**
  - `is_plausible(child, base) -> bool`
  - `read_reduplications(headword, definition) -> [(child, base, sense_no|None), ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reduplication.py`:

```python
"""papakupu states its reduplications in prose; we parse, never infer.

Two shapes. Forward, where the entry IS the reduplication and names its
base — 'ekeeke: (Reduplicated form of eke [2])'. Inverse, where the entry is
the base and names its reduplication — 'hoko: In the reduplicated forms
hohoko and hokohoko...'.

The spelling test is a FILTER on those statements, never a generator: the
source has already asserted the derivation, and the test only rejects a
sentence that turns out to be about a different word.

See docs/superpowers/specs/2026-09-21-reduplication-design.md.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from reduplication import fold, is_plausible, read_reduplications


class Fold(unittest.TestCase):
    def test_macrons_are_stripped(self):
        self.assertEqual(fold("kōrero"), "korero")

    def test_a_doubled_vowel_survives(self):
        # The whole point. normalise_search_key folds 'ekeeke' to 'ekeke',
        # which destroys the seam that makes the reduplication visible.
        self.assertEqual(fold("ekeeke"), "ekeeke")

    def test_empty_input_is_tolerated(self):
        self.assertEqual(fold(None), "")


class Filter(unittest.TestCase):
    def test_a_full_reduplication_passes(self):
        self.assertTrue(is_plausible("ekeeke", "eke"))

    def test_an_initial_syllable_reduplication_passes(self):
        self.assertTrue(is_plausible("nunui", "nui"))

    def test_a_final_foot_reduplication_passes(self):
        self.assertTrue(is_plausible("kōrerorero", "kōrero"))

    def test_a_reduplication_inside_a_compound_passes(self):
        self.assertTrue(is_plausible("pāwerawera", "pāwera"))

    def test_a_two_mora_reduplication_passes(self):
        self.assertTrue(is_plausible("ariariā", "ariā"))

    def test_a_macron_mismatch_still_passes(self):
        # papakupu writes 'pūhakehake' against the base 'puhake'.
        self.assertTrue(is_plausible("pūhakehake", "puhake"))

    def test_an_unrelated_word_is_rejected(self):
        # takapau's entry discusses momoe, a Proto-Polynesian cognate.
        self.assertFalse(is_plausible("momoe", "takapau"))

    def test_a_source_slip_is_rejected(self):
        # puri's entry names pupuhi, which is really from puhi.
        self.assertFalse(is_plausible("pupuhi", "puri"))

    def test_prose_caught_by_the_regex_is_rejected(self):
        for word in ("includes", "embraces", "can", "listed"):
            with self.subTest(word=word):
                self.assertFalse(is_plausible(word, "take"))

    def test_a_word_is_not_a_reduplication_of_itself(self):
        self.assertFalse(is_plausible("eke", "eke"))


class ReadForward(unittest.TestCase):
    def test_a_parenthetical_statement_with_a_sense_number(self):
        self.assertEqual(
            read_reduplications(
                "ekeeke", "sexual movement (Reduplicated form of eke [2])"),
            [("ekeeke", "eke", 2)])

    def test_a_statement_without_a_sense_number(self):
        self.assertEqual(
            read_reduplications(
                "ariariā", "resemble, look like. (Reduplicated form of ariā)."),
            [("ariariā", "ariā", None)])

    def test_a_trailing_full_stop_is_not_part_of_the_base(self):
        self.assertEqual(
            read_reduplications(
                "kōrerorero", "chat (Reduplicated form of kōrero.)"),
            [("kōrerorero", "kōrero", None)])


class ReadInverse(unittest.TestCase):
    def test_two_reduplications_named_with_and(self):
        self.assertEqual(
            read_reduplications(
                "hoko",
                "goods for sale. In the reduplicated forms hohoko and "
                "hokohoko, the focus is on the process."),
            [("hohoko", "hoko", None), ("hokohoko", "hoko", None)])

    def test_one_reduplication_named_in_prose(self):
        self.assertEqual(
            read_reduplications(
                "roa", "long. The reduplicated form roroa is often used."),
            [("roroa", "roa", None)])

    def test_a_comparative_note_about_another_word_is_rejected(self):
        # The trap: takapau's entry discusses momoe, which is no
        # reduplication of takapau.
        self.assertEqual(
            read_reduplications(
                "takapau",
                "mat. The reduplicated form momoe “sleep together” is "
                "inherited from a Proto Nuclear Polynesian term."),
            [])

    def test_the_word_of_is_never_taken_as_a_reduplication(self):
        # 'reduplicated form of X' is the FORWARD shape; the inverse reader
        # must not read 'of' as the named word.
        self.assertEqual(
            read_reduplications("emiemi", "gather. Reduplicated form of emi [1]"),
            [("emiemi", "emi", 1)])


class ReadNothing(unittest.TestCase):
    def test_a_definition_with_no_statement_yields_nothing(self):
        self.assertEqual(read_reduplications("ahu", "tend, foster, fashion"), [])

    def test_empty_input_is_tolerated(self):
        self.assertEqual(read_reduplications("ahu", None), [])
        self.assertEqual(read_reduplications(None, None), [])

    def test_the_same_pair_is_not_returned_twice(self):
        self.assertEqual(
            read_reduplications(
                "roa",
                "long. The reduplicated form roroa is used. "
                "See also the reduplicated form roroa."),
            [("roroa", "roa", None)])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_reduplication.py -q`
Expected: every test errors with `ModuleNotFoundError: No module named 'reduplication'`.

- [ ] **Step 3: Write the module**

Create `scripts/reduplication.py`:

```python
"""Read the reduplications papakupu states. Pure strings; no DB.

See docs/superpowers/specs/2026-09-21-reduplication-design.md.

This module never decides that a reduplication exists — papakupu does, in a
sentence. Nothing here is inferred from spelling, and that is a deliberate
rejection of the alternative: of 871 headwords in the corpus that are a stem
written twice, a sample of twelve found ONE genuine pair. 'hemihemi' (back
of the head) doubles 'hemi', the transliterated name James. Exact doubling
joins unrelated homographs far more often than it finds a derivation.

What the spellings ARE used for is rejecting a statement that turns out to
be about some other word, which papakupu's prose does three times.
"""
import re
import unicodedata

# 'ekeeke: (Reduplicated form of eke [2])' — the entry is the reduplication.
# NOT anchored on the opening bracket: 19 of the 20 forward statements are
# parenthesised and 'wareware' is not ('– reduplicated form of ware [2].)').
# The containment filter, not the punctuation, is what rejects a statement
# about another word, so requiring the bracket only loses a true pair.
_FORWARD = re.compile(
    r"reduplicated\s+forms?\s+of\s+([^\s\)\[,;]+)\s*(?:\[\s*(\d+)\s*\])?",
    re.I)
# 'hoko: In the reduplicated forms hohoko and hokohoko...' — the entry is the
# base. The negative lookahead keeps this off the forward shape's 'of'.
_INVERSE = re.compile(
    r"reduplicated\s+forms?,?\s+(?!of\b)([a-zāēīōū]+)"
    r"(?:\s*(?:and|,)\s*([a-zāēīōū]+))?", re.I)


def fold(text):
    """Lowercase and strip macrons, for comparison only.

    Unlike utils.normalise_search_key this does NOT collapse doubled vowels.
    That collapse turns 'ekeeke' into 'ekeke', which is no longer 'eke'
    twice — it destroys the seam that makes a reduplication visible, and it
    is the reason this module folds for itself instead of reusing the search
    key.
    """
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in decomposed
                   if unicodedata.category(c) != "Mn")


def is_plausible(child, base):
    """Could *child* be a reduplication of *base*? A filter, never a test.

    papakupu has already said it is. This only rejects a sentence that names
    a different word: takapau's entry discusses the cognate 'momoe', and
    puri's names 'pupuhi', which comes from 'puhi'.

    Deliberately loose — containment, not a pattern. Māori reduplicates in
    more shapes than a tidy rule admits: 'eke' -> 'ekeeke' (full), 'nui' ->
    'nunui' (initial syllable), 'korero' -> 'korerorero' (final foot),
    'pawera' -> 'pawerawera' (inside a compound), 'aria' -> 'ariaria' (two
    morae). A rule tight enough to name each shape rejected eight genuine
    statements while this was being designed, and throwing away what the
    source said is the worse error: the source's assertion, not our pattern,
    is what licenses the row.
    """
    c = fold(child).strip(".,;:")
    b = fold(base).strip(".,;:")
    return bool(c and b and c != b and len(c) > len(b) and b in c)


def read_reduplications(headword, definition):
    """[(child, base, sense_no|None)] for each statement in *definition*.

    Both shapes, forward first. A pair stated from both ends appears once;
    the forward statement is preferred because only it carries the base's
    sense number ('nanao' is stated by its own entry as 'nao [1]' and again
    by nao's entry with no number).
    """
    out, seen = [], set()
    text = definition or ""
    for match in _FORWARD.finditer(text):
        base = match.group(1).strip(".,;:")
        sense = match.group(2)
        if not is_plausible(headword, base):
            continue
        key = (fold(headword), fold(base))
        if key in seen:
            continue
        seen.add(key)
        out.append((headword, base, int(sense) if sense else None))
    for match in _INVERSE.finditer(text):
        for child in [g for g in match.groups()[:2] if g]:
            if not is_plausible(child, headword):
                continue
            key = (fold(child), fold(headword))
            if key in seen:
                continue
            seen.add(key)
            out.append((child, headword, None))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_reduplication.py -q`
Expected: 23 passed.

- [ ] **Step 5: Check it against the real corpus**

Run:

```bash
python - <<'PY'
import sqlite3, sys
sys.path.insert(0, "scripts"); sys.stdout.reconfigure(encoding="utf-8")
from reduplication import read_reduplications, fold
from utils import DB_PATH
con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
pairs = []
for hw, d in con.execute("SELECT headword, definition FROM papakupu_entries "
                         "WHERE definition LIKE '%eduplicat%'"):
    pairs.extend(read_reduplications(hw, d))
print("statements:", len(pairs),
      " distinct pairs:", len({(fold(c), fold(b)) for c, b, _ in pairs}))
PY
```

Expected exactly: `statements: 27  distinct pairs: 24`. A different number means the regexes drifted; stop and report rather than adjusting the expectation.

- [ ] **Step 6: Commit**

```bash
git add scripts/reduplication.py tests/test_reduplication.py
git commit -m "feat(reduplication): parse the reduplications papakupu states

Two prose shapes: the entry naming its base ('Reduplicated form of eke
[2]') and the entry naming its own reduplications ('In the reduplicated
forms hohoko and hokohoko'). 27 statements, 24 distinct pairs.

Nothing is inferred. Of 871 corpus headwords that are a stem written twice,
a twelve-row sample found one genuine pair — 'hemihemi' doubles 'hemi', the
transliterated name James — so spelling alone cannot license a derivation.
It is used only to reject a statement about a different word, which
papakupu's prose needs three times.

fold() keeps doubled vowels where normalise_search_key collapses them: that
collapse makes 'ekeeke' into 'ekeke', which is no longer 'eke' twice.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Normalisation and the asserted process

**Files:**
- Modify: `scripts/53_build_word_origin.py` — the `derived_from` block in `collect_derivations`
- Test: `tests/test_derivation_normalisation.py` (create)

**Interfaces:**
- Consumes: `relation.note` carrying the literal string `'reduplication'`, which Task 3 writes. Treat any other note as absent.
- Produces: nothing other tasks import. This task is self-contained inside `53_build_word_origin.py`.

**Context you need.** `collect_derivations` currently selects every `derived_from` relation and calls `describe_derivation(normalise_search_key(child), normalise_search_key(base_form))`. It already has a per-source `WARRANT` mapping giving `(evidence, derived, confidence)`, currently holding `williams` and `ngata`; a source absent from it is skipped.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_derivation_normalisation.py`:

```python
"""The affix is read off the spellings, so the normalisation decides it.

normalise_search_key strips macrons AND collapses doubled vowels. The
collapse is right for Williams, which writes a long vowel as a doubled
letter ('Paaha' is 'pāha'), and wrong wherever a doubled vowel is a morpheme
seam — it turns 'whaka-' into 'whak-' and '-ia' into '-a'.

No single normalisation serves both, so the rule is: try the strict
macron-only fold, and fall back to the collapsing key when it yields
nothing. Measured over all 6,153 rows on this path, 61 change and none
regresses.

See docs/superpowers/specs/2026-09-21-reduplication-design.md §6.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "word_origin",
    Path(__file__).parent.parent / "scripts" / "53_build_word_origin.py")
word_origin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(word_origin)


class Normalisation(unittest.TestCase):
    """_derivation_shape(child, base) -> (process, affix)."""

    def test_a_seam_is_not_eaten_by_the_prefix(self):
        # 'whaka' + 'aeaea'. Collapsing the seam gives 'whak-', losing the
        # final a of the most productive prefix in the language.
        self.assertEqual(word_origin._derivation_shape("whakaaeaea", "Aeaeā"),
                         ("prefix", "whaka-"))

    def test_a_seam_is_not_eaten_by_the_suffix(self):
        # 'kī' + '-ia'. Collapsing gives '-a', a different suffix, and the
        # per-suffix counts are exactly what this corpus is asked for.
        self.assertEqual(word_origin._derivation_shape("kīia", "kī"),
                         ("suffix", "-ia"))

    def test_a_doubling_across_a_vowel_reads_as_reduplication(self):
        self.assertEqual(word_origin._derivation_shape("awaawa", "Awa"),
                         ("reduplication", None))

    def test_a_plain_doubling_still_reads_as_reduplication(self):
        self.assertEqual(word_origin._derivation_shape("taketake", "take"),
                         ("reduplication", None))

    def test_williams_doubled_vowel_length_still_resolves(self):
        # Williams writes a long vowel doubled: 'Paaha' IS 'pāha'. The strict
        # fold finds nothing here, and the fallback is what keeps the row.
        self.assertEqual(word_origin._derivation_shape("whakapāha", "Paaha"),
                         ("prefix", "whaka-"))

    def test_a_mixed_double_and_macron_base_still_resolves(self):
        self.assertEqual(word_origin._derivation_shape("tiītoretore", "Tītore"),
                         ("suffix", "-tore"))

    def test_a_pair_the_collapse_hid_is_now_seen(self):
        # 'rūnāa' < 'rūnā' folded to the same key and yielded nothing.
        self.assertEqual(word_origin._derivation_shape("rūnāa", "rūnā"),
                         ("suffix", "-a"))

    def test_an_unrelated_pair_still_yields_nothing(self):
        self.assertEqual(word_origin._derivation_shape("kupu", "tangata"),
                         (None, None))


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, headword TEXT,
            loan_marker TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            gloss_en TEXT);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER, note TEXT);
        INSERT INTO entry VALUES (1, 'papakupu', 'ekeeke', NULL),
                                 (2, 'papakupu', 'eke',    NULL),
                                 (3, 'williams', 'hopukia', NULL),
                                 (4, 'williams', 'hopu',    NULL);
        INSERT INTO sense VALUES (10,1,1,NULL),(11,2,1,NULL),
                                 (12,3,1,NULL),(13,4,1,NULL);
        INSERT INTO relation VALUES
            (100, 1, 'derived_from', 'eke',  2, 'reduplication'),
            (101, 3, 'derived_from', 'hopu', 4, NULL);
    """)
    return con


class AssertedProcess(unittest.TestCase):
    def setUp(self):
        self.rows = {r["base_form"]: r
                     for r in word_origin.collect_derivations(_db())}

    def test_the_source_statement_beats_the_spellings(self):
        # describe_derivation reads 'ekeeke' < 'eke' as ('suffix','-ke').
        # papakupu says it is a reduplication, and papakupu is right.
        self.assertEqual(self.rows["eke"]["process"], "reduplication")
        self.assertIsNone(self.rows["eke"]["affix"])

    def test_papakupu_gets_its_own_evidence(self):
        self.assertEqual(self.rows["eke"]["evidence"],
                         "papakupu: stated as a reduplicated form")

    def test_a_stated_reduplication_is_attested_not_segmented(self):
        # The source said so in a sentence, so derived = 0.
        self.assertEqual(
            (self.rows["eke"]["derived"], self.rows["eke"]["confidence"]),
            (0, "certain"))

    def test_a_relation_without_the_marker_still_reads_its_spellings(self):
        self.assertEqual(self.rows["hopu"]["process"], "suffix")
        self.assertEqual(self.rows["hopu"]["evidence"],
                         "williams: printed under this base entry")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_derivation_normalisation.py -q`
Expected: FAIL with `AttributeError: module 'word_origin' has no attribute '_derivation_shape'`.

- [ ] **Step 3: Add the shape helper**

In `scripts/53_build_word_origin.py`, immediately above `collect_derivations`:

```python
def _derivation_shape(child, base):
    """(process, affix) for two spellings, strict fold first.

    normalise_search_key strips macrons AND collapses doubled vowels. The
    collapse is load-bearing for Williams, which writes a long vowel as a
    doubled letter — its 'Paaha' is 'pāha' — and destructive wherever a
    doubled vowel is a morpheme seam: it turns 'whaka' + 'aeaea' into the
    truncated 'whak-', and 'kī' + '-ia' into '-a'.

    The same 'aa' is a seam in one source and a long vowel in another, so no
    single normalisation serves both. Trying the strict fold first treats a
    doubled vowel as a seam where that yields a derivation, and as a long
    vowel where it does not. Over all 6,153 rows on this path, 61 change and
    none regresses.
    """
    strict = describe_derivation(fold_macrons(child), fold_macrons(base))
    if strict[0] is not None:
        return strict
    return describe_derivation(normalise_search_key(child),
                               normalise_search_key(base))
```

and add the import at the top of the file, beside the existing `from utils import ...` line:

```python
from reduplication import fold as fold_macrons
```

- [ ] **Step 4: Use it, and honour the source's assertion**

In `collect_derivations`, extend the `WARRANT` mapping and rewrite the loop body. Replace:

```python
    WARRANT = {
        "williams": ("williams: printed under this base entry", 0, "certain"),
        "ngata":    ("ngata: printed in one run with its base", 1, "probable"),
    }
    for src, eid, child, base_eid, base_form in con.execute(
            "SELECT e.source_id, r.entry_id, e.headword, r.target_entry_id, "
            "       r.target_headword "
            "  FROM relation r JOIN entry e ON e.id = r.entry_id "
            " WHERE r.rel_type = 'derived_from' AND r.target_entry_id IS NOT NULL"):
        warrant = WARRANT.get(src)
        if warrant is None:
```

with:

```python
    WARRANT = {
        "williams": ("williams: printed under this base entry", 0, "certain"),
        "ngata":    ("ngata: printed in one run with its base", 1, "probable"),
        "papakupu": ("papakupu: stated as a reduplicated form", 0, "certain"),
    }
    for src, eid, child, base_eid, base_form, note in con.execute(
            "SELECT e.source_id, r.entry_id, e.headword, r.target_entry_id, "
            "       r.target_headword, r.note "
            "  FROM relation r JOIN entry e ON e.id = r.entry_id "
            " WHERE r.rel_type = 'derived_from' AND r.target_entry_id IS NOT NULL"):
        warrant = WARRANT.get(src)
        if warrant is None:
```

and replace the line that reads the spellings:

```python
        process, affix = describe_derivation(normalise_search_key(child),
                                             normalise_search_key(base_form))
```

with:

```python
        if note == "reduplication":
            # The source said so in a sentence. describe_derivation reads
            # 'ekeeke' < 'eke' as ('suffix','-ke') — the seam collapses and
            # the answer is wrong. A statement beats our reading of letters.
            process, affix = "reduplication", None
        else:
            process, affix = _derivation_shape(child, base_form)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_derivation_normalisation.py -q`
Expected: 12 passed.

- [ ] **Step 6: Prove no row regresses**

Run against the real database, read-only:

```bash
python - <<'PY'
import importlib.util, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "scripts"); sys.stdout.reconfigure(encoding="utf-8")
_S = importlib.util.spec_from_file_location(
    "wo", Path("scripts/53_build_word_origin.py"))
wo = importlib.util.module_from_spec(_S); _S.loader.exec_module(wo)
from utils import DB_PATH
con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
changed = lost = 0
for child, base, process, affix in con.execute(
        "SELECT e.headword, d.base_form, d.process, d.affix FROM derivation d "
        "JOIN entry e ON e.id = d.entry_id "
        "WHERE d.evidence LIKE 'williams%' OR d.evidence LIKE 'ngata%'"):
    new = wo._derivation_shape(child, base)
    if (process, affix) != new:
        changed += 1
        if new[0] is None and process is not None:
            lost += 1
            print("REGRESSION:", child, base, (process, affix), "->", new)
print(f"changed: {changed}   regressions: {lost}")
PY
```

Expected exactly: `changed: 61   regressions: 0`. Any regression stops the task.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass. The database has not been rebuilt, so corpus counts are unchanged.

- [ ] **Step 8: Commit**

```bash
git add scripts/53_build_word_origin.py tests/test_derivation_normalisation.py
git commit -m "fix(derivation): stop a vowel collapse eating morpheme seams

The affix is read off two spellings, so the normalisation decides it, and
normalise_search_key collapses doubled vowels. That stored the most
productive prefix in the language as 'whak-' in 17 rows, and '-ia' as '-a',
corrupting the per-suffix counts this corpus exists to answer.

The collapse cannot simply go: Williams writes a long vowel as a doubled
letter, so its 'Paaha' is 'pāha' and three rows depend on it. The same 'aa'
is a seam in one source and a long vowel in another. _derivation_shape
tries the strict macron-only fold and falls back to the collapsing key: 61
rows corrected across all 6,153 on this path, zero regressions.

A derived_from relation noted 'reduplication' now takes that process
directly instead of re-deriving it. describe_derivation reads 'ekeeke' <
'eke' as ('suffix','-ke'); papakupu's sentence is better evidence than our
reading of the letters.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Wiring papakupu

**Files:**
- Modify: `scripts/50_build_unified.py` — add `_papakupu_reduplications` after `build_papakupu`; call it at the end of `build_papakupu`
- Test: `tests/test_papakupu_reduplication_wiring.py` (create)

**Interfaces:**
- Consumes: `read_reduplications(headword, definition) -> [(child, base, sense_no|None)]` and `fold(text)` from Task 1.
- Produces: `derived_from` relations on the CHILD entry, targeting the base entry, with `note='reduplication'` — which Task 2 already reads.

**Context you need.** A second pass is required, not an inline call. The inverse shape is stated on the *base's* entry but the relation must hang on the *child's*, and the child may not have been minted yet when its base row is processed. The pass runs after the main loop, over an index of the papakupu entries just created — the same shape as `_resolve_williams_see_also`.

`b.add_relation(entry_id, rel_type, target_headword, target_entry_id=None, note=None, target_sense_id=None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_papakupu_reduplication_wiring.py`:

```python
"""build_papakupu emits a derived_from relation per stated reduplication.

A second pass, because the inverse shape is stated on the BASE's entry while
the relation belongs on the CHILD's, and the child may not exist yet when
the base row is read.

Drives the real builder against an in-memory database. Corpus counts live in
tests/test_reduplication_corpus.py.
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


def _db(rows):
    """rows: (id, headword, sense_number, definition)"""
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
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            parent_sense_id INTEGER, gloss_en TEXT, gloss_mi TEXT,
            definition_raw TEXT, part_of_speech TEXT, part_of_speech_en TEXT,
            register TEXT, sort_no INTEGER, note TEXT);
        CREATE TABLE example (
            id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
            text_mi TEXT, text_en TEXT, source_abbrev TEXT, citation TEXT,
            sort_no INTEGER);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER,
            target_sense_id INTEGER, note TEXT);
        CREATE TABLE entry_domain (
            id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
            domain TEXT, domain_lang TEXT);
        CREATE TABLE papakupu_entries (
            id INTEGER PRIMARY KEY, headword TEXT, headword_sort TEXT,
            headword_search TEXT, part_of_speech TEXT, definition TEXT,
            usage_examples TEXT, variant_forms TEXT, see_also TEXT,
            source_code TEXT, loan_marker TEXT, sense_number INTEGER,
            pdf_page INTEGER);
    """)
    con.executemany(
        "INSERT INTO papakupu_entries (id, headword, headword_sort, "
        "headword_search, part_of_speech, definition, usage_examples, "
        "variant_forms, see_also, source_code, loan_marker, sense_number, "
        "pdf_page) VALUES (?,?,?,?,NULL,?,'[]','[]','[]','X',NULL,?,NULL)",
        [(i, hw, hw, hw.lower(), d, sn) for i, hw, sn, d in rows])
    return con


def _relations(con):
    return con.execute(
        "SELECT e.headword, r.rel_type, r.target_headword, r.note "
        "FROM relation r JOIN entry e ON e.id = r.entry_id "
        "WHERE r.rel_type = 'derived_from' "
        "ORDER BY e.headword, r.target_headword").fetchall()


class ForwardShape(unittest.TestCase):
    def setUp(self):
        self.con = _db([(1, "ekeeke", 1, "movement (Reduplicated form of eke [2])"),
                        (2, "eke", 1, "get on board"),
                        (3, "eke", 2, "mount")])
        b = build_unified.Builder(self.con, "papakupu", None, {})
        build_unified.build_papakupu(self.con, b)

    def test_the_relation_hangs_on_the_reduplication(self):
        self.assertEqual(_relations(self.con),
                         [("ekeeke", "derived_from", "eke", "reduplication")])

    def test_the_stated_sense_picks_the_right_base_entry(self):
        # 'eke [2]' names the second sense, which is a separate papakupu row.
        target = self.con.execute(
            "SELECT target_entry_id FROM relation "
            "WHERE rel_type = 'derived_from'").fetchone()[0]
        self.assertEqual(self.con.execute(
            "SELECT source_entry_id FROM entry WHERE id = ?",
            (target,)).fetchone()[0], "3")


class InverseShape(unittest.TestCase):
    def setUp(self):
        # The base is row 1 and names a child that is only minted at row 2 —
        # the ordering an inline call could not handle.
        self.con = _db([(1, "hoko", 1,
                         "trade. In the reduplicated forms hohoko and "
                         "hokohoko, the focus is on the process."),
                        (2, "hohoko", 1, "trading"),
                        (3, "hokohoko", 1, "bartering")])
        b = build_unified.Builder(self.con, "papakupu", None, {})
        build_unified.build_papakupu(self.con, b)

    def test_both_children_point_back_at_the_base(self):
        self.assertEqual(_relations(self.con), [
            ("hohoko", "derived_from", "hoko", "reduplication"),
            ("hokohoko", "derived_from", "hoko", "reduplication"),
        ])


class Skipped(unittest.TestCase):
    def test_a_statement_about_another_word_writes_nothing(self):
        con = _db([(1, "takapau", 1,
                    "mat. The reduplicated form momoe is inherited from "
                    "a Proto Nuclear Polynesian term."),
                   (2, "momoe", 1, "sleep together")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])

    def test_an_unresolved_end_writes_nothing(self):
        # papakupu names 'take', which it does not hold as an entry. The
        # word exists in 26 other sources, but papakupu names no source, so
        # reaching across would invent a pointer it never made.
        con = _db([(1, "take", 1,
                    "cause. The reduplicated form, taketake, includes "
                    "well-foundedness.")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])

    def test_an_entry_with_no_statement_writes_nothing(self):
        con = _db([(1, "ahu", 1, "tend, foster, fashion")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])


class NotDuplicated(unittest.TestCase):
    def test_the_stated_sense_survives_an_inverse_statement_read_first(self):
        # nao's own row is read first and states the pair with no sense
        # number; nanao's row states it as 'nao [2]'. Keeping whichever came
        # first would lose the number and resolve to the wrong base entry.
        con = _db([(1, "nao", 1, "handle. Used in the reduplicated forms "
                                 "nanao, naonao."),
                   (2, "nanao", 1, "grope (Reduplicated form of nao [2])"),
                   (3, "nao", 2, "grasp")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        target = con.execute(
            "SELECT r.target_entry_id FROM relation r "
            "JOIN entry e ON e.id = r.entry_id "
            "WHERE e.headword = 'nanao'").fetchone()[0]
        self.assertEqual(con.execute(
            "SELECT source_entry_id FROM entry WHERE id = ?",
            (target,)).fetchone()[0], "3")

    def test_a_pair_stated_from_both_ends_is_written_once(self):
        con = _db([(1, "nao", 1, "handle. Used in the reduplicated forms "
                                 "nanao, naonao."),
                   (2, "nanao", 1, "grope (Reduplicated form of nao [1])")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(
            [r for r in _relations(con) if r[0] == "nanao"],
            [("nanao", "derived_from", "nao", "reduplication")])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_papakupu_reduplication_wiring.py -q`
Expected: the relation assertions fail with `[] != [...]` — `build_papakupu` writes no `derived_from` yet.

- [ ] **Step 3: Add the import**

At the top of `scripts/50_build_unified.py`, beside `import suffix_forms`:

```python
import reduplication
```

- [ ] **Step 4: Add the second pass**

Immediately after `build_papakupu`:

```python
def _papakupu_reduplications(con, b):
    """derived_from relations for the reduplications papakupu states.

    A second pass, not an inline call. The inverse shape is stated on the
    BASE's entry — 'hoko: In the reduplicated forms hohoko and hokohoko' —
    while the relation belongs on the child's, and the child may not have
    been minted when its base row was read.

    The base's sense number is used when the source gives one: 'eke [2]' is
    a different papakupu row from 'eke [1]', and the rows are not stored in
    sense order, so the number has to be matched rather than counted. A
    pair stated from both ends keeps the statement that carries the
    number, whichever row came first.

    A pair whose other end papakupu does not hold is dropped. The word often
    exists in another source — 'taketake' is a headword in 26 — but
    papakupu names no source, so choosing one would invent a pointer it
    never made, and 53_build_word_origin drops an unresolved derived_from
    anyway.
    """
    # headword_search -> {sense_number or None: entry_id}
    index = {}
    for eid, key, sense in con.execute(
            "SELECT e.id, e.headword_search, p.sense_number "
            "  FROM entry e JOIN papakupu_entries p "
            "    ON p.id = CAST(e.source_entry_id AS INTEGER) "
            " WHERE e.source_id = 'papakupu'"):
        # Normalised again on the way in. add_entry stores headword_search
        # verbatim, and resolve() below normalises every lookup word, so the
        # two sides must agree. A no-op against real papakupu rows, which
        # arrive normalised already; without it a fixture holding a raw
        # 'ekeeke' would never match the collapsed lookup key 'ekeke'.
        index.setdefault(normalise_search_key(key), {})[sense] = eid

    def resolve(word, sense=None):
        by_sense = index.get(normalise_search_key(word))
        if not by_sense:
            return None
        if sense is not None and sense in by_sense:
            return by_sense[sense]
        return by_sense[sorted(by_sense, key=lambda s: (s is None, s))[0]]

    # A pair can be stated from both ends, and only the forward statement
    # carries the base's sense number. papakupu prints the two in no fixed
    # order, so collect first and keep the richer record; taking whichever
    # row id came first would silently drop the number.
    best, order = {}, []
    for hw, definition in con.execute(
            "SELECT headword, definition FROM papakupu_entries ORDER BY id"):
        for child, base, sense in reduplication.read_reduplications(hw, definition):
            key = (reduplication.fold(child), reduplication.fold(base))
            if key not in best:
                best[key] = (child, base, sense)
                order.append(key)
            elif sense is not None and best[key][2] is None:
                best[key] = (child, base, sense)
    for key in order:
        child, base, sense = best[key]
        child_eid, base_eid = resolve(child), resolve(base, sense)
        if child_eid is None or base_eid is None or child_eid == base_eid:
            continue
        b.add_relation(child_eid, "derived_from", base, base_eid,
                       note="reduplication")
```

- [ ] **Step 5: Call it**

At the very end of `build_papakupu`, after the `for t in jload(sa):` loop and dedented to the function's own level:

```python
    _papakupu_reduplications(con, b)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_papakupu_reduplication_wiring.py -q`
Expected: 8 passed.

- [ ] **Step 7: Simulate against the real papakupu rows**

Read-only; builds an in-memory copy, never the real database:

```bash
python - <<'PY'
import importlib.util, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "scripts"); sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH
_S = importlib.util.spec_from_file_location(
    "bu", Path("scripts/50_build_unified.py"))
bu = importlib.util.module_from_spec(_S); _S.loader.exec_module(bu)
real = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
cols = [r[1] for r in real.execute("PRAGMA table_info(papakupu_entries)")]
rows = real.execute(f"SELECT {','.join(cols)} FROM papakupu_entries").fetchall()
con = sqlite3.connect(":memory:")
for stmt in real.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name IN "
        "('entry','form','sense','example','relation','entry_domain',"
        "'papakupu_entries')"):
    con.execute(stmt[0])
con.executemany(
    f"INSERT INTO papakupu_entries ({','.join(cols)}) "
    f"VALUES ({','.join('?' * len(cols))})", rows)
b = bu.Builder(con, "papakupu", None, {})
bu.build_papakupu(con, b)
n = con.execute("SELECT COUNT(*) FROM relation WHERE rel_type='derived_from' "
                "AND note='reduplication'").fetchone()[0]
print("derived_from reduplication relations:", n)
PY
```

Expected exactly `18`. A different number means the resolver drifted; stop and report.

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass. The real database is untouched, so corpus counts are unchanged.

- [ ] **Step 9: Commit**

```bash
git add scripts/50_build_unified.py tests/test_papakupu_reduplication_wiring.py
git commit -m "feat(papakupu): emit derived_from for the stated reduplications

A second pass, not an inline call: the inverse shape is stated on the
base's entry ('hoko: In the reduplicated forms hohoko and hokohoko') while
the relation belongs on the child's, and the child may not be minted yet
when the base row is read.

The base's sense number is honoured where papakupu gives one — 'eke [2]' is
a different row from 'eke [1]', and the rows are not stored in sense order.
Pairs whose other end papakupu does not hold are dropped rather than
resolved into another source, which would invent a pointer papakupu never
made. 18 of 24 pairs survive.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Rebuild and pin the corpus

**Controller-only.** This task writes to the real 568MB database. Do not dispatch it to a subagent.

**Files:**
- Test: `tests/test_reduplication_corpus.py` (create)
- Data: `data/judgements.json`, `data/staging_dictionary.db`, `data/maori_dict.db`

- [ ] **Step 1: Snapshot the judgements**

```bash
python scripts/61_export_judgements.py
git diff data/judgements.json | grep -E "^[+-]" | grep -v "^[+-][+-]" | grep -v last_applied_at
```

Expected: the second command prints nothing — only timestamps moved — and the export still reports 18 judgements.

- [ ] **Step 2: Back up the database**

```bash
cp data/staging_dictionary.db \
   "data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-preredup"
```

- [ ] **Step 3: Rebuild papakupu's slice**

```bash
python scripts/50_build_unified.py --source papakupu > /tmp/pap.log 2>&1
echo "exit=$?"; tail -5 /tmp/pap.log
```

Expected: exit 0, and the `[papakupu] cleared …` line shows `relation` **18 higher** than before.

- [ ] **Step 4: Rebuild the derived chain**

```bash
python scripts/59_rebuild_derived.py > /tmp/rb.log 2>&1
echo "exit=$?"
grep -E "^===|derivation rows|concepts:|'kept'|FAILED|All derived" /tmp/rb.log
```

Expected: exit 0, `derivation rows: 11,442`, `concepts: 91,140`, `{'concepts': 91140, 'members': 175083, 'kept': 18, 'excluded': 0}`.

Never pipe this script through `head`.

- [ ] **Step 5: Write the corpus test**

Create `tests/test_reduplication_corpus.py`:

```python
"""Reduplication, counted against the built database.

papakupu states its reduplications in prose; we parse them and infer
nothing. Measured on 2026-09-21 after the rebuild:

    derivation total          11,424 -> 11,442   (+18)
    process='reduplication'      279 ->    302
      279 williams, + 5 relabelled from 'suffix', + 18 papakupu
    process='suffix'           5,175 ->  5,170
    process='prefix'             661 ->    662
    process NULL                  38 ->     37

61 rows on the derived_from path had their affix corrected by the
strict-then-fallback normalisation: 'whaka-' was stored as 'whak-', '-ia'
as '-a'.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

EXPECTED_PROCESS = {
    "compound": 5271,
    "suffix": 5170,
    "prefix": 662,
    "reduplication": 302,
}


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class Reduplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_the_process_distribution_is_exact(self):
        got = dict(self.con.execute(
            "SELECT process, COUNT(*) FROM derivation "
            "WHERE process IS NOT NULL GROUP BY 1").fetchall())
        self.assertEqual(got, EXPECTED_PROCESS)

    def test_papakupu_contributed_eighteen_reduplications(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence = 'papakupu: stated as a reduplicated form'"), 18)

    def test_every_papakupu_reduplication_is_attested_not_segmented(self):
        # The source said so in a sentence.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence LIKE 'papakupu: stated%' "
            "  AND (derived <> 0 OR confidence <> 'certain')"), 0)

    def test_a_stated_reduplication_carries_no_affix(self):
        # process comes from the sentence, not from the spellings; a
        # non-NULL affix here means describe_derivation was consulted.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation "
            "WHERE evidence LIKE 'papakupu: stated%' AND affix IS NOT NULL"), 0)

    def test_the_named_pairs_are_present(self):
        for child, base in (("ekeeke", "eke"), ("nanao", "nao"),
                            ("roroa", "roa"), ("waruwaru", "waru"),
                            ("whīwhiwhi", "whiwhi"), ("tukutuku", "tuku")):
            with self.subTest(child=child):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM derivation d "
                    "JOIN entry e ON e.id = d.entry_id "
                    "WHERE e.source_id = 'papakupu' AND e.headword = ? "
                    "  AND d.base_form = ?", child, base), 1)

    def test_the_traps_were_not_harvested(self):
        # takapau discusses the cognate momoe; puri names pupuhi, which is
        # from puhi. Neither is a reduplication of its entry.
        for base in ("takapau", "puri"):
            with self.subTest(base=base):
                self.assertEqual(self._one(
                    "SELECT COUNT(*) FROM derivation d "
                    "JOIN entry e ON e.id = d.base_entry_id "
                    "WHERE e.source_id = 'papakupu' AND e.headword = ? "
                    "  AND d.process = 'reduplication'", base), 0)

    def test_the_prefix_is_no_longer_truncated(self):
        # 'whaka-' was stored as 'whak-' in 17 rows.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE affix = 'whak-'"), 0)
        self.assertGreater(self._one(
            "SELECT COUNT(*) FROM derivation WHERE affix = 'whaka-'"), 100)

    def test_the_five_relabelled_doublings_are_reduplications(self):
        for word in ("awaawa", "eneene", "eweewe", "ikiiki", "ohooho"):
            with self.subTest(word=word):
                self.assertEqual(self._one(
                    "SELECT d.process FROM derivation d "
                    "JOIN entry e ON e.id = d.entry_id "
                    "WHERE e.headword = ? AND e.source_id = 'williams'",
                    word), "reduplication")

    def test_nothing_is_derived_from_itself(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE entry_id = base_entry_id"), 0)

    def test_the_compound_rows_were_not_touched(self):
        # They never pass through describe_derivation; a change here means
        # the normalisation fix reached further than its path.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE process = 'compound'"), 5271)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run the corpus test**

Run: `python -m pytest tests/test_reduplication_corpus.py -q`
Expected: 10 passed.

- [ ] **Step 7: Run the full suite and verify invariants**

Run: `python -m pytest tests/ -q` — all pass, calibration 17/17.

Then:

```bash
python - <<'PY'
import sqlite3, sys
sys.path.insert(0, "scripts"); sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH
con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
WANT = {"entry": 153440, "sense": 175101, "form": 35638,
        "derivation": 11442, "concept": 91140}
for t, want in WANT.items():
    got = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:<12} {got:>7}  want {want:>7}  "
          f"{'OK' if got == want else '*** DRIFT ***'}")
j = con.execute("SELECT COUNT(*) FROM concept_member "
                "WHERE status='confirmed'").fetchone()[0]
print(f"  judgements   {j:>7}  want      18  {'OK' if j == 18 else '*** DRIFT ***'}")
r = con.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
print(f"  relation     {r:>7}  want  175425  {'OK' if r == 175425 else '*** CHECK ***'}")
PY
```

Expected: every line OK. `relation` is 175,407 + 18.

- [ ] **Step 8: Commit**

```bash
git add tests/test_reduplication_corpus.py data/judgements.json
git commit -m "test(corpus): pin reduplication after the rebuild

derivation 11,424 -> 11,442. process='reduplication' 279 -> 302: 18 stated
by papakupu, 5 relabelled from 'suffix' where a collapsed vowel seam had
hidden the doubling.

61 rows had their affix corrected; 'whak-' no longer appears in the table.
The compound rows are pinned at 5,271 because they never pass through
describe_derivation — a guard against the normalisation fix reaching past
its own path.

entry, sense, form and concept are unchanged, and all 18 confirmed
judgements survived the rebuild.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** §2 (inference rejected) is realised as the absence of any detection task, and as the `reduplication.py` docstring. §3 (both shapes) is Task 1 Step 3 and Task 3's two test classes. §4 (the filter, and that it must not collapse vowels) is Task 1's `Filter` class and `fold`. §5 (process asserted, not re-derived) is Task 2 Step 4's `note == "reduplication"` branch, asserted by Task 4's no-affix test. §6 (normalisation) is Task 2 entire, with the zero-regression proof at Step 6. §7 (unresolved ends dropped) is Task 3's `test_an_unresolved_end_writes_nothing` and the `resolve` returning None. §8 (no new form_type) needs no task: nothing touches `form`. §9 is Task 4 Steps 6–7. §10 maps to the tests throughout; §11 is Task 4 Steps 1–4.

**Placeholder scan.** No TBD, no "handle edge cases", no "similar to Task N". Every code step carries its code; every test step carries its assertions.

**Type consistency.** `read_reduplications` returns `[(child, base, sense_no|None)]` in Task 1 and is unpacked as that triple in Task 3. `fold` is imported into Task 2 as `fold_macrons` to avoid shadowing, and used in Task 3 as `reduplication.fold`. `_derivation_shape(child, base) -> (process, affix)` is defined and used only inside Task 2. The note string `'reduplication'` is written in Task 3 and read in Task 2 — a mismatch there would silently fall through to the spellings, which Task 4's no-affix test catches.

**Verified before writing.** The Task 1 module was prototyped and run against the corpus: 27 statements, 24 distinct pairs, 18 with both ends resolvable. An earlier draft anchored the forward pattern on an opening bracket and silently dropped *wareware*, whose statement is unbracketed; the dry run caught it. The 61-changed/0-regressions figure was measured over all 6,153 rows on the `derived_from` path. The §9 process distribution was computed, not estimated.

**One risk worth naming.** Task 2 and Task 3 are mutually dependent at runtime: Task 2 reads a note Task 3 has not yet written. Task 2's unit tests supply that note synthetically, so it is testable alone, but the combination is only exercised end to end in Task 4. If Task 4's `test_a_stated_reduplication_carries_no_affix` fails, the note string is the first thing to check.
