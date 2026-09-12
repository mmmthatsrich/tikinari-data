# Concept Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group the corpus's 175,101 senses into concepts — one word as eleven dictionaries record it — with tiered confidence, and elect a canonical spelling from the witnesses.

**Architecture:** Single-source lexemes seed the concepts; cross-source witnesses attach one at a time on direct evidence to the concept, never transitively. Every membership carries its own evidence rows and confidence. Election chooses a canonical headword and glosses from strings a member actually wrote — never composed.

**Tech Stack:** Python 3.12, SQLite (WAL), `pytest`, `unittest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-concept-layer-design.md`

## Global Constraints

- **Never invent lexicographic content.** An elected value must be a string some member wrote.
- **Never rewrite, merge or delete a source entry.** The layer groups; it does not mutate.
- **`entry.id` is volatile across rebuilds.** Membership is keyed `(source_id, source_entry_id, sense_number)`; `entry_id`/`sense_id` are a cache.
- **The builder never overwrites a `confirmed` or `rejected` row.** It only adds or updates rows still `proposed`.
- **Same `headword_search` alone is never evidence.** It generates candidates only.
- **Ngata must never supply `gloss_en`.** Its gloss is the English lemma the word was listed under, not a definition.
- **TDD.** RED before GREEN, every task.
- Run Python as `py`, with `PYTHONUTF8=1` for anything printing Māori text.
- Commit with the repo's configured identity — plain `git commit`, no `-c` flags.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `scripts/concept_evidence.py` | Pure. Lexeme seeding keys, positive evidence detection, block rules, confidence. No DB. |
| `scripts/concept_election.py` | Pure. Canonical headword and gloss election. No DB. |
| `scripts/54_build_concepts.py` | The builder. Reads the unified core, writes `concept*` tables. |
| `scripts/59_rebuild_derived.py` | Runs `52 → 08b → 53 → 54 → 60` in order. |
| `tests/test_concept_evidence.py` | Unit tests for the evidence rules. |
| `tests/test_concept_election.py` | Unit tests for election. |
| `tests/test_concept_build.py` | Fixture-DB tests: seeding, attachment, non-transitivity, rebuild survival. |
| `tests/test_concept_acceptance.py` | DB invariants + the judged calibration clusters as acceptance tests. |

**Modify:**

| File | Change |
|---|---|
| `scripts/00_init_db.py` | Add `concept`, `concept_member`, `concept_member_evidence` DDL. |
| `scripts/50_build_unified.py` | `delete_source_slice`: null the `entry_id`/`sense_id` cache rather than deleting memberships. |
| `scripts/sweep_batch.py` | Add a CONCEPTS section to `assemble` / `render`. |
| `scripts/sweep_runner.py` | Accept `concept_actions` nested in findings. |
| `scripts/60_export_app_db.py` | Add `concept`, `concept_member` to `APP_TABLES`, filtered by confidence. |

### The shared sense-view

Tasks 2–7 pass this dict. Defined once in `concept_evidence.py`, built in Task 6.

```python
{
  "member_key":   (source_id, source_entry_id, sense_number),  # stable address
  "source_id":    str,
  "entry_id":     int,
  "sense_id":     int,
  "source_entry_id": str,
  "sense_number": int | None,
  "headword":     str,
  "headword_search": str,
  "pos":          str | None,
  "gloss_en":     str | None,
  "gloss_mi":     str | None,
  "lexeme":       tuple,             # from lexeme_key()
  "cognate_sets": frozenset,         # cognateset ids
  "examples":     frozenset,         # normalised text_mi
  "citations":    frozenset,         # normalised citation strings
  "cites":        frozenset,         # entry_ids this sense cites cross-source
}
```

---

### Task 1: Schema

**Files:**
- Modify: `scripts/00_init_db.py`
- Test: `tests/test_concept_build.py`

**Interfaces:**
- Consumes: nothing.
- Produces: tables `concept`, `concept_member`, `concept_member_evidence`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_concept_build.py`:

```python
"""Concept layer build tests."""
import re
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_SRC = Path(__file__).parent.parent / "scripts" / "00_init_db.py"


def concept_ddl() -> str:
    """The concept DDL block, lifted from 00_init_db so tests build the real thing."""
    text = SCHEMA_SRC.read_text(encoding="utf-8")
    m = re.search(r"(CREATE TABLE IF NOT EXISTS concept \(.*?"
                  r"idx_concept_member_lookup[^;]*;)", text, re.S)
    assert m, "concept DDL not found in 00_init_db.py"
    return m.group(1)


class Schema(unittest.TestCase):
    def test_the_three_tables_exist(self):
        con = sqlite3.connect(":memory:")
        con.executescript(concept_ddl())
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(
            names & {"concept", "concept_member", "concept_member_evidence"},
            {"concept", "concept_member", "concept_member_evidence"})

    def test_a_member_is_unique_per_concept_and_address(self):
        con = sqlite3.connect(":memory:")
        con.executescript(concept_ddl())
        con.execute("INSERT INTO concept (id, status, confidence) "
                    "VALUES (1,'proposed','probable')")
        row = ("INSERT INTO concept_member (concept_id, source_id, "
               "source_entry_id, sense_number, status, confidence) "
               "VALUES (1,'williams','1251',1,'proposed','certain')")
        con.execute(row)
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(row)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: FAIL — `AssertionError: concept DDL not found in 00_init_db.py`

- [ ] **Step 3: Add the DDL**

In `scripts/00_init_db.py`, immediately after the line
`CREATE INDEX IF NOT EXISTS idx_loan_origin_entry ON loan_origin(entry_id);`
add:

```sql
        -- ── concept: one word, as eleven dictionaries record it ──────────────
        -- docs/superpowers/specs/2026-09-12-concept-layer-design.md
        -- Groups witnesses; never merges, rewrites or deletes a source entry.
        CREATE TABLE IF NOT EXISTS concept (
            id                INTEGER PRIMARY KEY,
            status            TEXT NOT NULL,   -- proposed | confirmed | rejected
            confidence        TEXT NOT NULL,   -- certain | probable | uncertain
            -- Elected, never written. Each value names the member it came from.
            headword          TEXT,
            headword_from     INTEGER,
            gloss_en          TEXT,
            gloss_en_from     INTEGER,
            gloss_mi          TEXT,
            gloss_mi_from     INTEGER,
            created_at        TEXT,
            last_updated      TEXT
        );

        -- entry_id / sense_id are a CACHE. entry.id is volatile across rebuilds,
        -- so the stable address is (source_id, source_entry_id, sense_number) --
        -- the same keying sweep_patch uses.
        CREATE TABLE IF NOT EXISTS concept_member (
            id                INTEGER PRIMARY KEY,
            concept_id        INTEGER NOT NULL REFERENCES concept(id),
            source_id         TEXT NOT NULL,
            source_entry_id   TEXT NOT NULL,
            sense_number      INTEGER,
            entry_id          INTEGER,
            sense_id          INTEGER,
            status            TEXT NOT NULL,   -- proposed | confirmed | rejected
            confidence        TEXT NOT NULL,
            created_at        TEXT,
            UNIQUE (concept_id, source_id, source_entry_id, sense_number)
        );

        CREATE TABLE IF NOT EXISTS concept_member_evidence (
            id                INTEGER PRIMARY KEY,
            member_id         INTEGER NOT NULL REFERENCES concept_member(id),
            kind              TEXT NOT NULL,
            detail            TEXT NOT NULL,
            weight            REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_concept_member_concept
            ON concept_member(concept_id);
        CREATE INDEX IF NOT EXISTS idx_concept_member_evidence
            ON concept_member_evidence(member_id);
        CREATE INDEX IF NOT EXISTS idx_concept_member_lookup
            ON concept_member(source_id, source_entry_id, sense_number);
```

`entry_id` and `sense_id` deliberately carry **no** `REFERENCES` clause: a rebuild deletes and recreates those rows, and a foreign key would block it.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Create the tables in the live staging DB**

```bash
PYTHONUTF8=1 py -c "
import sqlite3, sys; sys.path.insert(0,'tests')
from test_concept_build import concept_ddl
c = sqlite3.connect('data/staging_dictionary.db')
c.executescript(concept_ddl()); c.commit()
print([r[0] for r in c.execute(\"select name from sqlite_master where type='table' and name like 'concept%'\")])
"
```
Expected: `['concept', 'concept_member', 'concept_member_evidence']`

- [ ] **Step 6: Commit**

```bash
git add scripts/00_init_db.py tests/test_concept_build.py
git commit -m "feat(concept): schema for concepts, members and their evidence"
```

---

### Task 2: Lexeme seeding keys

**Files:**
- Create: `scripts/concept_evidence.py`
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `lexeme_key(source_id, source_entry_id, headword_search, locator) -> tuple`, `SEED_CONFIDENCE: dict[str, str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_concept_evidence.py`:

