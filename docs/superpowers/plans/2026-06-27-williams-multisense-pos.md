# Williams Multi-Sense Split + Sense-Level POS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Williams definitions into per-sense `sense` rows with per-sense raw POS, and roll each entry's senses' POS up into canonical English + Māori sets on the entry.

**Architecture:** All work happens in the unify projection layer (`scripts/50_build_unified.py`) reading the untouched `williams_entries` landing zone. A new pure module parses the raw definition into senses. Schema gains `sense.part_of_speech` + `entry.part_of_speech_en`/`part_of_speech_mi`. `std_pos` supplies canonical labels. The slim app DB picks the new columns up automatically on export.

**Tech Stack:** Python 3.12 (stdlib `sqlite3`, `re`, `unittest`), SQLite 3 (FTS5).

## Global Constraints

- Two DBs: build into `data/staging_dictionary.db`; export the app DB with `py scripts/60_export_app_db.py`. Never hand-edit `data/maori_dict.db`.
- Run from repo root; set `PYTHONUTF8=1` (macrons/IPA in output).
- **Repo is NOT git-initialized.** Replace every "Commit" step with a checkpoint: run the named tests green, then `cp data/staging_dictionary.db data/staging_dictionary.db.bak-<step>`. No `git` commands.
- `canonical_mi` only from Paekupu `pos_mi` where it matches (Title-cased); otherwise NULL. Invent no Māori terms.
- POS carry-over rule (Williams): a sense with no explicit POS inherits the previous sense's POS; sense 1 with none → NULL.
- Closed Williams POS-abbrev set: `n. a. v. v.t. v.i. ad. pt. pl. pos. int. num. pron. def. indef. prefix. l.n.` (`pass.`, `fig.` are register, NOT POS).

---

### Task 1: Schema — add POS columns + idempotent migration

**Files:**
- Modify: `scripts/00_init_db.py` (the `entry` and `sense` `CREATE TABLE` blocks; add a migration helper called from `main()`)
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `sense.part_of_speech TEXT`, `entry.part_of_speech_en TEXT`, `entry.part_of_speech_mi TEXT` on `data/staging_dictionary.db`. `entry.part_of_speech` retained (raw set).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py  (add)
def test_pos_columns_exist():
    with sqlite3.connect(DB_PATH) as conn:
        sense_cols = {r[1] for r in conn.execute("PRAGMA table_info(sense)")}
        entry_cols = {r[1] for r in conn.execute("PRAGMA table_info(entry)")}
    assert "part_of_speech" in sense_cols
    assert "part_of_speech_en" in entry_cols
    assert "part_of_speech_mi" in entry_cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_schema.test_pos_columns_exist -v`
Expected: FAIL (`assert ... in sense_cols` → columns absent).

- [ ] **Step 3: Add columns to the CREATE blocks + migration helper**

In the `sense` `CREATE TABLE` add `part_of_speech TEXT,` (before the trailing constraints).
In the `entry` `CREATE TABLE` add `part_of_speech_en TEXT,` and `part_of_speech_mi TEXT,`.
Add this helper and call it inside `main()` after the `executescript` that creates tables, on the open `conn`:

```python
def _add_column(conn, table, col, decl):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

def migrate_pos_columns(conn):
    _add_column(conn, "sense", "part_of_speech", "TEXT")
    _add_column(conn, "entry", "part_of_speech_en", "TEXT")
    _add_column(conn, "entry", "part_of_speech_mi", "TEXT")
```

- [ ] **Step 4: Run init then the test**

Run: `PYTHONUTF8=1 py scripts/00_init_db.py && PYTHONUTF8=1 py -m unittest tests.test_schema.test_pos_columns_exist -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint** — run `tests/test_schema.py` green; `cp data/staging_dictionary.db data/staging_dictionary.db.bak-task1`.

---

### Task 2: Seed `std_pos` with the Williams abbrevs

