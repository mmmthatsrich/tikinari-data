# Williams Mid-Paragraph Sub-Headword Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the ~29 remaining Williams sub-headwords that session 65's paragraph-level split could not reach because they are glued *inside* a paragraph (or inside a single `<b>` element), driving the run-on-regex residue from 30 → ≤1.

**Architecture:** Extend `scripts/01_williams_parse.py` only. First refactor `_build_entry` to consume plain strings (headword, tail, paragraph texts, example spans) instead of lxml elements, so entries can be built from *virtual* paragraph fragments. Then add three detectors (plain-text sub-head paragraphs; POS+sense-number-in-bold; mid-paragraph bold sub-heads with a kinship guard) that emit a new entry kind `"subx"`. `01_williams_import.py` assigns `subx` ids in a reserved band `1_000_000 + main_id*100 + (50 + j)` so every id minted in session 65 (mains 1–11,910, subs/hangs k=1..49) is untouched — those ids are already referenced by the published bundle and the pushed dedup worklist.

**Tech Stack:** Python 3 (invoked as `py`), lxml, sqlite3, unittest. Windows: `PYTHONUTF8=1` on every run.

## Global Constraints

- **Id stability is inviolable.** After re-import: `williams_entries` ids 1–11,910 map to the same headwords as before, AND every existing id ≥ 1,000,000 maps to the same headword as before. New `subx` entries live only at `k ≥ 51`. Verified by a snapshot-diff step in Task 5.
- **Non-destructive:** all text removed from a parent gloss must reappear in the new sub-entry (the run-on tail moves, nothing is dropped).
- Normalisation stays exactly `utils.normalise_sort_key` / `normalise_search_key` — the import already applies them; do not re-implement.
- `PYTHONUTF8=1` prefix on every `py` command (macrons in output).
- Repo root: `C:\Local Git\Dictionaries`. Run all commands from there.
- One known-unfixable case is **accepted residue**: `houhou` (source_entry_id 1146001) keeps its leading `Hou (v), houhou, a. 1. Cold…` fragment (capitalized roman-homonym restart mid-div, 1 occurrence in the corpus). Do not attempt it.
- The Tikinari release loop is **out of scope** — this plan ends at the exported `data/maori_dict.db`. (When it does ship: Tikinari master swap must follow the approval-remap recipe in the project memory `tikinari-master-swap`.)

## Ground truth (verified 2026-07-07 against the raw HTML)

The 30 run-on last-senses (regex `\.\s+[a-zāēīōū\-]+, (a|ad|n|v\.i|v\.t|part)\. ` on Williams max-sense glosses) decompose into:

| Bucket | Shape (real example) | Count | Fix |
|---|---|---|---|
| A | mid-paragraph `…kereru. <b>whakahinuhinu</b>, a. <i>Glossy</i>.` (Hinu, seid 1193) | ~18 | split paragraph at the bold element |
| B | heads inside ONE bold: `‖ <b>kopi. topitopi</b>, n.` (Topi, 10439); `= <b>kareke, koitareke, tareke, tawaka. whakatūpererū</b>, v.i.` (10952) | 4 | split the bold's own text at its last `. ` |
| C | un-bolded paragraph-initial: `<p>rainga, n. <i>Undulation</i>.</p>` (Rai, 7889); also `whakaawhi` (560), `ihonga` (1752) | 3 | plain-text detector on `p.text` |
| D | POS + sense number inside bold: `<p> <b>māwhitiwhiti, n. 1</b>. <i>Grasshopper</i>…` (4912); `<b>ngingita, ngitangita</b>, a.` variant (5735) | 2–3 | extend `SUBHEAD_POS_RE` family |
| E | `Hou (v), houhou, a.` roman-homonym restart (1146001) | 1 | **leave** (accepted residue) |

Bucket A/B candidates are guarded by a **kinship test**: the candidate must be a derivative of the governing headword (shared macron-stripped, double-vowel-collapsed prefix ≥ 3 after dropping a leading `whaka` from either side). All 29 targets pass it (`tohunga`~`Tohu`, `taitaiao`~`Taiao`, `wariwari`~`whakawari`, `tiītoretore`~`Tītore` via search-key collapse); ordinary bold xrefs/idioms mid-sense do not carry a `, POS.` tail *and* sentence-final preceding text, so a false positive needs three simultaneous coincidences.

---

### Task 1: Refactor `_build_entry` to string inputs (behaviour-preserving)

**Files:**
- Modify: `scripts/01_williams_parse.py` (function `_build_entry`, its call sites in `parse_section_div`)
- Test: golden-output comparison (steps 1/4), no new test file