```python
"""Evidence rules for concept membership.

Each source groups its own senses into words differently, and that grouping is
STATED structure rather than inference — which is why seeds are trusted and
cross-source attachment is not.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_evidence import SEED_CONFIDENCE, lexeme_key


class LexemeKey(unittest.TestCase):
    def test_williams_groups_by_entry(self):
        # Williams files Hiwi as 1250, 1251, 1252 — three words, three lexemes.
        a = lexeme_key("williams", "1251", "hiwi", None)
        b = lexeme_key("williams", "1250", "hiwi", None)
        self.assertNotEqual(a, b)

    def test_te_aka_groups_by_entry(self):
        self.assertNotEqual(lexeme_key("te_aka", "1331", "hoi", None),
                            lexeme_key("te_aka", "1332", "hoi", None))

    def test_hepatakakupu_groups_by_word_id_in_the_locator(self):
        # Five entries, one lemma: the source says so via word_id.
        a = lexeme_key("hepatakakupu", "19969", "hiwi", "word_id=930")
        b = lexeme_key("hepatakakupu", "20526", "hiwi", "word_id=930")
        self.assertEqual(a, b)

    def test_hepatakakupu_separates_different_word_ids(self):
        self.assertNotEqual(
            lexeme_key("hepatakakupu", "300", "hurori", "word_id=1226"),
            lexeme_key("hepatakakupu", "303", "turori", "word_id=9889"))

    def test_ngata_groups_by_headword_within_the_source(self):
        # 14 'hoatu' rows are one word seen from 13 English lemmas.
        self.assertEqual(lexeme_key("ngata", "WR-HMN.5013#32977~1", "hoatu", None),
                         lexeme_key("ngata", "WR-HMN.3136#30213~1", "hoatu", None))

    def test_papakupu_groups_by_headword(self):
        self.assertEqual(lexeme_key("papakupu", "2", "a", None),
                         lexeme_key("papakupu", "3", "a", None))

    def test_a_missing_locator_falls_back_to_the_entry(self):
        self.assertNotEqual(lexeme_key("hepatakakupu", "1", "x", None),
                            lexeme_key("hepatakakupu", "2", "x", None))

    def test_ngata_seeds_are_probable_not_certain(self):
        # Grouping by headword would merge two genuine Ngata homographs and
        # nothing in Ngata's structure would say otherwise.
        self.assertEqual(SEED_CONFIDENCE["ngata"], "probable")
        self.assertEqual(SEED_CONFIDENCE.get("williams", "certain"), "certain")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_evidence.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'concept_evidence'`

- [ ] **Step 3: Write the implementation**

Create `scripts/concept_evidence.py`:

```python
"""Evidence rules for concept membership. Pure strings and dicts; no DB.

See docs/superpowers/specs/2026-09-12-concept-layer-design.md.

Within a source, identity is STATED — each source groups its own senses into
words. Across sources it must be inferred from circumstantial evidence and
judged. These functions keep those two things apart.
"""
import re

# Grouping by headword inside a source is right for Ngata's 14 'hoatu' rows,
# but it would merge two genuine Ngata homographs and nothing in the source's
# structure would say otherwise. Everything else is 'certain'.
SEED_CONFIDENCE = {"ngata": "probable", "papakupu": "probable"}

_WORD_ID = re.compile(r"word_id=(\d+)")

# Sources whose senses are split across rows sharing one headword.
_GROUP_BY_HEADWORD = {"ngata", "papakupu"}


def lexeme_key(source_id, source_entry_id, headword_search, locator):
    """Which lexeme a sense belongs to WITHIN its own source.

    He Pātaka Kupu scatters one lemma over several rows and names the grouping
    in entry.locator ('word_id=930'). Ngata and Papakupu split by headword.
    Williams and Te Aka give one entry per word.
    """
    if source_id == "hepatakakupu":
        m = _WORD_ID.search(locator or "")
        if m:
            return (source_id, "word", m.group(1))
    if source_id in _GROUP_BY_HEADWORD:
        return (source_id, "hw", (headword_search or "").strip().lower())
    return (source_id, "entry", str(source_entry_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_evidence.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_evidence.py
git commit -m "feat(concept): lexeme seeding keys, one rule per source"
```

---

### Task 3: Positive evidence

**Files:**
- Modify: `scripts/concept_evidence.py`
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Consumes: the sense-view dict (see File Structure).
- Produces: `positive_evidence(a, b) -> list[dict]` where each dict is `{"kind": str, "detail": str, "weight": float}`; `EVIDENCE_WEIGHT: dict[str, float]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_evidence.py` (and extend the import line to
`from concept_evidence import EVIDENCE_WEIGHT, SEED_CONFIDENCE, lexeme_key, positive_evidence`):

```python
def _sense(**kw):
    """A sense-view with empty defaults, so each test states only what matters."""
    base = {
        "member_key": ("x", "1", 1), "source_id": "x", "entry_id": 1,
        "sense_id": 1, "source_entry_id": "1", "sense_number": 1,
        "headword": "hiwi", "headword_search": "hiwi", "pos": None,
        "gloss_en": None, "gloss_mi": None, "lexeme": ("x", "entry", "1"),
        "cognate_sets": frozenset(), "examples": frozenset(),
        "citations": frozenset(), "cites": frozenset(),
    }
    base.update(kw)
    return base


class PositiveEvidence(unittest.TestCase):
    def test_a_citation_of_the_other_entry_is_the_strongest_evidence(self):
        a = _sense(source_id="te_matatiki", entry_id=10, cites=frozenset({99}))
        b = _sense(source_id="williams", entry_id=99)
        kinds = [e["kind"] for e in positive_evidence(a, b)]
        self.assertIn("cites_source", kinds)

    def test_a_shared_example_sentence(self):
        s = "kua pau katoa nga kai"
        a = _sense(source_id="ngata", examples=frozenset({s}))
        b = _sense(source_id="williams", examples=frozenset({s}))
        self.assertIn("shared_example",
                      [e["kind"] for e in positive_evidence(a, b)])

    def test_a_shared_citation(self):
        a = _sense(source_id="te_aka", citations=frozenset({"w 1971:54"}))
        b = _sense(source_id="williams", citations=frozenset({"w 1971:54"}))
        self.assertIn("attributed_quote",
                      [e["kind"] for e in positive_evidence(a, b)])

    def test_a_shared_cognate_set_is_not_evidence(self):
        # REMOVED 2026-09-12: every entry-to-cognate link in this corpus is
        # match_method='headword_exact', so a shared cognate set only restates
        # the shared headword — circular, and it merged three unrelated 'hoi'
        # words into one concept. The spec's evidence table was corrected; this
        # plan was not, which is what this row fixes.
        a = _sense(source_id="te_aka", cognate_sets=frozenset({7}))
        b = _sense(source_id="williams", cognate_sets=frozenset({7, 9}))
        self.assertEqual([], positive_evidence(a, b))

    def test_gloss_overlap_on_content_words(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        self.assertIn("gloss_overlap",
                      [e["kind"] for e in positive_evidence(a, b)])

    def test_stopwords_alone_are_not_overlap(self):
        # 'of a the' must never link two senses.
        a = _sense(source_id="te_aka", gloss_en="of a the")
        b = _sense(source_id="papakupu", gloss_en="of a the")
        self.assertEqual([], positive_evidence(a, b))

    def test_the_same_headword_alone_is_never_evidence(self):
        a = _sense(source_id="te_aka")
        b = _sense(source_id="williams")
        self.assertEqual([], positive_evidence(a, b))

    def test_evidence_within_one_source_is_not_counted(self):
        # Seeding already handles within-source grouping; counting it again
        # would let one source's internal repetition look like corroboration.
        s = "kua pau katoa nga kai"
        a = _sense(source_id="ngata", examples=frozenset({s}))
        b = _sense(source_id="ngata", examples=frozenset({s}))
        self.assertEqual([], positive_evidence(a, b))

    def test_every_kind_has_a_weight(self):
        for kind in ("cites_source", "shared_example", "attributed_quote",
                     "gloss_overlap"):
            self.assertIn(kind, EVIDENCE_WEIGHT)

    def test_detail_says_what_the_evidence_actually_was(self):
        a = _sense(source_id="te_aka", gloss_en="ridge of a hill")
        b = _sense(source_id="papakupu", gloss_en="ridge of a hill")
        detail = positive_evidence(a, b)[0]["detail"]
        self.assertIn("ridge", detail)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_evidence.py -q`
Expected: FAIL — `ImportError: cannot import name 'positive_evidence'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/concept_evidence.py`:

```python
# Ordered strongest first. The confidence a membership earns is the strongest
# kind present, so these are tiers rather than a sum.
EVIDENCE_WEIGHT = {
    "cites_source":       1.0,   # Te Matatiki citing 'himoemoe W.50'
    "shared_example":     0.9,   # two sources printing the same sentence
    "attributed_quote":   0.7,   # Te Aka citing 'W 1971:54'
    # No shared_cognate_set: cognate links are matched on spelling alone
    # (match_method='headword_exact'), so counting one is circular.
    "gloss_overlap":      0.5,
}

EVIDENCE_CONFIDENCE = {
    "cites_source":       "certain",
    "shared_example":     "certain",
    "attributed_quote":   "probable",
    "gloss_overlap":      "probable",
}

_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "is", "be", "or", "and", "for", "with",
    "as", "by", "at", "from", "on", "into", "it", "that", "this", "any", "some",
    "one", "used", "esp", "etc", "see", "also", "n", "v", "adj", "vt", "vi",
})

# The one tuning parameter in the design. Set by measuring against the judged
# calibration clusters (Task 14); two shared content words is the floor that
# keeps 'ridge of a hill' while rejecting 'of a the'.
GLOSS_OVERLAP_MIN = 2


def _content_words(text):
    return frozenset(w for w in re.findall(r"[a-z]+", (text or "").lower())
                     if w not in _STOPWORDS and len(w) > 2)


def positive_evidence(a, b):
    """[{kind, detail, weight}] linking two senses, strongest first.

    Cross-source only. Within-source grouping is the seeding step's job, and
    counting it here would let one source's internal repetition masquerade as
    corroboration from another.

    Same headword_search is deliberately absent: it generates candidates, and
    is never itself evidence.
    """
    if a["source_id"] == b["source_id"]:
        return []

    found = []

    if b["entry_id"] in a["cites"] or a["entry_id"] in b["cites"]:
        found.append(("cites_source",
                      f"{a['source_id']} cites the {b['source_id']} entry"))

    shared_ex = a["examples"] & b["examples"]
    if shared_ex:
        found.append(("shared_example",
                      f"both print {sorted(shared_ex)[0][:60]!r}"))

    shared_cit = a["citations"] & b["citations"]
    if shared_cit:
        found.append(("attributed_quote",
                      f"both cite {sorted(shared_cit)[0][:40]!r}"))

    # cognate_sets is carried on the sense-view for later display use and is
    # deliberately NOT consulted: see EVIDENCE_WEIGHT above.

    overlap = _content_words(a["gloss_en"]) & _content_words(b["gloss_en"])
    if len(overlap) >= GLOSS_OVERLAP_MIN:
        found.append(("gloss_overlap",
                      "glosses share " + ", ".join(sorted(overlap)[:4])))

    return [{"kind": k, "detail": d, "weight": EVIDENCE_WEIGHT[k]}
            for k, d in found]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_evidence.py -q`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_evidence.py