**Files:**
- Create: `scripts/14_seed_williams_pos.py`
- Test: `tests/test_williams_pos_seed.py`

**Interfaces:**
- Consumes: `std_pos(raw_pos, canonical_en, canonical_mi, status)` in `data/staging_dictionary.db`.
- Produces: rows so every abbrev in the closed set resolves to a `canonical_en`; `ad.`→`canonical_mi='Tūkē'`, `l.n.`→`Tūwāhi`; others mi NULL.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_williams_pos_seed.py
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from utils import DB_PATH

EXPECT = {
    "l.n.": ("Locative", "Tūwāhi"),
    "ad.":  ("Adverb", "Tūkē"),
    "pt.":  ("Particle", None),
    "pos.": ("Determiner (possessive)", None),
    "def.": ("Determiner (definite)", None),
    "indef.": ("Determiner (indefinite)", None),
    "prefix.": ("Prefix", None),
    "num.": ("Numeral", None),
}

def test_williams_abbrevs_mapped():
    with sqlite3.connect(DB_PATH) as conn:
        for raw, (en, mi) in EXPECT.items():
            row = conn.execute(
                "SELECT canonical_en, canonical_mi FROM std_pos WHERE raw_pos=?", (raw,)
            ).fetchone()
            assert row is not None, f"{raw} missing"
            assert row[0] == en, f"{raw} en {row[0]!r}!={en!r}"
            assert row[1] == mi, f"{raw} mi {row[1]!r}!={mi!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_williams_pos_seed -v`
Expected: FAIL (`pt.`/`pos.`/`def.`/`indef.`/`prefix.` missing; `ad.` mi is NULL not `Tūkē`; `num.` has no canonical).

- [ ] **Step 3: Write the seeding script**

```python
# scripts/14_seed_williams_pos.py
"""Seed/patch std_pos canonical labels for the Williams inline POS abbreviations.
canonical_mi only where Paekupu pos_mi matches (Title-cased); else NULL. Idempotent."""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

sys.stdout.reconfigure(encoding="utf-8")

# raw -> (canonical_en, canonical_mi)
SEED = {
    "l.n.":    ("Locative", "Tūwāhi"),
    "ad.":     ("Adverb", "Tūkē"),
    "pt.":     ("Particle", None),
    "pos.":    ("Determiner (possessive)", None),
    "def.":    ("Determiner (definite)", None),
    "indef.":  ("Determiner (indefinite)", None),
    "prefix.": ("Prefix", None),
    "num.":    ("Numeral", None),
}

def seed(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        for raw, (en, mi) in SEED.items():
            exists = conn.execute("SELECT 1 FROM std_pos WHERE raw_pos=?", (raw,)).fetchone()
            if exists:
                conn.execute(
                    "UPDATE std_pos SET canonical_en=?, canonical_mi=?, status='seeded' WHERE raw_pos=?",
                    (en, mi, raw),
                )
            else:
                conn.execute(
                    "INSERT INTO std_pos (raw_pos, source_counts, total_count, is_loan, "
                    "canonical_en, canonical_mi, status, notes) "
                    "VALUES (?, '{}', 0, 0, ?, ?, 'seeded', 'williams inline abbrev')",
                    (raw, en, mi),
                )
        conn.commit()
    print(f"Seeded {len(SEED)} Williams POS abbreviations.")

if __name__ == "__main__":
    seed()
```

- [ ] **Step 4: Run the seeder then the test**