**Interfaces:**
- Produces: `_build_entry(headword, head_tail, para_texts, mi_examples, source_section, page_number, kind, parent_headword) -> dict | None` where `head_tail: str` (text after the headword element — sense-roman + POS live here), `para_texts: list[str]` (cleaned text of each owned paragraph, headword prefix still present in the first), `mi_examples: list[str]` (already-cleaned `span.foreign[lang=mi]` texts).
- Produces: `_group_payload(g) -> (headword, head_tail, para_texts, mi_examples)` — converts today's element-based group dict to the string form.

- [ ] **Step 1: Freeze the golden output**

```bash
PYTHONUTF8=1 py scripts/01_williams_parse.py
cp sources/williams/parsed/williams_entries.json sources/williams/parsed/williams_entries.golden.json
```
Expected: `Total: 14905 entries`.

- [ ] **Step 2: Refactor**

In `scripts/01_williams_parse.py` change `_build_entry` so it no longer touches lxml. Replace its signature and element-reading top half with:

```python
def _build_entry(headword, head_tail, para_texts, mi_examples, source_section,
                 page_number, kind, parent_headword):
    """Build one entry dict from pre-extracted strings."""
    tail = head_tail or ""

    sense_number = ""
    roman_m = ROMAN_RE.match(tail)
    if roman_m:
        sense_number = roman_m.group(1).lower()
        tail = tail[roman_m.end():]

    pos_m = POS_RE.match(tail)
    part_of_speech = pos_m.group(1) if pos_m else ""

    usage_examples = list(mi_examples)
    full_text = " ".join(t for t in para_texts if t)
```
…keep everything from `# Strip headword prefix…` down unchanged (it already operates on `full_text`/strings).

Add the adapter and rewire the group loop in `parse_section_div`:

```python
def _group_payload(g):
    """Convert an element-based group to _build_entry's string inputs."""
    elem = g["elem"]
    head_tail = elem.tail or ""
    para_texts, mi_examples = [], []
    for p in g["paras"]:
        txt = clean_text(p.text_content())
        if txt:
            para_texts.append(txt)
        for sp in p.iter("span"):
            if sp.get("class") == "foreign" and sp.get("lang") == "mi":
                ex = clean_text(sp.text_content())
                if ex:
                    mi_examples.append(ex)
    return g["headword"], head_tail, para_texts, mi_examples
```

```python
    entries = []
    for g in groups:
        hw, head_tail, para_texts, mi_examples = _group_payload(g)
        e = _build_entry(hw, head_tail, para_texts, mi_examples, source_section,
                         page_number, g["kind"], g["parent"])
        if e:
            entries.append(e)
```

(The synthesized-`See`-gloss block after this loop is untouched.)

- [ ] **Step 3: Run the parser**

```bash
PYTHONUTF8=1 py scripts/01_williams_parse.py
```
Expected: `Total: 14905 entries` (same as golden).

- [ ] **Step 4: Byte-compare against golden**

```bash
PYTHONUTF8=1 py -c "import json,sys;sys.stdout.reconfigure(encoding='utf-8');a=json.load(open('sources/williams/parsed/williams_entries.json',encoding='utf-8'));b=json.load(open('sources/williams/parsed/williams_entries.golden.json',encoding='utf-8'));print('IDENTICAL' if a==b else 'DIFF at '+str(next(i for i,(x,y) in enumerate(zip(a,b)) if x!=y)))"
```
Expected: `IDENTICAL`. If DIFF, fix the refactor — this task must be behaviour-preserving.