git commit -m "feat(concept): positive evidence kinds, cross-source only"
```

---

### Task 4: Blocks and confidence

**Files:**
- Modify: `scripts/concept_evidence.py`
- Test: `tests/test_concept_evidence.py`

**Interfaces:**
- Consumes: the sense-view dict.
- Produces: `blocks(a, b) -> list[str]`, `confidence_for(evidence, blocked) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_evidence.py` (extend the import to include `blocks, confidence_for`):

```python
class Blocks(unittest.TestCase):
    def test_a_sources_own_homograph_numbering_blocks(self):
        # Williams files Hiwi as 1250 and 1251: that IS Williams saying these
        # are different words.
        a = _sense(source_id="williams", lexeme=("williams", "entry", "1250"))
        b = _sense(source_id="williams", lexeme=("williams", "entry", "1251"))
        self.assertTrue(blocks(a, b))

    def test_the_same_lexeme_in_one_source_does_not_block(self):
        a = _sense(source_id="williams", lexeme=("williams", "entry", "1251"))
        b = _sense(source_id="williams", lexeme=("williams", "entry", "1251"))
        self.assertEqual([], blocks(a, b))

    def test_macron_disagreement_blocks(self):
        # hia and hiia share a key only because headword_search strips macrons.
        a = _sense(source_id="te_aka", headword="hia")
        b = _sense(source_id="ngata", headword="hīa")
        self.assertTrue(blocks(a, b))

    def test_identical_spelling_does_not_block(self):
        a = _sense(source_id="te_aka", headword="hīmoemoe")
        b = _sense(source_id="ngata", headword="hīmoemoe")
        self.assertEqual([], blocks(a, b))

    def test_capitalisation_alone_does_not_block(self):
        # Williams capitalises its main headwords.
        a = _sense(source_id="williams", headword="Hīmoemoe")
        b = _sense(source_id="paekupu", headword="hīmoemoe")
        self.assertEqual([], blocks(a, b))

    def test_incompatible_part_of_speech_blocks(self):
        a = _sense(source_id="te_aka", pos="Noun")
        b = _sense(source_id="williams", pos="Verb (transitive)")
        self.assertTrue(blocks(a, b))

    def test_a_missing_part_of_speech_never_blocks(self):
        a = _sense(source_id="te_aka", pos=None)
        b = _sense(source_id="williams", pos="Noun")
        self.assertEqual([], blocks(a, b))

    def test_a_shared_pos_atom_does_not_block(self):
        a = _sense(source_id="te_aka", pos="Noun, Modifier")
        b = _sense(source_id="williams", pos="Modifier")
        self.assertEqual([], blocks(a, b))

    def test_a_block_says_why(self):
        a = _sense(source_id="te_aka", headword="hia")
        b = _sense(source_id="ngata", headword="hīa")
        self.assertIn("macron", blocks(a, b)[0].lower())


class Confidence(unittest.TestCase):
    def test_the_strongest_kind_wins(self):
        ev = [{"kind": "gloss_overlap"}, {"kind": "shared_example"}]
        self.assertEqual(confidence_for(ev, []), "certain")

    def test_a_block_downgrades_to_uncertain(self):
        ev = [{"kind": "shared_example"}]
        self.assertEqual(confidence_for(ev, ["macron disagreement"]), "uncertain")

    def test_no_evidence_is_uncertain(self):
        self.assertEqual(confidence_for([], []), "uncertain")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_evidence.py -q`
Expected: FAIL — `ImportError: cannot import name 'blocks'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/concept_evidence.py`:

```python
_MACRONS = str.maketrans("āēīōūĀĒĪŌŪ", "aeiouAEIOU")

_CONFIDENCE_ORDER = ("uncertain", "probable", "certain")


def _macron_shape(headword):
    """Which vowels a spelling marks long — the claim it makes about length."""
    text = (headword or "").strip().lower()
    return tuple(ch in "āēīōū" for ch in text)


def _pos_atoms(pos):
    return frozenset(p.strip().lower()
                     for p in re.split(r"[,/|]", pos or "") if p.strip())


def blocks(a, b):
    """Reasons these two senses must NOT share a concept.

    Negative evidence is first-class and is the safety mechanism of the whole
    design: it is what stops a third source, compatible with each of two
    separated words, quietly joining them.
    """
    reasons = []

    # A source's own structure separating them outranks any inference.
    if a["source_id"] == b["source_id"] and a["lexeme"] != b["lexeme"]:
        reasons.append(
            f"{a['source_id']} files these as different words "
            f"({a['lexeme'][-1]} vs {b['lexeme'][-1]})")

    # headword_search strips macrons, so two spellings can share a key while
    # making opposite claims about vowel length: hia vs hīa.
    ha, hb = (a["headword"] or "").strip().lower(), (b["headword"] or "").strip().lower()
    if ha and hb and ha != hb:
        if ha.translate(_MACRONS) == hb.translate(_MACRONS):
            if _macron_shape(ha) != _macron_shape(hb):
                reasons.append(f"macron disagreement: {ha!r} vs {hb!r}")

    atoms_a, atoms_b = _pos_atoms(a["pos"]), _pos_atoms(b["pos"])
    if atoms_a and atoms_b and not (atoms_a & atoms_b):
        reasons.append(f"incompatible part of speech: {a['pos']!r} vs {b['pos']!r}")

    return reasons


def confidence_for(evidence, blocked):
    """Strongest positive kind present, downgraded to uncertain by any block."""
    if blocked or not evidence:
        return "uncertain"
    best = max(_CONFIDENCE_ORDER.index(EVIDENCE_CONFIDENCE[e["kind"]])
               for e in evidence)
    return _CONFIDENCE_ORDER[best]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_evidence.py -q`
Expected: PASS (30 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_evidence.py
git commit -m "feat(concept): block rules and confidence, negative evidence first-class"
```

---

### Task 5: Election

**Files:**
- Create: `scripts/concept_election.py`
- Test: `tests/test_concept_election.py`