Run: `PYTHONUTF8=1 py scripts/14_seed_williams_pos.py && PYTHONUTF8=1 py -m unittest tests.test_williams_pos_seed -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint** — test green; `cp data/staging_dictionary.db data/staging_dictionary.db.bak-task2`.

---

### Task 3: `williams_senses.split_senses` (pure parser) + unit tests

**Files:**
- Create: `scripts/williams_senses.py`
- Test: `tests/test_williams_senses.py`

**Interfaces:**
- Produces: `split_senses(definition: str) -> list[dict]`, each dict
  `{"sense_number": int, "part_of_speech": str|None, "gloss_en": str, "definition_raw": str}`.
  Consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_williams_senses.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from williams_senses import split_senses

PAE = ("1. n. Horizon. Ano ko Kopu ka puta ake i te pae (Tregear's Maori-Polynesian "
       "Comparative Dictionary 99). 2. Region, direction. Kei whea te pae? (Tregear 136). "
       "3. Horizontal ridges of hills. Haere koe (Tregear 95).")

def test_pae_three_senses_with_carryover():
    s = split_senses(PAE)
    assert [x["sense_number"] for x in s] == [1, 2, 3]
    assert s[0]["part_of_speech"] == "n."
    assert s[1]["part_of_speech"] == "n."   # carry-over
    assert s[2]["part_of_speech"] == "n."   # carry-over
    assert s[0]["gloss_en"].startswith("Horizon")
    assert "Region, direction" in s[1]["gloss_en"]

def test_vi_then_carryover():
    d = "1. v.i. Flow. Tena te wai. 2. Fly. Pekapeka rere. 3. Sail. Rere noa."
    s = split_senses(d)
    assert [x["part_of_speech"] for x in s] == ["v.i.", "v.i.", "v.i."]

def test_citation_page_number_not_split():
    # "99)." then no real sense 2 -> single sense
    d = "n. Horizon. Ano ko Kopu (Tregear's Comparative Dictionary 99)."
    s = split_senses(d)
    assert len(s) == 1
    assert s[0]["sense_number"] == 1
    assert s[0]["part_of_speech"] == "n."

def test_single_sense_leading_pos():
    s = split_senses("v.t. Carry. He mea kawe.")
    assert len(s) == 1
    assert s[0]["part_of_speech"] == "v.t."
    assert s[0]["gloss_en"].startswith("Carry")

def test_no_pos_is_none():
    s = split_senses("Thing of unknown class.")
    assert len(s) == 1
    assert s[0]["part_of_speech"] is None

def test_definition_raw_preserved():
    s = split_senses(PAE)
    assert "Tregear" in s[0]["definition_raw"]  # citations kept in raw
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_williams_senses -v`
Expected: FAIL with `ModuleNotFoundError: williams_senses`.

- [ ] **Step 3: Write the parser**