- [ ] **Step 5: Run the parse test file, then commit**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_parse -v
git add scripts/01_williams_parse.py
git commit -m "refactor(williams): _build_entry consumes strings, not lxml elements"
```
Expected: all tests pass. (`williams_entries.golden.json` stays uncommitted — deleted at the end of Task 5.)

---

### Task 2: Detector helpers — plain-text sub-heads (C) and POS+digit-in-bold (D)

**Files:**
- Modify: `scripts/01_williams_parse.py`
- Test: Create `tests/test_williams_subsplit.py`

**Interfaces:**
- Produces: `PLAIN_SUBHEAD_RE` — matches `p.text` like `"rainga, n. Undulation."` → group 1 `"rainga"`, group 2 `"n."`.
- Produces: `SUBHEAD_POS_NUM_RE` — matches bold text `"māwhitiwhiti, n. 1"` → group 1 `"māwhitiwhiti"`; `_sub_headword` returns it.
- Consumes: `_SUB_TOKEN`, `POS_RE`, `_sub_headword` from the existing parser.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_williams_subsplit.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the mid-paragraph Williams sub-headword split (post-S65 residue)."""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from lxml import html as lhtml

wparse = importlib.import_module("01_williams_parse")


def _p(html):
    """First <p> element of an HTML fragment."""
    return lhtml.fromstring(f"<div>{html}</div>").find("p")


class TestPlainSubhead(unittest.TestCase):
    def test_plain_paragraph_subhead(self):          # bucket C — Rai/rainga
        m = wparse.PLAIN_SUBHEAD_RE.match("rainga, n. Undulation.")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "rainga")

    def test_plain_requires_pos(self):
        self.assertIsNone(wparse.PLAIN_SUBHEAD_RE.match("rainga te mea nui."))

    def test_plain_rejects_capitalised(self):
        self.assertIsNone(wparse.PLAIN_SUBHEAD_RE.match("Ka kite, n. nope."))


class TestPosNumInBold(unittest.TestCase):
    def test_pos_and_sense_number_in_bold(self):     # bucket D — māwhitiwhiti
        p = _p('<p> <b>māwhitiwhiti, n. 1</b>. <i>Grasshopper</i>.</p>')
        got = wparse._sub_headword(p)
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "māwhitiwhiti")

    def test_existing_pos_in_bold_still_works(self):  # S65 case must not regress
        p = _p('<p> <b>whawhango, a</b>. <i>Somewhat hoarse</i>.</p>')
        self.assertEqual(wparse._sub_headword(p)[0], "whawhango")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit -v
```
Expected: FAIL — `AttributeError: module '01_williams_parse' has no attribute 'PLAIN_SUBHEAD_RE'`.

- [ ] **Step 3: Implement**

In `scripts/01_williams_parse.py`, next to `SUBHEAD_POS_RE` add:

```python
_POS_ALT = (r"(?:v\.t\.i|v\.t|v\.i|v|n|a|adv|ad|part|conj|prep|int|pron|num"
            r"|suf|pref|loc)")
# Bucket C: sub-head set as plain paragraph text — '<p>rainga, n. Undulation.'
PLAIN_SUBHEAD_RE = re.compile(
    rf"^({_SUB_TOKEN}(?:, {_SUB_TOKEN})*), ({_POS_ALT}\.) ")
# Bucket D: POS and the first sense number both inside the bold —
# '<b>māwhitiwhiti, n. 1</b>.'
SUBHEAD_POS_NUM_RE = re.compile(
    rf"^({_SUB_TOKEN}(?:, {_SUB_TOKEN})*), {_POS_ALT}\.? 1$")
```

In `_sub_headword`, directly under the existing `SUBHEAD_POS_RE` check, add:

```python
    pm = SUBHEAD_POS_NUM_RE.match(word)
    if pm:
        return (pm.group(1), b)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/01_williams_parse.py tests/test_williams_subsplit.py
git commit -m "feat(williams): detectors for plain-text and POS+number-in-bold sub-heads"
```

---

### Task 3: Kinship guard + mid-paragraph splitter (buckets A and B)

**Files:**
- Modify: `scripts/01_williams_parse.py`
- Test: `tests/test_williams_subsplit.py` (extend)