**Interfaces:**
- Consumes: a list of sense-view dicts (the concept's members), plus `{member_key: base_is_macronised}` from `derivation`.
- Produces: `elect_headword(members, derived_long) -> (value, member_key, reason)`, `elect_gloss(members, lang) -> (value, member_key)`, `GLOSS_EN_PRECEDENCE: tuple`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_concept_election.py`:

```python
"""Electing a concept's canonical form from its witnesses.

The elected value is always a string some member actually wrote. Never
composed — that is what lets the corpus state a canonical form without
inventing lexicographic content.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from concept_election import (GLOSS_EN_PRECEDENCE, elect_gloss, elect_headword)


def _m(source_id, headword, gloss_en=None, gloss_mi=None, key=None):
    return {"member_key": key or (source_id, "1", 1), "source_id": source_id,
            "headword": headword, "gloss_en": gloss_en, "gloss_mi": gloss_mi}


class ElectHeadword(unittest.TestCase):
    def test_morphology_settles_it(self):
        # hoomai is long because it is hoo + mai. Beats any vote.
        members = [_m("williams", "Homai"), _m("te_aka", "homai"),
                   _m("paekupu", "hōmai")]
        value, key, reason = elect_headword(members, derived_long=True)
        self.assertEqual(value, "hōmai")
        self.assertIn("derivation", reason)

    def test_a_macronised_spelling_is_preferred_over_a_bare_one(self):
        # A source marking length makes a claim; one omitting it may simply
        # not mark length. Williams 1957 is the case in point.
        members = [_m("williams", "Hurori"), _m("ngata", "hūrori")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertEqual(value, "hūrori")

    def test_source_precedence_breaks_a_tie(self):
        members = [_m("ngata", "hīmoemoe"), _m("te_aka", "hīmoemoe")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertEqual(key[0], "te_aka")

    def test_no_macron_anywhere_elects_no_macron(self):
        # A Williams-only concept keeps its unmacronised spelling and the gap
        # stays visible. This is D18's 2,297, reported rather than guessed.
        members = [_m("williams", "Aho")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertEqual(value, "Aho")

    def test_the_elected_value_is_always_a_string_a_member_wrote(self):
        members = [_m("williams", "Hurori"), _m("ngata", "hūrori")]
        value, key, reason = elect_headword(members, derived_long=False)
        self.assertIn(value, [m["headword"] for m in members])

    def test_no_members_elects_nothing(self):
        self.assertEqual(elect_headword([], derived_long=False),
                         (None, None, None))


class ElectGloss(unittest.TestCase):
    def test_english_follows_source_precedence(self):
        members = [_m("papakupu", "hiwi", gloss_en="ridge of a hill"),
                   _m("te_aka", "hiwi", gloss_en="ridge (of a hill).")]
        value, key = elect_gloss(members, "en")
        self.assertEqual(key[0], "te_aka")

    def test_ngata_never_supplies_the_english_gloss(self):
        # Ngata's gloss is the English LEMMA the word was listed under, not a
        # definition: huripari, a hurricane, is glossed 'Wind'.
        members = [_m("ngata", "huripari", gloss_en="Wind"),
                   _m("papakupu", "huripari", gloss_en="fierce wind, tornado")]
        value, key = elect_gloss(members, "en")
        self.assertEqual(value, "fierce wind, tornado")

    def test_ngata_alone_supplies_no_english_gloss_at_all(self):
        members = [_m("ngata", "huripari", gloss_en="Wind")]
        self.assertEqual(elect_gloss(members, "en"), (None, None))

    def test_maori_comes_from_hepatakakupu(self):
        members = [_m("te_aka", "hiwi"),
                   _m("hepatakakupu", "hiwi", gloss_mi="Te pae o ētahi puke.")]
        value, key = elect_gloss(members, "mi")
        self.assertEqual(key[0], "hepatakakupu")

    def test_ngata_is_last_in_the_precedence_list(self):
        self.assertEqual(GLOSS_EN_PRECEDENCE[-1], "ngata")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_election.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'concept_election'`

- [ ] **Step 3: Write the implementation**

Create `scripts/concept_election.py`:

```python
"""Elect a concept's canonical form from its witnesses. Pure; no DB.

The elected value is ALWAYS a string some member actually wrote. Never
composed. That is what lets the corpus state a canonical form while keeping
the rubric's first rule — never invent lexicographic content.
"""

_MACRON_VOWELS = "āēīōū"

# D18's counts: te_aka can supply 1,943 of the 2,297 contested spellings,
# then hepatakakupu (1,530) and ngata (1,075).
HEADWORD_PRECEDENCE = (
    "te_aka", "hepatakakupu", "paekupu", "papakupu", "taikupu",
    "te_matatiki", "kimikupu_hou", "ngata", "temarareo", "williams",
    "tregear_exceptions",
)

# Ngata is LAST on purpose, and excluded entirely below: its gloss is the
# English lemma the word was listed under, not a definition. 'huripari', a
# hurricane, is glossed 'Wind' because it sits in a list of fifteen winds.
GLOSS_EN_PRECEDENCE = (
    "te_aka", "williams", "papakupu", "paekupu", "te_matatiki",
    "taikupu", "kimikupu_hou", "tregear_exceptions", "ngata",
)

_NO_GLOSS_EN = frozenset({"ngata"})

GLOSS_MI_PRECEDENCE = ("hepatakakupu", "paekupu", "te_aka")


def _has_macron(headword):
    return any(ch in _MACRON_VOWELS for ch in (headword or "").lower())


def _rank(source_id, order):
    return order.index(source_id) if source_id in order else len(order)


def elect_headword(members, derived_long):
    """(value, member_key, reason) — the canonical spelling, or (None,)*3.

    `derived_long` is True when the `derivation` table says this word is formed
    on a base whose vowel is long, which settles the macron outright.
    """
    if not members:
        return (None, None, None)

    macronised = [m for m in members if _has_macron(m["headword"])]

    if derived_long and macronised:
        best = min(macronised, key=lambda m: _rank(m["source_id"],
                                                   HEADWORD_PRECEDENCE))
        return (best["headword"], best["member_key"],
                "derivation: the base carries a long vowel")

    pool = macronised or members
    reason = ("a source marking vowel length makes a claim; one omitting it "
              "may simply not mark it") if macronised else \
             "no member marks vowel length"
    best = min(pool, key=lambda m: _rank(m["source_id"], HEADWORD_PRECEDENCE))
    return (best["headword"], best["member_key"], reason)


def elect_gloss(members, lang):
    """(value, member_key) for 'en' or 'mi', or (None, None)."""
    if lang == "en":
        order, field = GLOSS_EN_PRECEDENCE, "gloss_en"
        pool = [m for m in members if m["source_id"] not in _NO_GLOSS_EN]
    else:
        order, field = GLOSS_MI_PRECEDENCE, "gloss_mi"
        pool = list(members)

    pool = [m for m in pool if (m.get(field) or "").strip()]
    if not pool:
        return (None, None)
    best = min(pool, key=lambda m: _rank(m["source_id"], order))
    return (best[field], best["member_key"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_election.py -q`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_election.py tests/test_concept_election.py
git commit -m "feat(concept): election, morphology before macron before precedence"
```

---

### Task 6: Reading the sense-views out of the DB

**Files:**
- Create: `scripts/54_build_concepts.py`
- Test: `tests/test_concept_build.py`

**Interfaces:**
- Consumes: `lexeme_key` (Task 2).
- Produces: `load_senses(con, keys=None) -> dict[str, list[dict]]` mapping `headword_search` to sense-views.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_build.py` (add `import importlib` at the top):

```python
def _fixture_db():
    """A miniature corpus: the hiwi cluster's shape, in three sources."""
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (id INTEGER PRIMARY KEY, source_id TEXT,
            source_entry_id TEXT, headword TEXT, headword_search TEXT,
            part_of_speech TEXT, locator TEXT);
        CREATE TABLE sense (id INTEGER PRIMARY KEY, entry_id INTEGER,
            sense_number INTEGER, gloss_en TEXT, gloss_mi TEXT,
            part_of_speech TEXT);
        CREATE TABLE example (id INTEGER PRIMARY KEY, entry_id INTEGER,
            sense_id INTEGER, text_mi TEXT, citation TEXT);
        CREATE TABLE relation (id INTEGER PRIMARY KEY, entry_id INTEGER,
            rel_type TEXT, target_entry_id INTEGER);
        CREATE TABLE ETY_entry_link (id INTEGER PRIMARY KEY, entry_id INTEGER,
            cognateset_id INTEGER, sense_id INTEGER);
    """)
    con.executescript(concept_ddl())
    con.executemany(
        "INSERT INTO entry (id, source_id, source_entry_id, headword, "
        "headword_search, part_of_speech, locator) VALUES (?,?,?,?,?,?,?)", [
            (1, "williams", "1251", "Hiwi", "hiwi", None, None),
            (2, "williams", "1250", "Hiwi", "hiwi", None, None),
            (3, "te_aka", "1284", "hiwi", "hiwi", "noun", None),
            (4, "papakupu", "442", "hiwi", "hiwi", "Noun", None),
        ])
    con.executemany(
        "INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
        "VALUES (?,?,?,?)", [
            (10, 1, 1, "Ridge of a hill."),
            (11, 1, 2, "Line of descent."),
            (12, 2, 1, "Jerk a fishing line so as to hook the fish."),
            (13, 3, 1, "ridge (of a hill)."),
            (14, 4, 1, "ridge of a hill"),
        ])
    con.commit()
    return con


class LoadSenses(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def test_senses_are_grouped_by_headword_key(self):
        views = self.mod.load_senses(_fixture_db())
        self.assertEqual(set(views), {"hiwi"})
        self.assertEqual(len(views["hiwi"]), 5)

    def test_a_view_carries_its_stable_address(self):
        views = self.mod.load_senses(_fixture_db())
        keys = {v["member_key"] for v in views["hiwi"]}
        self.assertIn(("williams", "1251", 1), keys)

    def test_williams_senses_of_one_entry_share_a_lexeme(self):
        views = {v["member_key"]: v for v in
                 self.mod.load_senses(_fixture_db())["hiwi"]}
        self.assertEqual(views[("williams", "1251", 1)]["lexeme"],
                         views[("williams", "1251", 2)]["lexeme"])

    def test_williams_separate_entries_do_not(self):
        views = {v["member_key"]: v for v in
                 self.mod.load_senses(_fixture_db())["hiwi"]}
        self.assertNotEqual(views[("williams", "1251", 1)]["lexeme"],
                            views[("williams", "1250", 1)]["lexeme"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named '54_build_concepts'`

- [ ] **Step 3: Write the implementation**

Create `scripts/54_build_concepts.py`:

```python
"""Build the concept layer: one word, as eleven dictionaries record it.

See docs/superpowers/specs/2026-09-12-concept-layer-design.md.

Single-source lexemes seed the concepts; cross-source witnesses attach one at
a time on direct evidence to the concept, never transitively. Membership is
keyed on (source_id, source_entry_id, sense_number) so it survives a rebuild,
and rows a human or the sweep has judged are never overwritten.

    py scripts/54_build_concepts.py            # dry run, print counts
    py scripts/54_build_concepts.py --write
"""
import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH
from concept_evidence import lexeme_key


def _norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def load_senses(con, keys=None):
    """{headword_search: [sense-view, ...]} — the universe to be grouped."""
    where, params = "", []
    if keys:
        where = " AND e.headword_search IN (%s)" % ",".join("?" * len(keys))
        params = list(keys)

    examples = defaultdict(set)
    citations = defaultdict(set)
    for sid, text_mi, cit in con.execute(
            "SELECT sense_id, text_mi, citation FROM example"):
        if sid is None:
            continue
        if text_mi and len(text_mi) > 25:
            examples[sid].add(_norm(text_mi))
        if cit:
            citations[sid].add(_norm(cit))

    cognates = defaultdict(set)
    for eid, cs in con.execute(
            "SELECT entry_id, cognateset_id FROM ETY_entry_link"):
        cognates[eid].add(cs)

    cites = defaultdict(set)
    for eid, target in con.execute(
            "SELECT entry_id, target_entry_id FROM relation "
            " WHERE target_entry_id IS NOT NULL"):
        cites[eid].add(target)

    out = defaultdict(list)
    sql = ("SELECT e.id, e.source_id, e.source_entry_id, e.headword, "
           "       e.headword_search, e.locator, e.part_of_speech, "
           "       s.id, s.sense_number, s.gloss_en, s.gloss_mi, "
           "       s.part_of_speech "
           "  FROM sense s JOIN entry e ON e.id = s.entry_id "
           " WHERE e.headword_search IS NOT NULL" + where)
    for (eid, src, seid, hw, hse, locator, epos,
         sid, sn, gen, gmi, spos) in con.execute(sql, params):
        out[hse].append({
            "member_key": (src, str(seid), sn),
            "source_id": src,
            "entry_id": eid,
            "sense_id": sid,
            "source_entry_id": str(seid),
            "sense_number": sn,
            "headword": hw,
            "headword_search": hse,
            "pos": spos or epos,
            "gloss_en": gen,
            "gloss_mi": gmi,
            "lexeme": lexeme_key(src, seid, hse, locator),
            "cognate_sets": frozenset(cognates.get(eid, ())),
            "examples": frozenset(examples.get(sid, ())),
            "citations": frozenset(citations.get(sid, ())),
            "cites": frozenset(cites.get(eid, ())),
        })
    return dict(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/54_build_concepts.py tests/test_concept_build.py
git commit -m "feat(concept): load sense-views with their stable addresses"
```

---

### Task 7: Seed and attach

**Files:**
- Modify: `scripts/54_build_concepts.py`
- Test: `tests/test_concept_build.py`

**Interfaces:**
- Consumes: `load_senses` (Task 6), `positive_evidence`/`blocks`/`confidence_for` (Tasks 3–4).
- Produces: `form_concepts(views) -> list[dict]` where each dict is `{"members": [...], "confidence": str}` and each member is `{"view": dict, "evidence": [...], "confidence": str}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_build.py`:

```python
class FormConcepts(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _concepts(self, con=None):
        views = self.mod.load_senses(con or _fixture_db())
        return self.mod.form_concepts(views["hiwi"])

    def test_williams_two_entries_never_share_a_concept(self):
        # Williams files 1250 and 1251 apart: that IS Williams saying these
        # are different words, and nothing may override it here.
        for c in self._concepts():
            entries = {m["view"]["source_entry_id"] for m in c["members"]
                       if m["view"]["source_id"] == "williams"}
            self.assertLessEqual(len(entries), 1, entries)

    def test_the_ridge_sources_come_together(self):
        concepts = self._concepts()
        ridge = [c for c in concepts
                 if any(m["view"]["member_key"] == ("williams", "1251", 1)
                        for m in c["members"])]
        self.assertEqual(len(ridge), 1)
        sources = {m["view"]["source_id"] for m in ridge[0]["members"]}
        self.assertEqual(sources, {"williams", "te_aka", "papakupu"})

    def test_the_jerk_sense_stays_on_its_own(self):
        concepts = self._concepts()
        jerk = [c for c in concepts
                if any(m["view"]["member_key"] == ("williams", "1250", 1)
                       for m in c["members"])]
        self.assertEqual(len(jerk), 1)
        self.assertEqual(len(jerk[0]["members"]), 1)

    def test_every_sense_lands_in_exactly_one_concept(self):
        views = self.mod.load_senses(_fixture_db())["hiwi"]
        concepts = self.mod.form_concepts(views)
        placed = [m["view"]["member_key"] for c in concepts for m in c["members"]]
        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(set(placed), {v["member_key"] for v in views})

    def test_a_membership_records_its_evidence(self):
        concepts = self._concepts()
        attached = [m for c in concepts for m in c["members"]
                    if m["view"]["source_id"] != "williams" and m["evidence"]]
        self.assertTrue(attached)
        self.assertIn("kind", attached[0]["evidence"][0])

    def test_attachment_is_not_transitive(self):
        # A and C are blocked from each other; B is compatible with both.
        # B may join one of them, but that must never place A with C.
        con = _fixture_db()
        con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword,"
                    " headword_search, part_of_speech) VALUES"
                    " (5,'taikupu','t1','hīwi','hiwi',NULL)")
        con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en)"
                    " VALUES (15,5,1,'ridge of a hill')")
        con.commit()
        for c in self.mod.form_concepts(self.mod.load_senses(con)["hiwi"]):
            hws = {m["view"]["headword"].lower() for m in c["members"]}
            self.assertFalse({"hiwi", "hīwi"} <= hws, hws)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: FAIL — `AttributeError: module '54_build_concepts' has no attribute 'form_concepts'`

- [ ] **Step 3: Write the implementation**

Add to `scripts/54_build_concepts.py` (extend the import to
`from concept_evidence import SEED_CONFIDENCE, blocks, confidence_for, lexeme_key, positive_evidence`):

```python
def _seed_groups(views):
    """Single-source lexemes, in a stable order — the concepts' starting points.

    Each source groups its own senses into words and that grouping is STATED,
    not inferred, which is why these are trusted where cross-source attachment
    is not.
    """
    groups = defaultdict(list)
    for v in views:
        groups[v["lexeme"]].append(v)
    return [groups[k] for k in sorted(groups, key=lambda k: (str(k),))]


def form_concepts(views):
    """Group one headword key's sense-views into concepts.

    Seeds attach to a concept only on positive evidence linking them to it, and
    only when no block holds against ANY existing member. That second clause is
    the anti-chaining rule: if two words are separated by their own source's
    numbering, no third source compatible with each can later join them.
    """
    concepts = []
    for seed in _seed_groups(views):
        placed = False
        for concept in concepts:
            existing = [m["view"] for m in concept["members"]]

            # A block against any current member rules the whole concept out.
            if any(blocks(s, e) for s in seed for e in existing):
                continue

            evidence = []
            for s in seed:
                for e in existing:
                    found = positive_evidence(s, e)
                    if found:
                        evidence.extend(found)
            if not evidence:
                continue

            seed_conf = min(
                (SEED_CONFIDENCE.get(s["source_id"], "certain") for s in seed),
                key=("uncertain", "probable", "certain").index)
            conf = confidence_for(evidence, [])
            conf = min((conf, seed_conf),
                       key=("uncertain", "probable", "certain").index)
            for s in seed:
                concept["members"].append(
                    {"view": s, "evidence": evidence, "confidence": conf})
            placed = True
            break

        if not placed:
            conf = min(
                (SEED_CONFIDENCE.get(s["source_id"], "certain") for s in seed),
                key=("uncertain", "probable", "certain").index)
            concepts.append({"members": [{"view": s, "evidence": [],
                                          "confidence": conf} for s in seed]})

    for c in concepts:
        c["confidence"] = min((m["confidence"] for m in c["members"]),
                              key=("uncertain", "probable", "certain").index)
    return concepts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/54_build_concepts.py tests/test_concept_build.py
git commit -m "feat(concept): seed and attach, with the anti-chaining rule"
```

---

### Task 8: Persist, preserving judgements

**Files:**
- Modify: `scripts/54_build_concepts.py`
- Test: `tests/test_concept_build.py`

**Interfaces:**
- Consumes: `form_concepts` (Task 7), `elect_headword`/`elect_gloss` (Task 5).
- Produces: `persist(con, concepts) -> dict` with counts; `run(write: bool)`; CLI `--write`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_build.py`:

```python
class Persist(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _build(self, con):
        views = self.mod.load_senses(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key]))
        return self.mod.persist(con, allc)

    def test_it_writes_concepts_members_and_evidence(self):
        con = _fixture_db()
        self._build(con)
        self.assertGreater(con.execute(
            "SELECT COUNT(*) FROM concept").fetchone()[0], 0)
        self.assertEqual(con.execute(
            "SELECT COUNT(*) FROM concept_member").fetchone()[0], 5)

    def test_it_elects_a_headword_some_member_wrote(self):
        con = _fixture_db()
        self._build(con)
        for hw, in con.execute(
                "SELECT headword FROM concept WHERE headword IS NOT NULL"):
            self.assertIn(hw, ("Hiwi", "hiwi"))

    def test_running_twice_does_not_duplicate(self):
        con = _fixture_db()
        self._build(con)
        first = con.execute("SELECT COUNT(*) FROM concept_member").fetchone()[0]
        self._build(con)
        self.assertEqual(con.execute(
            "SELECT COUNT(*) FROM concept_member").fetchone()[0], first)

    def test_a_confirmed_membership_is_never_overwritten(self):
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='confirmed', "
                    "confidence='certain' WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        row = con.execute("SELECT status, confidence FROM concept_member "
                          "WHERE source_id='papakupu'").fetchone()
        self.assertEqual(row, ("confirmed", "certain"))

    def test_a_rejected_membership_is_never_revived(self):
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='rejected' "
                    "WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE source_id='papakupu'"
        ).fetchone()[0], "rejected")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: FAIL — `AttributeError: module '54_build_concepts' has no attribute 'persist'`

- [ ] **Step 3: Write the implementation**

Add to `scripts/54_build_concepts.py` (extend imports with
`from concept_election import elect_gloss, elect_headword` and
`from datetime import datetime, timezone`):

```python
NOW = datetime.now(timezone.utc).isoformat()

_JUDGED = ("confirmed", "rejected")


def _derived_long(con):
    """Member keys whose word is formed on a base carrying a long vowel.

    derivation (D38) is attested word formation, so where it says hōmai is
    hō + mai the macron is settled by morphology rather than by a vote.
    """
    out = set()
    for src, seid, base in con.execute(
            "SELECT e.source_id, e.source_entry_id, d.base_form "
            "  FROM derivation d JOIN entry e ON e.id = d.entry_id"):
        if any(ch in "āēīōū" for ch in (base or "").lower()):
            out.add((src, str(seid)))
    return out


def persist(con, concepts):
    """Write concepts, preserving anything a human or the sweep has judged."""
    judged = {}
    for cid, src, seid, sn, status, conf in con.execute(
            "SELECT concept_id, source_id, source_entry_id, sense_number, "
            "       status, confidence FROM concept_member "
            " WHERE status IN (?,?)", _JUDGED):
        judged[(src, str(seid), sn)] = (cid, status, conf)

    con.execute("DELETE FROM concept_member_evidence")
    con.execute("DELETE FROM concept_member WHERE status NOT IN (?,?)", _JUDGED)

    long_bases = _derived_long(con)
    counts = {"concepts": 0, "members": 0, "kept": 0}

    for concept in concepts:
        members = [m for m in concept["members"]
                   if judged.get(m["view"]["member_key"], (None, None, None))[1]
                   != "rejected"]
        if not members:
            continue

        cur = con.execute(
            "INSERT INTO concept (status, confidence, created_at, last_updated)"
            " VALUES ('proposed', ?, ?, ?)", (concept["confidence"], NOW, NOW))
        concept_id = cur.lastrowid
        counts["concepts"] += 1

        member_ids = {}
        for m in members:
            v = m["view"]
            key = v["member_key"]
            if key in judged:
                counts["kept"] += 1
                con.execute(
                    "UPDATE concept_member SET concept_id=?, entry_id=?, "
                    " sense_id=? WHERE source_id=? AND source_entry_id=? "
                    " AND sense_number IS ?",
                    (concept_id, v["entry_id"], v["sense_id"],
                     key[0], key[1], key[2]))
                mid = con.execute(
                    "SELECT id FROM concept_member WHERE source_id=? AND "
                    " source_entry_id=? AND sense_number IS ?", key).fetchone()[0]
            else:
                mid = con.execute(
                    "INSERT INTO concept_member (concept_id, source_id, "
                    " source_entry_id, sense_number, entry_id, sense_id, "
                    " status, confidence, created_at) "
                    " VALUES (?,?,?,?,?,?, 'proposed', ?, ?)",
                    (concept_id, key[0], key[1], key[2], v["entry_id"],
                     v["sense_id"], m["confidence"], NOW)).lastrowid
                counts["members"] += 1
            member_ids[key] = mid
            for e in m["evidence"]:
                con.execute(
                    "INSERT INTO concept_member_evidence (member_id, kind, "
                    " detail, weight) VALUES (?,?,?,?)",
                    (mid, e["kind"], e["detail"], e["weight"]))

        views = [m["view"] for m in members]
        derived = any((v["source_id"], v["source_entry_id"]) in long_bases
                      for v in views)
        hw, hw_key, _reason = elect_headword(views, derived)
        gen, gen_key = elect_gloss(views, "en")
        gmi, gmi_key = elect_gloss(views, "mi")
        con.execute(
            "UPDATE concept SET headword=?, headword_from=?, gloss_en=?, "
            " gloss_en_from=?, gloss_mi=?, gloss_mi_from=?, last_updated=? "
            " WHERE id=?",
            (hw, member_ids.get(hw_key), gen, member_ids.get(gen_key),
             gmi, member_ids.get(gmi_key), NOW, concept_id))

    # Only now: a judged member still pointed at its OLD concept during the
    # loop above, so its concept could not be dropped before it was moved.
    con.execute("DELETE FROM concept_member_evidence WHERE member_id NOT IN "
                "(SELECT id FROM concept_member)")
    con.execute("DELETE FROM concept WHERE id NOT IN "
                "(SELECT concept_id FROM concept_member)")
    con.commit()
    return counts


def run(write: bool) -> None:
    con = sqlite3.connect(DB_PATH)
    views = load_senses(con)
    concepts = []
    for key in sorted(views):
        concepts.extend(form_concepts(views[key]))

    sizes = defaultdict(int)
    for c in concepts:
        sizes[len({m["view"]["source_id"] for m in c["members"]})] += 1
    print(f"concepts: {len(concepts):,}")
    for n in sorted(sizes):
        print(f"    spanning {n} source(s): {sizes[n]:,}")

    if not write:
        print("\n(dry run — pass --write to persist)")
        con.close()
        return
    print("\n" + repr(persist(con, concepts)))
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="persist to the DB")
    run(ap.parse_args().write)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py -q`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/54_build_concepts.py tests/test_concept_build.py
git commit -m "feat(concept): persist, never overwriting a judged membership"
```

---

### Task 9: Rebuild survival

**Files:**
- Modify: `scripts/50_build_unified.py` (in `delete_source_slice`)
- Test: `tests/test_concept_build.py`

**Interfaces:**
- Consumes: `concept_member` (Task 1).
- Produces: nothing new; changes `delete_source_slice` behaviour.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_build.py`:

```python
class RebuildSurvival(unittest.TestCase):
    """A membership is a judgement; a rebuild must not destroy it.

    derivation and loan_origin are pure projections and are deleted wholesale.
    concept_member is not: it holds what the sweep decided, and entry.id is
    only a cache of where that sense currently lives.
    """

    def test_the_slice_delete_nulls_the_cache_not_the_membership(self):
        con = _fixture_db()
        con.execute("INSERT INTO concept (id, status, confidence) "
                    "VALUES (1,'proposed','probable')")
        con.execute("INSERT INTO concept_member (concept_id, source_id, "
                    " source_entry_id, sense_number, entry_id, sense_id, "
                    " status, confidence) "
                    " VALUES (1,'williams','1251',1,1,10,'confirmed','certain')")
        con.commit()

        con.execute("UPDATE concept_member SET entry_id=NULL, sense_id=NULL "
                    " WHERE entry_id IN (SELECT id FROM entry "
                    "                     WHERE source_id='williams')")
        con.commit()

        row = con.execute("SELECT status, entry_id FROM concept_member "
                          "WHERE source_id='williams'").fetchone()
        self.assertEqual(row, ("confirmed", None))
```

- [ ] **Step 2: Run the test — note this one is NOT a RED step**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_build.py::RebuildSurvival -q`
Expected: PASS. It pins the SQL's intended behaviour on a fixture; it cannot
fail before the change because it runs the statement directly. The real
verification is Step 4, against the live rebuild.

- [ ] **Step 3: Wire it into the slice delete**

In `scripts/50_build_unified.py`, inside `delete_source_slice`, find the block added for D38 that begins:

```python
    # derivation and loan_origin are pure projections of the core, rebuilt in
```

Immediately **before** that block, insert:

```python
    # concept_member is NOT a projection: it holds sweep judgements. entry_id
    # and sense_id are only a cache of where the sense currently lives, so the
    # rebuild nulls the cache and 54_build_concepts re-resolves it from the
    # stable (source_id, source_entry_id, sense_number) address.
    try:
        con.execute(
            "UPDATE concept_member SET entry_id = NULL, sense_id = NULL "
            " WHERE entry_id IN (SELECT id FROM entry WHERE source_id = ?)",
            (source_id,))
    except sqlite3.OperationalError:
        pass            # table not present in an older DB
```

- [ ] **Step 4: Verify against the live DB**

```bash
PYTHONUTF8=1 py -m pytest tests/ -q
PYTHONUTF8=1 py scripts/50_build_unified.py --source temarareo 2>&1 | tail -3
PYTHONUTF8=1 py -c "
import sqlite3; c=sqlite3.connect('data/staging_dictionary.db')
print('members:', c.execute('select count(*) from concept_member').fetchone()[0])
print('judged preserved:', c.execute(\"select count(*) from concept_member where status in ('confirmed','rejected')\").fetchone()[0])
"
```
Expected: tests pass; the rebuild completes with no foreign-key error.

- [ ] **Step 5: Commit**

```bash
git add scripts/50_build_unified.py tests/test_concept_build.py
git commit -m "fix(concept): a rebuild nulls the id cache, never the membership"
```

---

### Task 10: First real build, and tuning the one parameter

**Files:**
- Modify: `scripts/concept_evidence.py` (`GLOSS_OVERLAP_MIN` only, if the measurement says so)
- Test: `tests/test_concept_acceptance.py`

**Interfaces:**
- Consumes: everything above.
- Produces: populated `concept*` tables in `data/staging_dictionary.db`.

- [ ] **Step 1: Write the failing acceptance test**

Create `tests/test_concept_acceptance.py`:

```python
"""The judged calibration clusters, as acceptance tests.

These are real answers, reasoned one cluster at a time during the sweep, so
they are the best check the machinery has. Each assertion names the finding it
came from.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _concepts_on(self, key):
        return self.con.execute(
            "SELECT DISTINCT cm.concept_id FROM concept_member cm "
            "  JOIN entry e ON e.source_id = cm.source_id "
            "   AND e.source_entry_id = cm.source_entry_id "
            " WHERE e.headword_search = ?", (key,)).fetchall()

    def test_hiwi_is_many_words_not_one(self):
        # 18 entries, eight distinct words plus two loans.
        self.assertGreaterEqual(len(self._concepts_on("hiwi")), 6)

    def test_hia_never_joins_hiia(self):
        # 'hīa' is hī + -a, 'draw a breath'; it shares a key only because
        # headword_search strips macrons.
        rows = self.con.execute(
            "SELECT cm.concept_id, e.headword FROM concept_member cm "
            "  JOIN entry e ON e.source_id = cm.source_id "
            "   AND e.source_entry_id = cm.source_entry_id "
            " WHERE e.headword_search = 'hia'").fetchall()
        by_concept = {}
        for cid, hw in rows:
            by_concept.setdefault(cid, set()).add(hw.lower())
        for cid, hws in by_concept.items():
            self.assertFalse({"hia", "hīa"} <= hws, f"concept {cid}: {hws}")

    def test_himoemoe_unifies_its_sources(self):
        # Six sources, one word, no disagreement anywhere.
        counts = self.con.execute(
            "SELECT cm.concept_id, COUNT(DISTINCT cm.source_id) FROM concept_member cm"
            "  JOIN entry e ON e.source_id = cm.source_id "
            "   AND e.source_entry_id = cm.source_entry_id "
            " WHERE e.headword_search = 'himoemoe' GROUP BY 1").fetchall()
        self.assertTrue(any(n >= 4 for _cid, n in counts), counts)

    def test_paekupu_soy_is_not_an_ear_lobe(self):
        # paekupu:hoi 'soy, soya' is a loan and genuinely its own word.
        cid = self.con.execute(
            "SELECT concept_id FROM concept_member "
            " WHERE source_id='paekupu' AND source_entry_id='hoi'").fetchone()
        self.assertIsNotNone(cid)
        sources = self.con.execute(
            "SELECT COUNT(DISTINCT source_id) FROM concept_member "
            " WHERE concept_id = ?", cid).fetchone()[0]
        self.assertEqual(sources, 1)


class Invariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql):
        return self.con.execute(sql).fetchone()[0]

    def test_no_sense_is_in_two_concepts(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM (SELECT source_id, source_entry_id, "
            " sense_number FROM concept_member GROUP BY 1,2,3 HAVING COUNT(*)>1)"), 0)

    def test_an_elected_headword_was_written_by_a_member(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM concept c WHERE c.headword IS NOT NULL AND "
            " NOT EXISTS (SELECT 1 FROM concept_member cm "
            "   JOIN entry e ON e.source_id=cm.source_id "
            "    AND e.source_entry_id=cm.source_entry_id "
            "  WHERE cm.concept_id=c.id AND e.headword=c.headword)"), 0)

    def test_no_concept_holds_two_senses_from_different_williams_entries(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM (SELECT concept_id FROM concept_member "
            " WHERE source_id='williams' GROUP BY concept_id "
            " HAVING COUNT(DISTINCT source_entry_id) > 1)"), 0)

    def test_ngata_never_supplied_an_english_gloss(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM concept c JOIN concept_member m "
            "  ON m.id = c.gloss_en_from WHERE m.source_id = 'ngata'"), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the build and the tests**