```python
# scripts/williams_senses.py
"""Split a Williams raw definition into per-sense dicts with per-sense POS.

Pure string -> list[dict]; no DB. Williams packs all senses into one definition,
numbered inline ("1. n. ... 2. ... 3. v.i. ...") with POS stated once and carried
over until it changes. See docs/superpowers/specs/2026-06-27-williams-multisense-pos-design.md
"""
import re

# Closed Williams POS-abbrev set. pass./fig. are register, NOT POS -> excluded.
POS_ABBREVS = [
    "def.art.", "v.t.", "v.i.", "l.n.", "ad.", "pt.", "pl.", "pos.", "int.",
    "num.", "pron.", "def.", "indef.", "prefix.", "conj.", "prep.", "interj.",
    "n.", "a.", "v.",
]
_POS_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in sorted(POS_ABBREVS, key=len, reverse=True)) + r")\s"
)
_MARKER_RE = re.compile(r"(?:^|[.)]\s)(\d+)\.\s")
_LEAD_MARKER_RE = re.compile(r"^\s*\d+\.\s")


def _sense_spans(text):
    """(content_start, marker_start) list for the longest strict 1,2,3,… run; [] if <2."""
    spans, expected = [], 1
    for m in _MARKER_RE.finditer(text):
        if int(m.group(1)) == expected:
            spans.append((m.end(), m.start()))
            expected += 1
    return spans if len(spans) >= 2 else []


def _split_pos(chunk):
    """Return (pos|None, gloss) by peeling an optional leading POS abbrev."""
    m = _POS_RE.match(chunk)
    if m:
        return m.group(1), chunk[m.end():].strip()
    return None, chunk.strip()


def split_senses(definition):
    if not definition:
        return []
    text = definition.strip()
    spans = _sense_spans(text)

    if not spans:
        chunk = _LEAD_MARKER_RE.sub("", text, count=1).strip()
        pos, gloss = _split_pos(chunk)
        return [{"sense_number": 1, "part_of_speech": pos,
                 "gloss_en": gloss, "definition_raw": chunk}]

    # content runs from each sense's content_start to the next marker_start
    content_starts = [cs for cs, _ in spans]
    next_marker = [ms for _, ms in spans][1:] + [len(text)]
    out, prev_pos = [], None
    for i, cs in enumerate(content_starts):
        chunk = text[cs:next_marker[i]].strip()
        pos, gloss = _split_pos(chunk)
        if pos is None:
            pos = prev_pos           # carry-over
        prev_pos = pos
        out.append({"sense_number": i + 1, "part_of_speech": pos,
                    "gloss_en": gloss, "definition_raw": chunk})
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONUTF8=1 py -m unittest tests.test_williams_senses -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Checkpoint** — tests green (no DB change this task).

---

### Task 4: Wire `split_senses` into `build_williams` + `add_sense` POS param

**Files:**
- Modify: `scripts/50_build_unified.py` (`add_sense` method; `build_williams` ~line 154–167; add import)
- Test: `tests/test_unified.py`

**Interfaces:**
- Consumes: `split_senses` (Task 3); `sense.part_of_speech` column (Task 1).
- Produces: multiple `sense` rows per multi-sense Williams entry with `part_of_speech` set.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_unified.py  (add)
def test_williams_multisense_split():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT s.sense_number, s.part_of_speech FROM entry e JOIN sense s ON s.entry_id=e.id "
        "WHERE e.source_id='williams' AND e.headword_search=? ORDER BY s.sense_number",
        ("pae",)
    ).fetchall()
    conn.close()
    nums = [r[0] for r in rows]
    assert len(nums) >= 3, f"expected multi-sense, got {nums}"
    assert nums == list(range(1, len(nums) + 1))   # sequential
    assert rows[0][1] is not None                   # POS populated
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_unified.test_williams_multisense_split -v`
Expected: FAIL (currently 1 sense for `pae`; `len(nums) >= 3`).

- [ ] **Step 3: Update `add_sense` and `build_williams`**

Add the import near the top of `scripts/50_build_unified.py` (alongside the other `from … import`):

```python
from williams_senses import split_senses
```