**Interfaces:**
- Produces: `_related(candidate, parent) -> bool` — search-key kinship (shared prefix ≥ 3 after dropping a leading `whaka`, or containment).
- Produces: `_split_midparagraph(p, parent_hw) -> list[dict]` — splits one `<p>` into fragment dicts `{"headword": str|None, "head_tail": str, "text": str}`; fragment 0 has `headword=None` (the parent's share). A paragraph with no split points returns exactly one fragment whose `text == clean_text(p.text_content())`.
- Consumes: `clean_text`, `_SUB_TOKEN`, `_POS_ALT`, `POS_RE`, `SUBHEAD_RE`, `SUBHEAD_POS_RE`, `SUBHEAD_POS_NUM_RE`; `normalise_search_key` from `utils` (new import).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_williams_subsplit.py`)

```python
class TestRelated(unittest.TestCase):
    def test_all_targets_pass(self):
        pairs = [("whakahinuhinu", "Hinu"), ("tohunga", "Tohu"),
                 ("taitaiao", "Taiao"), ("wariwari", "whakawari"),
                 ("tiītoretore", "Tītore"), ("ihonga", "Iho"),
                 ("whakatūpererū", "Tūpererū"),
                 ("ngingita", "Ngita"), ("tāraharaha", "Tarahanga")]
        for cand, parent in pairs:
            self.assertTrue(wparse._related(cand, parent), (cand, parent))

    def test_unrelated_word_fails(self):
        self.assertFalse(wparse._related("kereru", "Hinu"))
        self.assertFalse(wparse._related("titoki", "Topi"))


class TestMidParagraphSplit(unittest.TestCase):
    def test_bucket_a_bold_after_sentence(self):     # Hinu / whakahinuhinu
        p = _p('<p>Ka ki te taha i te hinu ka whaiwaewaetia, ka tataia ki te '
               'huruhuru kereru. <b>whakahinuhinu</b>, a. <i>Glossy</i>.</p>')
        frags = wparse._split_midparagraph(p, "Hinu")
        self.assertEqual(len(frags), 2)
        self.assertIsNone(frags[0]["headword"])
        self.assertTrue(frags[0]["text"].endswith("kereru."))
        self.assertEqual(frags[1]["headword"], "whakahinuhinu")
        self.assertIn("Glossy", frags[1]["text"])
        self.assertTrue(frags[1]["head_tail"].lstrip().startswith(", a.")
                        or frags[1]["head_tail"].lstrip().startswith("a."))

    def test_bucket_b_two_heads_in_one_bold(self):   # Topi / kopi. topitopi
        p = _p('<p class="hang"><span class="foreign bold" lang="mi">Topi'
               '</span>, v.i. <i>Shut</i>, as the mouth or hand. '
               '‖ <b>kopi. topitopi</b>, n. <i>Alectryon excelsum</i>, '
               'a tree. (Tar.) = <b>titoki</b>.</p>')
        frags = wparse._split_midparagraph(p, "Topi")
        self.assertEqual(len(frags), 2)
        self.assertTrue(frags[0]["text"].rstrip().endswith("kopi."))
        self.assertEqual(frags[1]["headword"], "topitopi")
        self.assertIn("Alectryon", frags[1]["text"])

    def test_bold_xref_not_split(self):              # '= <b>titoki</b>.' stays
        p = _p('<p><b>2</b>. A tree. = <b>titoki</b>.</p>')
        self.assertEqual(len(wparse._split_midparagraph(p, "Topi")), 1)

    def test_unrelated_bold_with_pos_not_split(self):
        p = _p('<p>Some sense. <b>kereru</b>, n. a pigeon aside.</p>')
        self.assertEqual(len(wparse._split_midparagraph(p, "Hinu")), 1)

    def test_mid_sentence_bold_not_split(self):      # no sentence-final prefix
        p = _p('<p>In the expression <b>whakapiri wahine</b>, a charm.</p>')
        self.assertEqual(len(wparse._split_midparagraph(p, "Piri")), 1)

    def test_fragment0_equals_text_content_when_no_split(self):
        p = _p('<p> <b>2</b>. <i>Game</i>, preserved in fat. Kei te tahere.</p>')
        frags = wparse._split_midparagraph(p, "Hinu")
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0]["text"], wparse.clean_text(p.text_content()))
```

- [ ] **Step 2: Run to verify failure**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit -v
```
Expected: FAIL — `no attribute '_related'`.

- [ ] **Step 3: Implement** (add to `scripts/01_williams_parse.py`; add `from utils import normalise_search_key` beside the existing `williams_xref` import — `scripts/` is already on `sys.path`)

```python
_SENT_END_RE = re.compile(r'[.?!]["”)]?\s*$')


def _strip_whaka(key):
    return key[5:] if key.startswith("whaka") and len(key) > 7 else key


def _related(candidate, parent):
    """Derivative kinship: shared search-key prefix >=3 (whaka- dropped)."""
    a = _strip_whaka(normalise_search_key(candidate))
    b = _strip_whaka(normalise_search_key(parent))
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return common >= 3


# bold text that is 'xref-list. newhead' — the split point is inside the bold
_BOLD_TAIL_HEAD_RE = re.compile(
    rf"^(.*\.)\s+({_SUB_TOKEN}(?:, {_SUB_TOKEN})*)$", re.DOTALL)


def _split_midparagraph(p, parent_hw):
    """Split one <p> at mid-paragraph derivative sub-heads (buckets A/B).

    A bold child is a split point only when ALL THREE hold: the accumulated
    preceding text ends a sentence; the bold (or its trailing token after an
    'xref-list. ' prefix) is a lowercase token/variant list RELATED to the
    governing headword; and a POS marker follows (in the tail, or already
    inside the bold via SUBHEAD_POS_RE / SUBHEAD_POS_NUM_RE).
    """
    frags = [{"headword": None, "head_tail": "", "text": clean_text(p.text or "")}]

    def _append(s):
        s = clean_text(s or "")
        if s:
            cur = frags[-1]["text"]
            frags[-1]["text"] = (cur + " " + s).strip() if cur else s

    for child in p:
        sub_hw = None
        keep_left = ""
        head_tail = ""
        if child.tag == "b":
            word = clean_text(child.text_content())
            tail = child.tail or ""
            pm = SUBHEAD_POS_RE.match(word) or SUBHEAD_POS_NUM_RE.match(word)
            if pm and _related(pm.group(1), parent_hw):
                sub_hw = pm.group(1)
                head_tail = word[len(sub_hw):] + tail   # ', a' + '. <rest>'
            elif SUBHEAD_RE.match(word) and POS_RE.match(tail.lstrip()) \
                    and _related(word, parent_hw):
                sub_hw = word
                head_tail = tail
            else:
                bm = _BOLD_TAIL_HEAD_RE.match(word)     # bucket B
                if bm and POS_RE.match(tail.lstrip()) \
                        and _related(bm.group(2), parent_hw):
                    keep_left, sub_hw = bm.group(1), bm.group(2)
                    head_tail = tail
            if sub_hw is not None and not _SENT_END_RE.search(
                    (frags[-1]["text"] + " " + keep_left).strip()):
                sub_hw = None                            # mid-sentence: keep glued
        if sub_hw is None:
            _append(child.text_content())
            _append(child.tail)
            continue
        _append(keep_left)
        frags.append({"headword": sub_hw,
                      "head_tail": head_tail,
                      "text": sub_hw})
        _append(head_tail)
    return frags
```