```bash
PYTHONUTF8=1 py scripts/54_build_concepts.py
PYTHONUTF8=1 py scripts/54_build_concepts.py --write
PYTHONUTF8=1 py -m pytest tests/test_concept_acceptance.py -q
```
Expected: the dry run prints a concept count and a spread by source; the acceptance tests then pass or point at a specific cluster.

- [ ] **Step 3: Tune `GLOSS_OVERLAP_MIN` only if an acceptance test fails**

If `test_hiwi_is_many_words_not_one` fails, the threshold is too loose — raise `GLOSS_OVERLAP_MIN` in `scripts/concept_evidence.py` by one and rebuild. If `test_himoemoe_unifies_its_sources` fails, it is too tight — lower it by one. Record the final value and the reason in the constant's comment. Do not change any other rule to make a test pass.

- [ ] **Step 4: Re-run the whole suite**

Run: `PYTHONUTF8=1 py -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/concept_evidence.py tests/test_concept_acceptance.py
git commit -m "test(concept): the judged calibration clusters as acceptance tests"
```

---

### Task 11: Show concepts in the sweep batch

**Files:**
- Modify: `scripts/sweep_batch.py`
- Test: `tests/test_sweep_batch.py`

**Interfaces:**
- Consumes: `concept`, `concept_member`, `concept_member_evidence`.
- Produces: `assemble()` gains a `"concepts"` key; `render()` emits a CONCEPTS section.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sweep_batch.py`:

```python
class ConceptsInTheBatch(unittest.TestCase):
    """The sweep judges memberships, which is a far better unit than a cluster.

    A membership is a specific claim with a reason, answerable yes or no; a
    headword cluster is eighteen entries and eight words.
    """

    def test_the_batch_carries_the_clusters_concepts(self):
        con = _batch_fixture()          # existing helper in this file
        batch = assemble(con, "hiwi")
        self.assertIn("concepts", batch)

    def test_a_concept_lists_its_members_and_their_evidence(self):
        con = _batch_fixture()
        batch = assemble(con, "hiwi")
        if not batch["concepts"]:
            self.skipTest("fixture has no concepts")
        c = batch["concepts"][0]
        self.assertIn("members", c)
        self.assertIn("evidence", c["members"][0])

    def test_the_render_has_a_concepts_section(self):
        con = _batch_fixture()
        text = render(assemble(con, "hiwi"))
        self.assertIn("CONCEPTS", text)