Give `add_sense` a `part_of_speech` keyword and write the column (keep existing callers working — only the new keyword is added; match the method's current column list and append `part_of_speech`):

```python
    def add_sense(self, entry_id, sense_number, gloss_en, gloss_mi, definition_raw,
                  part_of_speech=None, parent_sense_id=None, register=None):
        cur = self.con.execute(
            "INSERT INTO sense (entry_id, sense_number, parent_sense_id, gloss_en, "
            "gloss_mi, definition_raw, register, part_of_speech) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (entry_id, sense_number, parent_sense_id, gloss_en, gloss_mi,
             definition_raw, register, part_of_speech),
        )
        self.counts["sense"] += 1
        return cur.lastrowid
```

In `build_williams`, replace the single-sense block (the `sid = b.add_sense(...)` line and its
example loop) with:

```python
        senses = split_senses(d) or [{"sense_number": 1, "part_of_speech": None,
                                      "gloss_en": d, "definition_raw": d}]
        first_sid = None
        for s in senses:
            sid = b.add_sense(eid, s["sense_number"], s["gloss_en"], None,
                              s["definition_raw"], part_of_speech=s["part_of_speech"])
            if first_sid is None:
                first_sid = sid
        for i, ex in enumerate(examples):
            b.add_example(first_sid, eid, ex, None, None, None, i)   # examples -> sense 1
```

Leave the existing `add_entry(...)` call and the relation/cross_ref (`xr`) loop in
`build_williams` exactly as they are; entry POS is set centrally in Task 5.

- [ ] **Step 4: Re-unify williams and run the test**

Run: `PYTHONUTF8=1 py scripts/50_build_unified.py --source williams && PYTHONUTF8=1 py -m unittest tests.test_unified.test_williams_multisense_split -v`
Expected: PASS; console shows williams sense count > 11,910.

- [ ] **Step 5: Checkpoint** — `tests/test_williams_senses.py` + `tests/test_unified.py` green; `cp data/staging_dictionary.db data/staging_dictionary.db.bak-task4`.

---

### Task 5: Entry POS wrap-up (all sources)

**Files:**
- Modify: `scripts/50_build_unified.py` (add `load_std_pos` + `write_entry_pos`; ensure every `build_<source>` passes its row POS to `add_sense(..., part_of_speech=<raw_pos>)`; call `write_entry_pos` at end of `main()`)
- Test: `tests/test_unified.py`

**Interfaces:**
- Consumes: `std_pos(raw_pos→canonical_en, canonical_mi)`; `sense.part_of_speech`.
- Produces: `entry.part_of_speech` (deduped raw set), `entry.part_of_speech_en`, `entry.part_of_speech_mi`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_unified.py  (add)
def test_entry_pos_wrapup():
    conn = sqlite3.connect(DB_PATH)
    en, mi, raw = conn.execute(
        "SELECT part_of_speech_en, part_of_speech_mi, part_of_speech FROM entry "
        "WHERE source_id='williams' AND headword_search=? LIMIT 1", ("pae",)
    ).fetchone()
    conn.close()
    assert en and "Noun" in en          # canonical english wrap-up
    assert mi and "Tūingoa" in mi        # canonical māori wrap-up (n. -> Tūingoa)
    assert raw and "n." in raw           # raw set retained
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_unified.test_entry_pos_wrapup -v`
Expected: FAIL (`part_of_speech_en` NULL).

- [ ] **Step 3: Add the loader, the wrap-up, and per-source sense POS**

Add two module-level functions:

```python
def load_std_pos(con):
    m = {}
    for raw, en, mi in con.execute("SELECT raw_pos, canonical_en, canonical_mi FROM std_pos"):
        m[raw] = (en, mi)
    return m

def write_entry_pos(con, std_pos):
    rows = con.execute(
        "SELECT e.id, GROUP_CONCAT(s.part_of_speech, '\x1f') "
        "FROM entry e JOIN sense s ON s.entry_id = e.id GROUP BY e.id"
    ).fetchall()
    for eid, raws in rows:
        seen_raw, seen_en, seen_mi = [], [], []
        for r in (raws.split('\x1f') if raws else []):
            if not r or r == 'None':
                continue
            if r not in seen_raw:
                seen_raw.append(r)
            en, mi = std_pos.get(r, (None, None))
            if en and en not in seen_en:
                seen_en.append(en)
            if mi and mi not in seen_mi:
                seen_mi.append(mi)
        con.execute(
            "UPDATE entry SET part_of_speech=?, part_of_speech_en=?, part_of_speech_mi=? WHERE id=?",
            (", ".join(seen_raw) or None, ", ".join(seen_en) or None,
             ", ".join(seen_mi) or None, eid),
        )
    con.commit()
```

For the non-Williams builders (`build_te_aka`, `build_hepatakakupu`, `build_paekupu`,
`build_papakupu`): each already reads a `pos` for the row — pass it through to the sense, e.g.
change their `b.add_sense(eid, sn, gloss_en, gloss_mi, def_raw)` call to
`b.add_sense(eid, sn, gloss_en, gloss_mi, def_raw, part_of_speech=pos)`. (One line each. Paekupu
uses its `part_of_speech`; do NOT use `pos_mi` here — mi comes from `std_pos`.)

At the end of `main()`, after all selected sources are built and before the final
summary/print, add:

```python
    write_entry_pos(con, load_std_pos(con))
```

(It groups by entry, so re-running one source still produces correct per-entry wrap-ups for the
entries that exist.)

- [ ] **Step 4: Re-unify all and run the test**

Run: `PYTHONUTF8=1 py scripts/50_build_unified.py && PYTHONUTF8=1 py -m unittest tests.test_unified.test_entry_pos_wrapup -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint** — full `tests/test_unified.py` green; `cp data/staging_dictionary.db data/staging_dictionary.db.bak-task5`.

---

### Task 6: Full rebuild, export, verify, docs

**Files:**
- Run: `scripts/50_build_unified.py`, `scripts/60_export_app_db.py`
- Modify: `DATABASE_REFERENCE.md`, `SCHEMA_PROPOSAL.md`, `SESSIONS.md`

- [ ] **Step 1: Full suite green**

Run: `PYTHONUTF8=1 py -m unittest discover -s tests -p "test_*.py"`
Expected: OK (all prior + new tests).

- [ ] **Step 2: Re-unify all + export the app DB**

Run: `PYTHONUTF8=1 py scripts/50_build_unified.py && PYTHONUTF8=1 py scripts/60_export_app_db.py`
Expected: export prints `integrity_check: ok`, `foreign_key_check: clean`, and a size; sense count higher than 105,898.

- [ ] **Step 3: Verify the app DB has the new columns + data**

Run:
```bash
PYTHONUTF8=1 py -c "import sqlite3;c=sqlite3.connect(r'data/maori_dict.db');\
print('sense.pos', [r[1] for r in c.execute('PRAGMA table_info(sense)') if r[1]=='part_of_speech']);\
print('entry.pos', [r[1] for r in c.execute('PRAGMA table_info(entry)') if r[1].startswith('part_of_speech')]);\
print('sample', c.execute(\"select headword,part_of_speech_en,part_of_speech_mi from entry where source_id='williams' and headword_search='pae'\").fetchone())"
```
Expected: columns present; sample shows English + Māori wrap-up.

- [ ] **Step 4: Update docs**

- `DATABASE_REFERENCE.md`: in the unified-core section, document `sense.part_of_speech` and `entry.part_of_speech_en`/`_mi` (wrap-up of sense POS, mi where `std_pos` has it); note Williams is now multi-sense.
- `SCHEMA_PROPOSAL.md`: note the grain refinement — Williams multi-row senses now split; POS is sense-level with entry wrap-up.
- `SESSIONS.md`: add session 45 row (Williams multi-sense split + sense-level POS + entry wrap-up; final sense count; `std_pos` abbrevs seeded; mi from Paekupu where matched).

- [ ] **Step 5: Checkpoint** — `cp data/staging_dictionary.db data/staging_dictionary.db.bak-task6`.

---

## Self-Review

- **Spec coverage:** schema (T1) ✓; std_pos labels incl. Paekupu mi (T2) ✓; parser w/ sequential-run + carry-over + closed POS set (T3) ✓; build_williams split + examples→sense1 (T4) ✓; entry wrap-up all sources (T5) ✓; rebuild/export/docs (T6) ✓. Homonyms + per-sense examples explicitly out of scope (spec) — no task, correct.
- **Placeholder scan:** code shown in every code step; no TBD/TODO; the prose "leave … as they are" in T4 points at existing code to preserve, not a gap.
- **Type consistency:** `split_senses` dict keys (`sense_number`/`part_of_speech`/`gloss_en`/`definition_raw`) match T4 usage; `add_sense(..., part_of_speech=...)` matches T1's `sense.part_of_speech`; `entry.part_of_speech_en/_mi` consistent across T1/T5/T6.