Semantics to preserve while iterating: the new fragment's `text` starts with the sub-headword (so `_build_entry`'s existing headword-prefix strip fires) and then carries `head_tail` plus everything after the bold; `head_tail` separately feeds the POS extractor. Trace both the `pm` branch (`", a" + ". Glossy."`) and the plain branch (`", a. Glossy."`) — the Task 3 tests pin the observable behaviour; adjust plumbing until green.

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit -v
```
Expected: all 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/01_williams_parse.py tests/test_williams_subsplit.py
git commit -m "feat(williams): kinship-guarded mid-paragraph sub-head splitter"
```

---

### Task 4: Wire into `parse_section_div` as kind `subx`

**Files:**
- Modify: `scripts/01_williams_parse.py` (`parse_section_div`)
- Test: `tests/test_williams_subsplit.py` (extend), corpus assertions in step 4

**Interfaces:**
- Produces: parser JSON entries with `"kind": "subx"` and `"parent_headword"` set; bucket-C plain paragraphs also emit `subx`.
- Consumes: `_split_midparagraph`, `_related`, `PLAIN_SUBHEAD_RE`, `_group_payload`, `_build_entry`.

- [ ] **Step 1: Write the failing tests** (append)

```python
class TestParseSectionDivSubx(unittest.TestCase):
    def _entries(self, div_html):
        div = lhtml.fromstring(div_html)
        return wparse.parse_section_div(div, "T", 1)

    def test_hinu_shape_end_to_end(self):
        div_html = ('<div class="section"><p class="hang">'
                    '<span class="foreign bold" lang="mi">Hinu</span>, n. '
                    '<b>1</b>. <i>Oil, fat</i>.</p>'
                    '<p>Ka ki te taha i te hinu. <b>whakahinuhinu</b>, a. '
                    '<i>Glossy</i>.</p></div>')
        es = self._entries(div_html)
        self.assertEqual([e["headword"] for e in es], ["Hinu", "whakahinuhinu"])
        self.assertEqual(es[1]["kind"], "subx")
        self.assertEqual(es[1]["parent_headword"], "Hinu")
        self.assertEqual(es[1]["part_of_speech"], "a.")
        self.assertNotIn("whakahinuhinu", es[0]["definition"])
        self.assertIn("Glossy", es[1]["definition"])

    def test_rai_plain_paragraph_end_to_end(self):   # bucket C
        div_html = ('<div class="section"><p class="hang">'
                    '<span class="foreign bold" lang="mi">Rai</span>, rarai, a. '
                    '<i>Ribbed, furrowed</i>.</p>'
                    '<p>rainga, n. <i>Undulation</i>.</p></div>')
        es = self._entries(div_html)
        self.assertEqual([e["headword"] for e in es], ["Rai", "rainga"])
        self.assertEqual(es[1]["kind"], "subx")
        self.assertEqual(es[1]["part_of_speech"], "n.")
```

Run: `PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit -v` → the two new tests FAIL (whakahinuhinu/rainga not emitted).

- [ ] **Step 2: Implement**

Two insertions in `parse_section_div`.

(a) Bucket C — in the `elif main_hw is not None:` branch, after the `_sub_headword` check returns None, try the plain detector before falling through to continuation:

```python
        elif main_hw is not None:
            sub = _sub_headword(child)
            if sub is not None:
                word, b = sub
                current = {"kind": "sub", "headword": word, "elem": b,
                           "paras": [child], "parent": last_hang_hw}
                groups.append(current)
                continue
            ptext = clean_text(child.text or "")
            pmm = PLAIN_SUBHEAD_RE.match(ptext)
            if pmm and _related(pmm.group(1), last_hang_hw):
                current = {"kind": "subx", "headword": pmm.group(1),
                           "plain_p": child, "paras": [child],
                           "parent": last_hang_hw}
                groups.append(current)
                continue
```

(b) Buckets A/B — replace the entry-building loop so each group's paragraphs pass through `_split_midparagraph`; fragments after the first become `subx` entries owned by that group's headword:

```python
    entries = []
    for g in groups:
        if "plain_p" in g:                      # bucket C: strings direct
            ptext = clean_text(g["plain_p"].text_content())
            head_tail = ptext[len(g["headword"]):]
            e = _build_entry(g["headword"], head_tail, [ptext], [],
                             source_section, page_number, "subx", g["parent"])
            if e:
                entries.append(e)
            continue
        hw, head_tail, _texts_unused, mi_examples = _group_payload(g)
        own_texts, extra = [], []
        for p in g["paras"]:
            frags = _split_midparagraph(p, hw)
            if frags[0]["text"]:
                own_texts.append(frags[0]["text"])
            extra.extend(frags[1:])
        e = _build_entry(hw, head_tail, own_texts, mi_examples,
                         source_section, page_number, g["kind"], g["parent"])
        if e:
            entries.append(e)
        for fr in extra:
            se = _build_entry(fr["headword"], fr["head_tail"], [fr["text"]], [],
                              source_section, page_number, "subx", hw)
            if se:
                entries.append(se)
```

Ordering note: `subx` entries from a group are appended immediately after that group's entry — fine for reading order; the import (Task 5) puts their *ids* in the k≥51 band regardless of position, so S65 `sub`/`hang` ids are unaffected.

- [ ] **Step 3: Run unit tests**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit tests.test_williams_parse -v
```
Expected: all PASS. (`test_williams_parse` re-reads the JSON from disk — regenerate in step 4 first if it complains about counts.)

- [ ] **Step 4: Corpus run + parity + recovery assertions**

```bash
PYTHONUTF8=1 py scripts/01_williams_parse.py
```
Expected total: **≈ 14,933** (29 targets minus accepted residue; anything in 14,925–14,945 is plausible — investigate outside that range; each extra/missing entry must be explainable).

```bash
PYTHONUTF8=1 py - <<'EOF'
import json, sqlite3, sys
sys.stdout.reconfigure(encoding="utf-8")
ents = json.load(open("sources/williams/parsed/williams_entries.json", encoding="utf-8"))
mains = [e for e in ents if e["kind"] == "main"]
olds  = [e for e in ents if e["kind"] in ("sub", "hang")]
con = sqlite3.connect("data/staging_dictionary.db")
db_mains = [h for (h,) in con.execute(
    "SELECT headword FROM williams_entries WHERE id<=11910 ORDER BY id")]
db_subs  = [h for (h,) in con.execute(
    "SELECT headword FROM williams_entries WHERE id>=1000000 ORDER BY id")]
assert [m["headword"] for m in mains] == db_mains, "MAIN SEQUENCE BROKE"
assert [o["headword"] for o in olds] == db_subs,  "S65 SUB SEQUENCE BROKE"
got = {e["headword"] for e in ents if e["kind"] == "subx"}
have_sub = {e["headword"] for e in ents if e["kind"] == "sub"}
want = {"whakahinuhinu", "tohunga", "topitopi", "rainga", "whakaawhi",
        "ihonga", "wariwari", "taitaiao", "whakaonge", "whakamatika"}