```

`_batch_fixture` is a placeholder for the fixture helper that file already
uses. Before writing these tests run `grep -n "^def \|^    def setUp" tests/test_sweep_batch.py`
and substitute the real name; do not add a second fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_sweep_batch.py -q`
Expected: FAIL — `KeyError: 'concepts'`

- [ ] **Step 3: Write the implementation**

In `scripts/sweep_batch.py`, inside `assemble`, before the return, add:

```python
    batch["concepts"] = _concepts_for(con, cluster_key)
```

and add the helper plus a render section:

```python
def _concepts_for(con, cluster_key):
    """The proposed concepts covering this cluster, with their evidence."""
    rows = con.execute(
        "SELECT DISTINCT cm.concept_id FROM concept_member cm "
        "  JOIN entry e ON e.source_id = cm.source_id "
        "   AND e.source_entry_id = cm.source_entry_id "
        " WHERE e.headword_search = ? ORDER BY cm.concept_id",
        (cluster_key,)).fetchall()
    out = []
    for (cid,) in rows:
        c = con.execute(
            "SELECT status, confidence, headword, gloss_en, gloss_mi "
            "  FROM concept WHERE id = ?", (cid,)).fetchone()
        members = []
        for mid, src, seid, sn, status, conf in con.execute(
                "SELECT id, source_id, source_entry_id, sense_number, status, "
                "       confidence FROM concept_member WHERE concept_id = ? "
                " ORDER BY source_id, source_entry_id", (cid,)):
            evidence = [dict(zip(("kind", "detail"), r)) for r in con.execute(
                "SELECT kind, detail FROM concept_member_evidence "
                " WHERE member_id = ?", (mid,))]
            members.append({"address": f"{src}:{seid}"
                                       + (f"#{sn}" if sn else ""),
                            "status": status, "confidence": conf,
                            "evidence": evidence})
        out.append({"id": cid, "status": c[0], "confidence": c[1],
                    "headword": c[2], "gloss_en": c[3], "gloss_mi": c[4],
                    "members": members})
    return out
```