missing = want - got - have_sub
print("subx count:", len([e for e in ents if e["kind"] == "subx"]))
print("spot-check missing:", missing or "none")
assert not missing
print("PARITY + RECOVERY OK")
EOF
```
Expected: `PARITY + RECOVERY OK`. The S65-sub-sequence assert is the critical one — if it fires, a `subx` leaked into `sub`/`hang` kind or reordered them; fix the parser, never weaken the assert.

- [ ] **Step 5: Commit**

```bash
git add scripts/01_williams_parse.py tests/test_williams_subsplit.py
git commit -m "feat(williams): emit mid-paragraph sub-heads as kind=subx"
```

---

### Task 5: Import band ids for `subx` + full pipeline re-run

**Files:**
- Modify: `scripts/01_williams_import.py`
- Test: `tests/test_williams_subsplit.py` (band test), snapshot diff in step 4

**Interfaces:**
- Produces: `assign_ids(entries) -> list[int]` — module-level, pure; `subx` ids = `1_000_000 + main_id*100 + 50 + j` (`j` 1-based per main; error above 49). `sub`/`hang` keep k=1..49 exactly as S65; mains 1..N.

- [ ] **Step 1: Failing test** (append to `tests/test_williams_subsplit.py`)

```python
class TestImportBandIds(unittest.TestCase):
    def test_subx_band(self):
        imp = importlib.import_module("01_williams_import")
        base = {"definition": "x", "part_of_speech": "", "usage_examples": [],
                "cross_refs": [], "sense_number": "", "page_number": 1,
                "source_section": "P"}
        entries = [dict(base, headword="Piri",    kind="main"),
                   dict(base, headword="piriahi", kind="sub"),
                   dict(base, headword="pirix",   kind="subx"),
                   dict(base, headword="Pirir",   kind="main"),
                   dict(base, headword="pirisubx", kind="subx")]
        self.assertEqual(imp.assign_ids(entries),
                         [1, 1000101, 1000151, 2, 1000251])
```

Run: `PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit.TestImportBandIds -v` → FAIL (`no attribute 'assign_ids'`).

- [ ] **Step 2: Implement** — extract the id loop from `import_williams` into a module-level function and add the band:

```python
def assign_ids(entries):
    """Deterministic williams_entries ids. mains: 1..N positional.
    sub/hang: 1_000_000 + main*100 + k (k=1..49, S65 scheme — frozen).
    subx (mid-paragraph recoveries, S66): same formula, k = 50 + j."""
    ids, main_seq, sub_k, subx_j = [], 0, 0, 0
    for e in entries:
        kind = e.get("kind", "main")
        if kind == "main":
            main_seq += 1
            sub_k = subx_j = 0
            ids.append(main_seq)
            continue
        if main_seq == 0:
            raise ValueError(f"sub-entry before any main: {e['headword']}")
        if kind == "subx":
            subx_j += 1
            if subx_j > 49:
                raise ValueError(f"over 49 subx under main id {main_seq}")
            ids.append(1_000_000 + main_seq * 100 + 50 + subx_j)
        else:
            sub_k += 1
            if sub_k > 49:
                raise ValueError(f"over 49 sub-entries under main id {main_seq}")
            ids.append(1_000_000 + main_seq * 100 + sub_k)
    return ids
```

In `import_williams`, replace the inline `main_seq/sub_k` block with:

```python
    eids = assign_ids(entries)
    rows = []
    for eid, e in zip(eids, entries):
        rows.append((
            eid,
            e["headword"],
            ...            # rest of the tuple exactly as today
        ))
```
(The S65 cap tightens from 99 to 49 — current max per parent is 6; the ValueError guards regression.)

- [ ] **Step 3: Unit tests green**

```bash
PYTHONUTF8=1 py -m unittest tests.test_williams_subsplit tests.test_williams_parse -v
```
Expected: all PASS.

- [ ] **Step 4: Backup, snapshot, re-import, id-stability diff, downstream rebuild**

```bash
ts=$(date +%Y%m%d-%H%M%S)
cp data/staging_dictionary.db "backups/staging_dictionary.db.bak-$ts-williams-subx"
cp data/maori_dict.db "backups/maori_dict.db.bak-$ts-williams-subx"
PYTHONUTF8=1 py - <<'EOF'
import sqlite3, json
con = sqlite3.connect("data/staging_dictionary.db")
snap = {str(i): h for i, h in con.execute("SELECT id, headword FROM williams_entries")}
json.dump(snap, open("backups/williams_ids_pre_subx.json", "w", encoding="utf-8"),
          ensure_ascii=False)
print("snapshot", len(snap))
EOF
PYTHONUTF8=1 py scripts/01_williams_import.py
PYTHONUTF8=1 py - <<'EOF'
import sqlite3, json, sys
sys.stdout.reconfigure(encoding="utf-8")
old = {int(k): v for k, v in json.load(
    open("backups/williams_ids_pre_subx.json", encoding="utf-8")).items()}
con = sqlite3.connect("data/staging_dictionary.db")
new = dict(con.execute("SELECT id, headword FROM williams_entries"))
changed = {i: (old[i], new.get(i)) for i in old if new.get(i) != old[i]}
added = sorted(set(new) - set(old))
assert not changed, f"EXISTING IDS CHANGED: {list(changed.items())[:5]}"
assert all(i % 100 >= 51 for i in added), f"new id outside subx band: {added[:5]}"
print(f"OK: 0 changed, {len(added)} added, all in k>=51 band")
EOF
PYTHONUTF8=1 py scripts/50_build_unified.py --source williams
PYTHONUTF8=1 py scripts/08b_pollex_entry_linker.py --write --reset
PYTHONUTF8=1 py scripts/52_build_etymology_unified.py --reset
PYTHONUTF8=1 py scripts/06_fts_rebuild.py
PYTHONUTF8=1 py scripts/35_detect_pairs.py
```
Expected: `OK: 0 changed, ~28 added…`; unify `entry 149xx`; 52 `PARITY: PASS`; detect_pairs skips all pre-existing pairs.

- [ ] **Step 5: Final verification — residue ≤ 2, nothing lost, full suite, export**

```bash
PYTHONUTF8=1 py - <<'EOF'
import sqlite3, re, sys
sys.stdout.reconfigure(encoding="utf-8")
con = sqlite3.connect("data/staging_dictionary.db")
pat = re.compile(r"\.\s+[a-zāēīōū\-]+, (a|ad|n|v\.i|v\.t|part)\. ")
rows = con.execute("""SELECT e.source_entry_id, e.headword, s.gloss_en
  FROM entry e JOIN sense s ON s.entry_id=e.id
  WHERE e.source_id='williams' AND s.sense_number=
    (SELECT MAX(s2.sense_number) FROM sense s2 WHERE s2.entry_id=e.id)""").fetchall()
hits = [(a, b) for a, b, g in rows if g and pat.search(g)]
print("residue:", len(hits), hits)
assert len(hits) <= 2, "residue too high — inspect leftovers before proceeding"
for hw, frag in [("whakahinuhinu", "Glossy"), ("rainga", "Undulation"),
                 ("topitopi", "Alectryon"), ("tohunga", "Skilled person")]:
    n = con.execute("""SELECT COUNT(*) FROM entry e JOIN sense s ON s.entry_id=e.id
        WHERE e.source_id='williams' AND e.headword=? AND s.gloss_en LIKE ?""",
        (hw, f"%{frag}%")).fetchone()[0]
    assert n >= 1, hw
print("recovered glosses present")
EOF
PYTHONUTF8=1 py -m unittest discover -s tests -p "test_*.py"
PYTHONUTF8=1 py scripts/60_export_app_db.py
rm sources/williams/parsed/williams_entries.golden.json
```
Expected: `residue:` 1 (`houhou`) — 2 acceptable if one leftover proves legitimately unsplittable on inspection; all repo tests `OK`; export `integrity_check: ok`.

- [ ] **Step 6: Trackers + commit**

Update `SESSIONS.md`: add S66 row (mid-paragraph subsplit; entry counts before/after; residue list; `subx` band `k=51+`) and bump the Summary paragraph. Update `DATABASE_REFERENCE.md`: `williams_entries` row count, Williams entry/sense counts, `entry`/`sense`/`relation` totals, extend the `williams_entries.id` scheme note with "`subx` mid-paragraph recoveries take `k = 50 + j`". Use the real numbers printed in steps 4–5.

```bash
git add scripts/01_williams_parse.py scripts/01_williams_import.py \
        tests/test_williams_subsplit.py SESSIONS.md DATABASE_REFERENCE.md
git commit -m "feat(williams): recover mid-paragraph glued sub-headwords (session 66)"
```

---

## Self-Review Notes

- **Spec coverage:** bucket A (Tasks 3+4), B (Task 3), C (Task 2 detector + Task 4 wiring), D (Task 2), E excluded by Global Constraints. Id stability: Task 5 band + snapshot diff. Non-destructive: Task 5 step 5 gloss-presence asserts.
- **Known fiddly spot:** tail plumbing in `_split_midparagraph` (which string becomes `head_tail` per branch). The Task 3 tests deliberately pin observable behaviour (`head_tail` starts with the POS text; fragment texts carry the moved gloss) — treat the tests as the arbiter, not the sketch.
- **Type consistency:** `_build_entry(headword, head_tail, para_texts, mi_examples, source_section, page_number, kind, parent_headword)` identical across Tasks 1, 3, 4; `assign_ids(entries) -> list[int]` only in Task 5; fragment dict keys `headword`/`head_tail`/`text` consistent across Tasks 3–4.
- **Do NOT run the Tikinari release loop from this plan.** When shipping later, follow project memory `tikinari-master-swap` (approval remap). The new `subx` ids enlarge the dedup worklist again — expected.