In `render`, before the ETYMOLOGY section, add:

```python
    if batch.get("concepts"):
        lines.append("")
        lines.append("── CONCEPTS ─────────────────────────────────────────")
        lines.append("   (proposed groupings. Confirm or reject a MEMBERSHIP;")
        lines.append("    same headword alone is never evidence.)")
        for c in batch["concepts"]:
            lines.append(f"   concept {c['id']}  [{c['status']}/{c['confidence']}]"
                         f"  {c['headword']!r}")
            if c["gloss_en"]:
                lines.append(f"       en {c['gloss_en'][:70]!r}")
            for m in c["members"]:
                lines.append(f"       {m['address']:<34} "
                             f"{m['status']}/{m['confidence']}")
                for e in m["evidence"]:
                    lines.append(f"           {e['kind']}: {e['detail'][:60]}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_sweep_batch.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/sweep_batch.py tests/test_sweep_batch.py
git commit -m "feat(sweep): show a cluster's proposed concepts and their evidence"
```

---

### Task 12: Record concept decisions

**Files:**
- Modify: `scripts/sweep_runner.py`
- Test: `tests/test_sweep_runner.py`

**Interfaces:**
- Consumes: findings payload.
- Produces: `concept_actions` accepted inside a finding — `{"action": "confirm_member"|"reject_member", "member": "source:entry#sense"}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sweep_runner.py`:

```python
class ConceptActions(unittest.TestCase):
    """Concept decisions nest inside findings, exactly as patches do: a
    membership cannot change without a recorded reason."""

    def test_a_confirm_marks_the_membership(self):
        con = _runner_fixture()   # substitute this file's real fixture helper;
        # find it with: grep -n "^def " tests/test_sweep_runner.py
        con.execute("INSERT INTO concept (id, status, confidence) "
                    "VALUES (1,'proposed','probable')")
        con.execute("INSERT INTO concept_member (id, concept_id, source_id, "
                    " source_entry_id, sense_number, status, confidence) "
                    " VALUES (1,1,'williams','1251',1,'proposed','probable')")
        con.commit()
        record(con, "s1", {"cluster_key": "hiwi", "findings": [{
            "kind": "duplicate", "subject": "williams:1251#1",
            "summary": "same word as te_aka:1284", "action": "applied",
            "concept_actions": [{"action": "confirm_member",
                                 "member": "williams:1251#1"}]}]})
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE id=1").fetchone()[0],
            "confirmed")

    def test_an_unknown_action_is_refused(self):
        con = _runner_fixture()
        with self.assertRaises(ValueError):
            record(con, "s1", {"cluster_key": "hiwi", "findings": [{
                "kind": "duplicate", "subject": "x", "summary": "y",
                "concept_actions": [{"action": "explode", "member": "a:1#1"}]}]})

    def test_an_unknown_member_is_refused(self):
        con = _runner_fixture()
        with self.assertRaises(ValueError):
            record(con, "s1", {"cluster_key": "hiwi", "findings": [{
                "kind": "duplicate", "subject": "x", "summary": "y",
                "concept_actions": [{"action": "confirm_member",
                                     "member": "nosuch:9#9"}]}]})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_sweep_runner.py -q`
Expected: FAIL — the membership stays `proposed`.

- [ ] **Step 3: Write the implementation**

In `scripts/sweep_runner.py`, add to `_validate` inside the per-finding loop:

```python
        for j, a in enumerate(f.get("concept_actions") or []):
            at = f"{where}.concept_actions[{j}]"
            if a.get("action") not in CONCEPT_ACTIONS:
                raise ValueError(f"{at}: unknown action {a.get('action')!r}")
            if not (a.get("member") or "").strip():
                raise ValueError(f"{at}: member is required")
```

Add near `ACTIONS`:

```python
# A membership is a judgement, so it changes only through a recorded finding.
# The spec also lists split and merge. They are deliberately NOT here: both are
# expressible as confirm/reject on the memberships involved, and a first-class
# split needs a rule for which concept keeps the id that nothing yet depends on.
CONCEPT_ACTIONS = {"confirm_member", "reject_member"}
_MEMBER_RE = re.compile(r"^([^:]+):([^#]+)(?:#(\d+))?$")
```

Add a helper and call it from `record` where patches are applied:

```python
def _apply_concept_actions(con, finding):
    """Mark a membership confirmed or rejected. Raises if it does not exist."""
    for a in finding.get("concept_actions") or []:
        m = _MEMBER_RE.match(a["member"].strip())
        if not m:
            raise ValueError(f"unparseable member {a['member']!r}")
        src, seid, sn = m.group(1), m.group(2), m.group(3)
        sn = int(sn) if sn else None
        status = ("confirmed" if a["action"] == "confirm_member"
                  else "rejected")
        cur = con.execute(
            "UPDATE concept_member SET status = ? WHERE source_id = ? "
            "  AND source_entry_id = ? AND sense_number IS ?",
            (status, src, seid, sn))
        if cur.rowcount == 0:
            raise ValueError(f"no concept membership for {a['member']!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_sweep_runner.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/sweep_runner.py tests/test_sweep_runner.py
git commit -m "feat(sweep): confirm or reject a membership through a finding"
```

---

### Task 13: Export to the app at the confidence threshold

**Files:**
- Modify: `scripts/60_export_app_db.py`
- Test: `tests/test_concept_acceptance.py`

**Interfaces:**
- Consumes: `concept`, `concept_member`.
- Produces: both tables in `data/maori_dict.db`, filtered.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_concept_acceptance.py`:

```python
class AppExport(unittest.TestCase):
    """An uncertain grouping must not reach users, even by accident."""

    APP = Path(__file__).parent.parent / "data" / "maori_dict.db"

    def test_the_app_has_the_concept_tables(self):
        if not self.APP.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(self.APP)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertTrue({"concept", "concept_member"} <= names)

    def test_no_uncertain_concept_reaches_the_app(self):
        if not self.APP.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(self.APP)
        n = con.execute(
            "SELECT COUNT(*) FROM concept "
            " WHERE confidence = 'uncertain' AND status <> 'confirmed'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(n, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m pytest tests/test_concept_acceptance.py -q`
Expected: FAIL — the app DB has no `concept` table.

- [ ] **Step 3: Write the implementation**

In `scripts/60_export_app_db.py`, extend `APP_TABLES` after `"loan_origin",`:

```python
    # Concepts: one word as eleven dictionaries record it. Filtered below —
    # an uncertain grouping must not reach users even by accident. The
    # evidence table stays in staging; it is sweep-facing detail.
    "concept",
    "concept_member",
```

After the copy loop, add the filter:

```python
    app.execute(
        "DELETE FROM concept WHERE confidence = 'uncertain' "
        "  AND status <> 'confirmed'")
    app.execute(
        "DELETE FROM concept_member WHERE concept_id NOT IN "
        "  (SELECT id FROM concept)")
    app.commit()
```

- [ ] **Step 4: Run it and verify**

```bash
PYTHONUTF8=1 py scripts/60_export_app_db.py 2>&1 | tail -3
PYTHONUTF8=1 py -m pytest tests/test_concept_acceptance.py -q
```
Expected: `integrity_check: ok`, `foreign_key_check: clean`, tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/60_export_app_db.py tests/test_concept_acceptance.py
git commit -m "feat(concept): export to the app, uncertain groupings withheld"
```

---

### Task 14: The rebuild chain, and pruning the dead queue keys

**Files:**
- Create: `scripts/59_rebuild_derived.py`
- Test: `tests/test_source_field_coverage.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `py scripts/59_rebuild_derived.py` runs `52 → 08b → 53 → 54 → 60`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_source_field_coverage.py`:

```python
class AppDbIsNotStale(unittest.TestCase):
    """The derived chain has been got wrong twice by hand. Assert the result.

    52 -> 08b -> 53 -> 54 -> 60, and skipping any step leaves the app DB
    disagreeing with staging in a way no other test catches.
    """

    APP = Path(__file__).parent.parent / "data" / "maori_dict.db"

    def test_the_app_entry_count_matches_staging(self):
        if not self.APP.exists():
            self.skipTest("app DB not built")
        stg = sqlite3.connect(DB_PATH)
        app = sqlite3.connect(self.APP)
        for table in ("entry", "sense", "relation"):
            with self.subTest(table=table):
                self.assertEqual(
                    app.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    stg.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                    f"{table}: app DB is stale — run 59_rebuild_derived.py")
        stg.close()
        app.close()
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `PYTHONUTF8=1 py -m pytest tests/test_source_field_coverage.py -q`
Expected: PASS if the chain is currently complete; FAIL naming the stale table otherwise. Either outcome is informative — the test's value is that it fails when someone skips a step.

- [ ] **Step 3: Write the orchestrator**

Create `scripts/59_rebuild_derived.py`:

```python
"""Rebuild everything derived from the unified core, in dependency order.

50_build_unified rewrites a source's slice and clears the entry-link tables.
Five things must then run, in this order, and skipping one leaves the app DB
quietly disagreeing with staging:

    52_build_etymology_unified --reset   ETY_* from the raw etymology sources
    08b_pollex_entry_linker --write --reset   POLLEX -> entry bridge
    53_build_word_origin --write         derivation + loan_origin
    54_build_concepts --write            concepts
    60_export_app_db                     the app projection

    py scripts/59_rebuild_derived.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SCRIPTS = Path(__file__).parent

STEPS = [
    ("52_build_etymology_unified.py", ["--reset"]),
    ("08b_pollex_entry_linker.py", ["--write", "--reset"]),
    ("53_build_word_origin.py", ["--write"]),
    ("54_build_concepts.py", ["--write"]),
    ("60_export_app_db.py", []),
]


def main() -> int:
    for name, args in STEPS:
        print(f"\n=== {name} {' '.join(args)} ".ljust(70, "="))
        result = subprocess.run([sys.executable, str(SCRIPTS / name), *args])
        if result.returncode != 0:
            print(f"\nFAILED at {name} — later steps not run.", file=sys.stderr)
            return result.returncode
    print("\nAll derived tables rebuilt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run it end to end**

```bash
PYTHONUTF8=1 py scripts/59_rebuild_derived.py 2>&1 | tail -20
PYTHONUTF8=1 py -m pytest tests/ -q
```
Expected: every step reports success; the full suite passes.

- [ ] **Step 5: Prune the 62 dead queue keys**

They are D31's truncated Ngata fragments, queued before D31 removed the
entries that produced them.

```bash
PYTHONUTF8=1 py -c "
import sqlite3; c=sqlite3.connect('data/staging_dictionary.db')
n=c.execute('''DELETE FROM sweep_cluster WHERE status='pending' AND NOT EXISTS
   (SELECT 1 FROM entry e WHERE e.headword_search = sweep_cluster.cluster_key)''').rowcount
c.commit(); print('pruned', n, 'dead cluster keys')
"
```
Expected: `pruned 62 dead cluster keys`

- [ ] **Step 6: Commit**

```bash
git add scripts/59_rebuild_derived.py tests/test_source_field_coverage.py
git commit -m "chore: one command for the derived rebuild chain, and a staleness test"
```

---

## Done when

- `py scripts/59_rebuild_derived.py` rebuilds everything in one command.
- `concept` and `concept_member` are populated, exported, and the acceptance
  tests from the judged calibration clusters pass.
- A sweep batch shows the cluster's proposed concepts, and a finding can
  confirm or reject a membership.
- The full suite passes.
