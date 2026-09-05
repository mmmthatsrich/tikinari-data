# Wakareo ā-ipurangi Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract ten component dictionaries from Wakareo ā-ipurangi (reotupu.co.nz) into `staging_dictionary.db` as new word-list sources, unified into the canonical core and excluded from the app DB export.

**Architecture:** A pure, DB-free parser module (`scripts/wakareo_records.py`) does all HTML→dict work and is unit-tested against committed fixtures. An authenticated scraper sweeps `Browse.aspx?ID=n` and routes each record by the `WR-` provenance tag it carries. Ten landing tables preserve each component's native lookup direction; `50_build_unified.py` projects them into the core, inverting the five English-headword sources so `entry.headword` is always Māori. `60_export_app_db.py` gains a source exclusion list so none of it reaches `maori_dict.db`.

**Tech Stack:** Python 3.12 (invoked as `py`), `requests`, `truststore`, sqlite3, unittest. Windows: `PYTHONUTF8=1` on every run.

**Spec:** `docs/superpowers/specs/2026-09-05-wakareo-extraction-design.md`

## Global Constraints

- **Repo root: `C:\AI Development\Dictionaries`.** Run every command from there. (Older plans in this directory say `C:\Local Git\Dictionaries` — the repo has moved; ignore that path.)
- **`PYTHONUTF8=1` prefix on every `py` command** — macrons in headwords and output.
- **TLS:** every script that makes an HTTPS request MUST call `truststore.inject_into_ssl()` **before** `import requests`. Norton Antivirus intercepts TLS on this machine (`CN=Norton Web/Mail Shield Root`), so `certifi` cannot validate the chain. **`verify=False` is forbidden** — credentials are POSTed over this connection.
- **Credentials** come only from `utils.load_env("WAKAREO_USER", "WAKAREO_PASS")`, which reads the gitignored `.env`. Never hardcode, never log, never write them to `sources/` or any committed file.
- **Nothing ships.** No Wakareo source may appear in `data/maori_dict.db`. Task 7 enforces this with a test.
- **Williams is skipped.** Any record carrying the `WR-WWC` tag is discarded and counted, never landed.
- **`sources/` is gitignored.** Test fixtures must live in `tests/fixtures/wakareo/`, which is committed.
- **Politeness:** 1.5s minimum delay between requests, `User-Agent: MaoriDictResearch/1.0 (rich@kaio.co.nz)`.
- **Back up before any DB write:** `cp data/staging_dictionary.db data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-wakareo`.

## The ten sources

`source_id` → landing table → direction. Memorise this table; every task refers to it.

| `source_id` | Landing table | `WR-` tag | Direction |
|---|---|---|---|
| `tregear_exceptions` | `tregear_exceptions_entries` | `WR-TE` | MI→EN |
| `ngata` | `ngata_entries` | `WR-HMN` | **EN→MI** |
| `te_matatiki` | `te_matatiki_entries` | `WR-TM` | MI→EN |
| `kimikupu_hou` | `kimikupu_hou_entries` | `WR-KKH` | **EN→MI** |
| `he_kupu_arotake` | `he_kupu_arotake_entries` | `WR-HKA` | **EN→MI** |
| `kupu_rorohiko` | `kupu_rorohiko_entries` | `WR-HKR` | **EN→MI** |
| `tai_kupu_variants` | `tai_kupu_variants_entries` | `WR-TK` | MI→EN |
| `nga_tini_a_tangaroa` | `nga_tini_a_tangaroa_entries` | `WR-NT` | MI→EN |
| `kupu_mataora` | `kupu_mataora_entries` | `WR-KM` | **EN→MI** |
| `maori_law_lexicon` | `maori_law_lexicon_entries` | `WR-CL` | MI→EN |

Plus `WR-WWC` (Williams Corpus) — **discarded**.

## File structure

| File | Responsibility |
|---|---|
| `scripts/wakareo_records.py` | **Create.** Pure HTML→dict parsing. No DB, no network, no filesystem. All ten body parsers. |
| `scripts/41_wakareo_scrape.py` | **Create.** Login, ID sweep, raw HTML to `sources/wakareo/raw/`, resumable manifest. |
| `scripts/41_wakareo_parse.py` | **Create.** Walks raw HTML, dispatches to `wakareo_records`, writes per-source JSON. |
| `scripts/41_wakareo_import.py` | **Create.** JSON → the ten landing tables. |
| `scripts/00_init_db.py` | **Modify.** Ten `CREATE TABLE`s + ten `source_metadata` rows. |
| `scripts/50_build_unified.py` | **Modify.** Ten builders, EN→MI inversion, `SOURCES` tuple. |
| `scripts/60_export_app_db.py` | **Modify.** Source exclusion filter on the copy step. |
| `tests/fixtures/wakareo/*.html` | **Create.** Committed copies of the recon fixtures. |
| `tests/test_wakareo_records.py` | **Create.** Unit tests for the pure module. |
| `tests/test_wakareo_provenance.py` | **Create.** DB-level integrity + export exclusion guard. |

---

### Task 1: Fixtures + template splitter

**Files:**
- Create: `tests/fixtures/wakareo/` (copies of 11 recon entry fixtures)
- Create: `scripts/wakareo_records.py`
- Create: `tests/test_wakareo_records.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `split_template(html) -> dict | None` with keys `headword`, `pos`, `search_scope`, `body`, `ref_tag`, `ref_no`. Returns `None` when the HTML holds no record. `parse_search_scope(text) -> list[str]`. `strip_tags(html) -> str`.

- [ ] **Step 1: Copy the recon fixtures into the committed test tree**

```bash
mkdir -p tests/fixtures/wakareo
cp sources/wakareo/recon/entry_DICT*.html tests/fixtures/wakareo/
cp sources/wakareo/recon/shape_*.html tests/fixtures/wakareo/
ls tests/fixtures/wakareo/
```

Expected: 17 files — `entry_DICT1_1.html` … `entry_DICT11_81063.html`, plus `shape_KIMIKUPU_52800.html`, `shape_MATATIKI_47800.html`, `shape_NGATA_26218.html`, `shape_NGATA_26240.html`, `shape_NGATA_26300.html`, `shape_TAIKUPU-VAR_78035.html`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_wakareo_records.py`:

```python
"""Wakareo record parsing — pure functions, no DB, no network."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import wakareo_records as wr

FIXTURES = Path(__file__).parent / "fixtures" / "wakareo"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TemplateSplit(unittest.TestCase):
    def test_ngata_multi_equivalent(self):
        r = wr.split_template(fx("shape_NGATA_26300.html"))
        self.assertEqual(r["headword"], "Aloofness")
        self.assertEqual(r["ref_tag"], "HMN")
        self.assertEqual(r["ref_no"], 297)
        self.assertEqual(r["pos"], "")
        self.assertEqual(r["search_scope"], "")
        self.assertIn("tū whakamatara", r["body"])

    def test_matatiki_has_pos_and_paren_scope(self):
        r = wr.split_template(fx("shape_MATATIKI_47800.html"))
        self.assertEqual(r["headword"], "Aumanga")
        self.assertEqual(r["pos"], "[noun]")
        self.assertEqual(r["ref_tag"], "TM")
        self.assertEqual(wr.parse_search_scope(r["search_scope"]), ["aumanga"])

    def test_tai_kupu_bracket_scope(self):
        r = wr.split_template(fx("shape_TAIKUPU-VAR_78035.html"))
        self.assertEqual(r["ref_tag"], "TK")
        self.assertEqual(
            wr.parse_search_scope(r["search_scope"]), ["ahua", "ahūa", "āhua"]
        )

    def test_williams_corpus_record_is_identifiable(self):
        r = wr.split_template(fx("entry_DICT1_1.html"))
        self.assertEqual(r["ref_tag"], "WWC")

    def test_every_fixture_parses_and_tags(self):
        known = {"WWC", "TE", "HMN", "TM", "KKH", "HKA", "HKR", "TK", "NT", "KM", "CL"}
        for p in sorted(FIXTURES.glob("*.html")):
            with self.subTest(fixture=p.name):
                r = wr.split_template(p.read_text(encoding="utf-8"))
                self.assertIsNotNone(r, f"{p.name} did not parse")
                self.assertIn(r["ref_tag"], known)
                self.assertTrue(r["headword"])

    def test_no_record_returns_none(self):
        self.assertIsNone(wr.split_template("<html><body>nothing</body></html>"))

    def test_empty_scope_is_empty_list(self):
        self.assertEqual(wr.parse_search_scope(""), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_wakareo_records -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wakareo_records'`

- [ ] **Step 4: Write the implementation**

Create `scripts/wakareo_records.py`:

```python
"""Parse Wakareo ā-ipurangi record HTML into plain dicts.

Pure: no DB, no network, no filesystem. Every function takes and returns
plain Python values so the whole module is unit-testable against fixtures.

Each record uses one template, emitted BEFORE the page's <!DOCTYPE>:

    <TD><TD><FONT SIZE='+2'>{headword}</FONT></TD>
    <TD>{pos}</TD>
    <TD ALIGN='Right'>{search_scope}</TD>
    <BR><HR SIZE='2' WIDTH='100%'><BR>
    {body}
    <BR><BR>[Reference: WR-{TAG}.{n}]

The page <title> reads "Custom Māori Law Lexicon" on EVERY record — an
upstream template bug. Only the WR- tag identifies the component.
"""
import re

_HEADWORD = re.compile(r"(?is)<FONT\s+SIZE='\+2'>(.*?)</FONT>")
_POS = re.compile(r"(?is)</FONT>\s*</TD>\s*<TD>(.*?)</TD>")
_SCOPE = re.compile(r"(?is)<TD\s+ALIGN='Right'>(.*?)</TD>")
_RULE = re.compile(r"(?is)<HR[^>]*>\s*(?:<BR>)?")
_REF = re.compile(r"(?is)\[Reference:\s*WR-([A-Z]+)\.(\d+)\]")
_SCOPE_INNER = re.compile(r"(?is)[\(\[]\s*Search Scope:\s*(.*?)\s*[\)\]]")
_TAG = re.compile(r"(?is)<[^>]+>")


def strip_tags(html: str) -> str:
    """Drop tags, decode the only entity Wakareo emits, collapse whitespace."""
    if not html:
        return ""
    text = _TAG.sub(" ", html).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def split_template(html: str) -> dict | None:
    """Split one record page into its four slots plus the provenance tag.

    Returns None when the page carries no record (empty ID, or a login
    redirect body).
    """
    if not html:
        return None
    record = html.split("<!DOCTYPE")[0]
    ref = _REF.search(record)
    hw = _HEADWORD.search(record)
    if not (ref and hw):
        return None

    pos = _POS.search(record)
    scope = _SCOPE.search(record)

    tail = _RULE.split(record, maxsplit=1)
    body = tail[1] if len(tail) > 1 else ""
    body = _REF.sub("", body)

    return {
        "headword": strip_tags(hw.group(1)),
        "pos": strip_tags(pos.group(1)) if pos else "",
        "search_scope": strip_tags(scope.group(1)) if scope else "",
        "body": body.strip(),
        "ref_tag": ref.group(1),
        "ref_no": int(ref.group(2)),
    }


def parse_search_scope(text: str) -> list[str]:
    """['ahua', 'ahūa', 'āhua'] from either bracket style, [] when absent."""
    if not text:
        return []
    m = _SCOPE_INNER.search(text)
    if not m:
        return []
    return [p.strip() for p in m.group(1).split(",") if p.strip()]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `PYTHONUTF8=1 py -m unittest tests.test_wakareo_records -v`
Expected: PASS, 7 tests.

If `test_every_fixture_parses_and_tags` fails on a specific fixture, print that fixture's first 400 characters and adjust the regex — do **not** loosen the assertion.

- [ ] **Step 6: Commit**

```bash
git add scripts/wakareo_records.py tests/test_wakareo_records.py tests/fixtures/wakareo/
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): record template splitter + committed recon fixtures"
```

---

### Task 2: Per-component body parsers

**Files:**
- Modify: `scripts/wakareo_records.py`
- Modify: `tests/test_wakareo_records.py`

**Interfaces:**
- Consumes: `split_template`, `parse_search_scope`, `strip_tags` from Task 1.
- Produces: `TAG_TO_SOURCE: dict[str, str]` mapping `WR-` tag → `source_id`; `EN_MI_SOURCE_IDS: frozenset[str]`; `parse_record(html) -> dict | None` returning `{source_id, ref_no, headword, pos, search_scope: list, body_raw, ...}` plus direction-specific keys — `equivalents: list[str]`, `example_en`, `example_mi` for EN→MI; `gloss_en` for MI→EN; `derivation`, `williams_refs: list[int]` additionally for `te_matatiki`. Returns `None` for `WR-WWC` and unparseable pages.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wakareo_records.py`, before the `if __name__` block:

```python
class BodyParsers(unittest.TestCase):
    def test_ngata_splits_equivalents_and_example_pair(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertEqual(r["source_id"], "ngata")
        self.assertEqual(r["headword"], "Aloofness")
        self.assertEqual(r["equivalents"], ["tū whakamatara", "tūrangahapa"])
        self.assertEqual(
            r["example_en"], "Her aloofness separated her from the others."
        )
        self.assertEqual(
            r["example_mi"], "Na tōna tū whakamatara kē a ia i wehe atu i ētahi."
        )

    def test_ngata_single_equivalent_with_stray_close_tag(self):
        # fixture 26240 body starts with a stray "</B>" before the equivalent
        r = wr.parse_record(fx("shape_NGATA_26240.html"))
        self.assertEqual(r["equivalents"], ["ohorere"])
        self.assertEqual(r["example_en"], "She jumped up in alarm.")

    def test_kimikupu_no_example_leaves_pair_none(self):
        r = wr.parse_record(fx("shape_KIMIKUPU_52800.html"))
        self.assertEqual(r["source_id"], "kimikupu_hou")
        self.assertEqual(r["equivalents"], ["pukahu"])
        self.assertIsNone(r["example_en"])
        self.assertIsNone(r["example_mi"])

    def test_matatiki_gloss_derivation_and_williams_refs(self):
        r = wr.parse_record(fx("shape_MATATIKI_47800.html"))
        self.assertEqual(r["source_id"], "te_matatiki")
        self.assertEqual(r["gloss_en"], "Vent")
        self.assertIn("hollowed-out space", r["derivation"])
        self.assertEqual(r["williams_refs"], [22])

    def test_tai_kupu_variants(self):
        r = wr.parse_record(fx("shape_TAIKUPU-VAR_78035.html"))
        self.assertEqual(r["source_id"], "tai_kupu_variants")
        self.assertEqual(r["search_scope"], ["ahua", "ahūa", "āhua"])
        self.assertTrue(r["gloss_en"])

    def test_williams_corpus_is_discarded(self):
        self.assertIsNone(wr.parse_record(fx("entry_DICT1_1.html")))

    def test_every_non_williams_fixture_yields_a_source_id(self):
        for p in sorted(FIXTURES.glob("entry_DICT*.html")):
            if p.name == "entry_DICT1_1.html":
                continue
            with self.subTest(fixture=p.name):
                r = wr.parse_record(p.read_text(encoding="utf-8"))
                self.assertIsNotNone(r)
                self.assertIn(r["source_id"], set(wr.TAG_TO_SOURCE.values()))
                if r["source_id"] in wr.EN_MI_SOURCE_IDS:
                    self.assertIsInstance(r["equivalents"], list)
                else:
                    self.assertIsInstance(r["gloss_en"], str)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONUTF8=1 py -m unittest tests.test_wakareo_records.BodyParsers -v`
Expected: FAIL — `AttributeError: module 'wakareo_records' has no attribute 'parse_record'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/wakareo_records.py`:

```python
TAG_TO_SOURCE = {
    "TE":  "tregear_exceptions",
    "HMN": "ngata",
    "TM":  "te_matatiki",
    "KKH": "kimikupu_hou",
    "HKA": "he_kupu_arotake",
    "HKR": "kupu_rorohiko",
    "TK":  "tai_kupu_variants",
    "NT":  "nga_tini_a_tangaroa",
    "KM":  "kupu_mataora",
    "CL":  "maori_law_lexicon",
    # "WWC" (Wordstream Williams Corpus) is deliberately absent — duplicate of
    # the NZETC-derived `williams` source, discarded at parse time.
}

EN_MI_SOURCE_IDS = frozenset(
    {"ngata", "kimikupu_hou", "he_kupu_arotake", "kupu_rorohiko", "kupu_mataora"}
)

_BR = re.compile(r"(?i)<BR\s*/?>")
_W_REF = re.compile(r"(?i)\bW\.(\d+)")
_DERIVATION = re.compile(r"(?s)(\[.*\])")


def _segments(body: str) -> list[str]:
    """Body split on <BR>, tags stripped, empties dropped."""
    return [s for s in (strip_tags(p) for p in _BR.split(body)) if s]


def _parse_en_mi(rec: dict, segs: list[str]) -> dict:
    """English headword -> comma-separated Māori equivalents, optional EN/MI pair."""
    equivalents = []
    if segs:
        equivalents = [e.strip() for e in segs[0].split(",") if e.strip()]
    rec["equivalents"] = equivalents
    rec["example_en"] = segs[1] if len(segs) > 1 else None
    rec["example_mi"] = segs[2] if len(segs) > 2 else None
    return rec


def _parse_mi_en(rec: dict, segs: list[str]) -> dict:
    """Māori headword -> English gloss (all remaining prose)."""
    rec["gloss_en"] = " ".join(segs) if segs else ""
    return rec


def _parse_te_matatiki(rec: dict, segs: list[str]) -> dict:
    """Like MI->EN, but a trailing [...] block is a derivation citing Williams pages."""
    derivation = None
    prose = list(segs)
    if prose and prose[-1].startswith("["):
        derivation = prose.pop()
    rec["gloss_en"] = " ".join(prose) if prose else ""
    rec["derivation"] = derivation
    rec["williams_refs"] = (
        [int(n) for n in _W_REF.findall(derivation)] if derivation else []
    )
    return rec


def parse_record(html: str) -> dict | None:
    """Full parse of one record page. None for Williams Corpus or a non-record."""
    slots = split_template(html)
    if slots is None:
        return None
    source_id = TAG_TO_SOURCE.get(slots["ref_tag"])
    if source_id is None:
        return None                      # WR-WWC and any future unknown tag

    rec = {
        "source_id": source_id,
        "ref_no": slots["ref_no"],
        "source_entry_id": f"WR-{slots['ref_tag']}.{slots['ref_no']}",
        "headword": slots["headword"],
        "pos": slots["pos"],
        "search_scope": parse_search_scope(slots["search_scope"]),
        "body_raw": slots["body"],
    }
    segs = _segments(slots["body"])
    if source_id in EN_MI_SOURCE_IDS:
        return _parse_en_mi(rec, segs)
    if source_id == "te_matatiki":
        return _parse_te_matatiki(rec, segs)
    return _parse_mi_en(rec, segs)
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONUTF8=1 py -m unittest tests.test_wakareo_records -v`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/wakareo_records.py tests/test_wakareo_records.py
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): per-component body parsers with EN/MI direction split"
```

---

### Task 3: Authenticated scraper

**Files:**
- Create: `scripts/41_wakareo_scrape.py`

**Interfaces:**
- Consumes: `utils.load_env`.
- Produces: raw HTML at `sources/wakareo/raw/{ID}.html` and `sources/wakareo/raw/manifest.json` with keys `fetched` (list of int), `empty` (list of int), `errors` (dict), `last_id` (int), `tag_counts` (dict).

This task has no unit test — it is I/O against a live subscription site. It is verified by a bounded smoke run.

- [ ] **Step 1: Write the scraper**

Create `scripts/41_wakareo_scrape.py`:

```python
"""Download Wakareo ā-ipurangi records by numeric ID.

Wakareo (reotupu.co.nz) is a subscription compilation of 11 dictionaries.
`Browse.aspx?ID={n}` returns ONE record as a plain authenticated GET — no
__VIEWSTATE postback needed for navigation. Every record carries a
`[Reference: WR-XX.n]` tag naming its component, so the sweep routes records
by what they say they are rather than by an assumed ID range.

IDs 1..25578 are the Wordstream Williams Corpus, a duplicate of the existing
NZETC-derived `williams` source. The sweep starts after them, and any record
that still reports WR-WWC is discarded rather than saved.

Credentials come from the gitignored .env via utils.load_env. Access is by
paid subscription plus written permission from Wordstream.

Usage:
  py scripts/41_wakareo_scrape.py                    # full run (~55k requests, ~23h)
  py scripts/41_wakareo_scrape.py --limit 200        # bounded smoke run
  py scripts/41_wakareo_scrape.py --from 47746 --to 47800   # targeted refetch
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# MUST precede `import requests`: Norton Antivirus intercepts TLS on this
# machine, so certifi cannot validate the chain but the Windows store can.
import truststore
truststore.inject_into_ssl()
import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_env

BASE = "https://reotupu.co.nz/WSLiveWakareo/"
LOGIN_URL = BASE + "login.aspx?ReturnUrl=%2fWSLiveWakareo%2f"
RAW_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "raw"
MANIFEST = RAW_DIR / "manifest.json"

HEADERS = {"User-Agent": "MaoriDictResearch/1.0 (rich@kaio.co.nz)"}
DELAY_SECONDS = 1.5
FIRST_NON_WILLIAMS_ID = 25_579
STOP_AFTER_EMPTY = 50          # consecutive empties => end of the ID space
SAVE_INTERVAL = 50
MAX_RETRIES = 3
RETRY_DELAY = 15

_HIDDEN = re.compile(r'(?is)<input[^>]*type="hidden"[^>]*>')
_REF = re.compile(r"(?is)\[Reference:\s*WR-([A-Z]+)\.(\d+)\]")


def _hidden_fields(html: str) -> dict:
    out = {}
    for tag in _HIDDEN.findall(html):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name:
            out[name.group(1)] = value.group(1) if value else ""
    return out


def login() -> requests.Session:
    creds = load_env("WAKAREO_USER", "WAKAREO_PASS")
    session = requests.Session()
    session.headers.update(HEADERS)
    page = session.get(LOGIN_URL, timeout=45)
    page.raise_for_status()
    form = _hidden_fields(page.text)
    form["Login1$UserName"] = creds["WAKAREO_USER"]
    form["Login1$Password"] = creds["WAKAREO_PASS"]
    form["Login1$LoginButton"] = "Log In"
    time.sleep(1)
    landing = session.post(page.url, data=form, timeout=45)
    if "login.aspx" in landing.url.lower():
        raise SystemExit(
            "ERROR: Wakareo login failed. Check WAKAREO_USER / WAKAREO_PASS in .env."
        )
    return session


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        "fetched": [], "empty": [], "errors": {},
        "last_id": FIRST_NON_WILLIAMS_ID - 1,
        "tag_counts": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def save_manifest(m: dict, fetched: set, empty: set, errors: dict) -> None:
    m["fetched"] = sorted(fetched)
    m["empty"] = sorted(empty)
    m["errors"] = errors
    m["last_saved"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")


def fetch(session: requests.Session, entry_id: int):
    """Return (html, session). Re-authenticates once on session expiry."""
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(BASE + f"Browse.aspx?ID={entry_id}", timeout=45)
            if "login.aspx" in r.url.lower():
                print("  session expired — re-authenticating")
                session = login()
                r = session.get(BASE + f"Browse.aspx?ID={entry_id}", timeout=45)
                if "login.aspx" in r.url.lower():
                    raise SystemExit("ERROR: re-login failed; aborting run.")
            r.raise_for_status()
            return r.text, session
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES - 1:
                return None, session
            print(f"  retry {attempt + 1}/{MAX_RETRIES} on ID {entry_id}: {exc}")
            time.sleep(RETRY_DELAY)
    return None, session


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Scrape Wakareo records by ID.")
    ap.add_argument("--limit", type=int, help="stop after N requests (smoke run)")
    ap.add_argument("--from", dest="start", type=int, help="first ID (default: resume)")
    ap.add_argument("--to", dest="end", type=int, help="last ID (inclusive)")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    fetched = set(manifest["fetched"])
    empty = set(manifest["empty"])
    errors = dict(manifest["errors"])
    tag_counts = dict(manifest["tag_counts"])

    entry_id = args.start if args.start else manifest["last_id"] + 1
    if entry_id < FIRST_NON_WILLIAMS_ID and not args.start:
        entry_id = FIRST_NON_WILLIAMS_ID

    session = login()
    print(f"Logged in. Sweeping from ID {entry_id}"
          + (f" to {args.end}" if args.end else "")
          + (f" (limit {args.limit})" if args.limit else ""))

    requests_made = 0
    consecutive_empty = 0
    try:
        while True:
            if args.end and entry_id > args.end:
                break
            if args.limit and requests_made >= args.limit:
                break
            if consecutive_empty >= STOP_AFTER_EMPTY:
                print(f"Stopping: {STOP_AFTER_EMPTY} consecutive empty IDs.")
                break

            path = RAW_DIR / f"{entry_id}.html"
            if entry_id in fetched or entry_id in empty:
                entry_id += 1
                continue

            html, session = fetch(session, entry_id)
            requests_made += 1
            time.sleep(DELAY_SECONDS)

            if html is None:
                errors[str(entry_id)] = "request failed"
                entry_id += 1
                continue

            ref = _REF.search(html)
            if not ref:
                empty.add(entry_id)
                consecutive_empty += 1
            else:
                tag = ref.group(1)
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                consecutive_empty = 0
                if tag == "WWC":
                    empty.add(entry_id)        # duplicate source — do not save
                else:
                    path.write_text(html, encoding="utf-8")
                    fetched.add(entry_id)

            manifest["last_id"] = entry_id
            manifest["tag_counts"] = tag_counts
            if requests_made % SAVE_INTERVAL == 0:
                save_manifest(manifest, fetched, empty, errors)
                print(f"  ID {entry_id}: {len(fetched):,} saved, "
                      f"{len(empty):,} skipped, {len(errors)} errors")
            entry_id += 1
    finally:
        save_manifest(manifest, fetched, empty, errors)
        print(f"\nSaved {len(fetched):,} records; skipped {len(empty):,}; "
              f"{len(errors)} errors.")
        print("Tag counts:", json.dumps(tag_counts, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke run — 200 records from the Ngata / Te Matatiki boundary**

```bash
PYTHONUTF8=1 py scripts/41_wakareo_scrape.py --from 47700 --to 47899
```

Expected: `Logged in.` then a tag-count summary showing **both** `HMN` and `TM` (the run crosses the Ngata→Te Matatiki boundary at ~47,746), roughly 200 files in `sources/wakareo/raw/`, zero errors.

If login fails, confirm `.env` holds real values: `PYTHONUTF8=1 py -c "import sys; sys.path.insert(0,'scripts'); from utils import load_env; print(sorted(load_env('WAKAREO_USER','WAKAREO_PASS')))"` — it prints only the key names, never the values.

- [ ] **Step 3: Verify the Williams discard path**

```bash
PYTHONUTF8=1 py scripts/41_wakareo_scrape.py --from 100 --to 109
ls sources/wakareo/raw/10*.html 2>/dev/null | wc -l
```

Expected: the tag summary counts `WWC: 10`, and the `ls` prints `0` — no Williams file was written.

- [ ] **Step 4: Commit**

```bash
git add scripts/41_wakareo_scrape.py
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): authenticated ID-sweep scraper with WR-tag routing"
```

---

### Task 4: Landing tables + source metadata

**Files:**
- Modify: `scripts/00_init_db.py` (add a `create_wakareo_tables` function; call it from the same place the other `create_*` functions are called; extend `seed_source_metadata`)

**Interfaces:**
- Consumes: nothing.
- Produces: ten tables and ten `source_metadata` rows, named exactly as in *The ten sources*.

- [ ] **Step 1: Add the table DDL**

Add to `scripts/00_init_db.py`, following the existing `CREATE TABLE IF NOT EXISTS` style. Two shapes — EN→MI and MI→EN — plus Te Matatiki's two extra columns:

```python
# --- Wakareo ā-ipurangi components (session 67) ---------------------------
# Ten landing tables, one per component dictionary. Each preserves its
# source's NATIVE lookup direction; 50_build_unified.py inverts the EN->MI
# ones so entry.headword is always Māori. These are the curated landing
# zone — cleanups edit them in place, never the JSON.

_WAKAREO_COMMON = """
            id              INTEGER PRIMARY KEY,
            source_entry_id TEXT NOT NULL UNIQUE,   -- 'WR-HMN.297'
            wakareo_id      INTEGER NOT NULL,       -- Browse.aspx?ID=n
            ref_no          INTEGER NOT NULL,       -- the n in WR-XX.n
            headword        TEXT NOT NULL,
            headword_sort   TEXT NOT NULL,
            headword_search TEXT NOT NULL,
            part_of_speech  TEXT,
            search_scope    TEXT,                   -- JSON array of authored variants
            body_raw        TEXT,
            content_hash    TEXT,
            first_seen      TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            last_updated    TEXT DEFAULT (datetime('now'))
"""

WAKAREO_EN_MI_TABLES = (
    "ngata_entries", "kimikupu_hou_entries", "he_kupu_arotake_entries",
    "kupu_rorohiko_entries", "kupu_mataora_entries",
)
WAKAREO_MI_EN_TABLES = (
    "tregear_exceptions_entries", "tai_kupu_variants_entries",
    "nga_tini_a_tangaroa_entries", "maori_law_lexicon_entries",
)


def create_wakareo_tables(conn: sqlite3.Connection) -> None:
    for table in WAKAREO_EN_MI_TABLES:
        conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {_WAKAREO_COMMON},
            equivalents     TEXT,                   -- JSON array of Māori terms
            example_en      TEXT,
            example_mi      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_{table}_search ON {table}(headword_search);
        CREATE INDEX IF NOT EXISTS idx_{table}_sort   ON {table}(headword_sort);
        """)
    for table in WAKAREO_MI_EN_TABLES:
        conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {_WAKAREO_COMMON},
            gloss_en        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_{table}_search ON {table}(headword_search);
        CREATE INDEX IF NOT EXISTS idx_{table}_sort   ON {table}(headword_sort);
        """)
    # Te Matatiki additionally carries a bracketed derivation citing Williams pages.
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS te_matatiki_entries (
        {_WAKAREO_COMMON},
        gloss_en        TEXT,
        derivation      TEXT,
        williams_refs   TEXT                        -- JSON array of Williams page ints
    );
    CREATE INDEX IF NOT EXISTS idx_te_matatiki_entries_search
        ON te_matatiki_entries(headword_search);
    CREATE INDEX IF NOT EXISTS idx_te_matatiki_entries_sort
        ON te_matatiki_entries(headword_sort);
    """)
```

Call `create_wakareo_tables(conn)` alongside the other `create_*` calls in the module's main/init function.

- [ ] **Step 2: Add the ten source_metadata rows**

Add to the `sources` list inside `seed_source_metadata`. The `licence` string names the asserted copyright holder from Wakareo's `Legal.aspx`; the notes record that none of these ship.

```python
        ("tregear_exceptions",  "Wordstream Tregear Exceptions",   "Wordstream Corporation (c) 2002",        "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; staging only — not exported to the app DB"),
        ("ngata",               "H.M. Ngata English-Maori Dictionary", "Whai Ngata; Learning Media 1993",    "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; staging only — not exported"),
        ("te_matatiki",         "Te Matatiki Contemporary Maori Words", "Te Taura Whiri (c) 1996; OUP written-permission clause", "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; staging only — not exported to the app DB"),
        ("kimikupu_hou",        "Kimikupu Hou modern words",       "NZCER; kaitiaki Te Taura Whiri",         "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; staging only — not exported"),
        ("he_kupu_arotake",     "He Kupu Arotake",                 "Crown copyright (c) 1995; Education Review Office", "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; staging only — not exported"),
        ("kupu_rorohiko",       "Kupu Rorohiko",                   "Te Taka Keegan; University of Waikato",  "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; Maori IT terms; English headword, inverted at unify; staging only — not exported"),
        ("tai_kupu_variants",   "Tai Kupu (Maori word variances)", "Wordstream Corporation (c) 2003",        "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; NOT the Maori Minute `taikupu` source; staging only — not exported"),
        ("nga_tini_a_tangaroa", "Nga tini a Tangaroa (fish names)","Ministry of Fisheries; Strickland",       "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; staging only — not exported to the app DB"),
        ("kupu_mataora",        "Kupu Mataora",                    "Not asserted in Wakareo Legal.aspx",     "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; English headword, inverted at unify; staging only — not exported"),
        ("maori_law_lexicon",   "Custom Maori Law Lexicon",        "Not asserted in Wakareo Legal.aspx",     "https://reotupu.co.nz/WSLiveWakareo/", None, 0, "Wakareo component; staging only — not exported to the app DB"),
```

- [ ] **Step 3: Back up, then run init and verify**

```bash
cp data/staging_dictionary.db data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-wakareo
PYTHONUTF8=1 py scripts/00_init_db.py
PYTHONUTF8=1 py -c "
import sqlite3
c = sqlite3.connect('data/staging_dictionary.db')
tables = {r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")}
want = ['ngata_entries','kimikupu_hou_entries','he_kupu_arotake_entries','kupu_rorohiko_entries','kupu_mataora_entries','tregear_exceptions_entries','tai_kupu_variants_entries','nga_tini_a_tangaroa_entries','maori_law_lexicon_entries','te_matatiki_entries']
missing = [t for t in want if t not in tables]
print('missing tables:', missing)
n = c.execute(\"SELECT COUNT(*) FROM source_metadata WHERE url LIKE '%WSLiveWakareo%'\").fetchone()[0]
print('wakareo source_metadata rows:', n)
"
```

Expected: `missing tables: []` and `wakareo source_metadata rows: 10`.

- [ ] **Step 4: Confirm re-running is idempotent**

Run: `PYTHONUTF8=1 py scripts/00_init_db.py && PYTHONUTF8=1 py -m unittest tests.test_schema -v`
Expected: PASS, no errors on the second init.

- [ ] **Step 5: Commit**

```bash
git add scripts/00_init_db.py
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): ten landing tables + source_metadata rows"
```

---

### Task 5: Parse driver + importer

**Files:**
- Create: `scripts/41_wakareo_parse.py`
- Create: `scripts/41_wakareo_import.py`

**Interfaces:**
- Consumes: `wakareo_records.parse_record`, `TAG_TO_SOURCE`, `EN_MI_SOURCE_IDS` (Task 2); the tables from Task 4.
- Produces: `sources/wakareo/parsed/{source_id}.json` — a JSON list of record dicts; and populated landing tables.

- [ ] **Step 1: Write the parse driver**

Create `scripts/41_wakareo_parse.py`:

```python
"""Parse scraped Wakareo HTML into one JSON file per component dictionary.

  py scripts/41_wakareo_parse.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wakareo_records import parse_record

RAW_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "raw"
OUT_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "parsed"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_source = defaultdict(list)
    skipped = 0

    files = sorted(RAW_DIR.glob("*.html"), key=lambda p: int(p.stem))
    for path in files:
        rec = parse_record(path.read_text(encoding="utf-8"))
        if rec is None:
            skipped += 1
            continue
        rec["wakareo_id"] = int(path.stem)
        by_source[rec["source_id"]].append(rec)

    for source_id, records in sorted(by_source.items()):
        out = OUT_DIR / f"{source_id}.json"
        out.write_text(
            json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"  {source_id:22s} {len(records):6,d} -> {out.name}")
    print(f"\nParsed {len(files):,} files; skipped {skipped:,}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the smoke-run data**

Run: `PYTHONUTF8=1 py scripts/41_wakareo_parse.py`
Expected: two lines — `ngata` and `te_matatiki` — with a combined count near 200, `skipped 0`.

- [ ] **Step 3: Write the importer**

Create `scripts/41_wakareo_import.py`:

```python
"""Import parsed Wakareo JSON into the ten landing tables.

Idempotent: INSERT OR REPLACE keyed on source_entry_id ('WR-HMN.297').

  py scripts/41_wakareo_import.py                 # every component found
  py scripts/41_wakareo_import.py --source ngata  # just one
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH, normalise_search_key, normalise_sort_key, compute_content_hash
from wakareo_records import EN_MI_SOURCE_IDS, TAG_TO_SOURCE

PARSED_DIR = Path(__file__).parent.parent / "sources" / "wakareo" / "parsed"

SOURCE_TO_TABLE = {sid: f"{sid}_entries" for sid in TAG_TO_SOURCE.values()}

BASE_COLS = ("source_entry_id", "wakareo_id", "ref_no", "headword", "headword_sort",
             "headword_search", "part_of_speech", "search_scope", "body_raw",
             "content_hash")


def row_for(rec: dict) -> tuple[tuple, tuple]:
    """Return (column_names, values) for one record, direction-aware."""
    hw = rec["headword"]
    base = (
        rec["source_entry_id"], rec["wakareo_id"], rec["ref_no"], hw,
        normalise_sort_key(hw), normalise_search_key(hw),
        rec["pos"] or None,
        json.dumps(rec["search_scope"], ensure_ascii=False),
        rec["body_raw"],
        compute_content_hash({"hw": hw, "body": rec["body_raw"]}),
    )
    if rec["source_id"] in EN_MI_SOURCE_IDS:
        return (BASE_COLS + ("equivalents", "example_en", "example_mi"),
                base + (json.dumps(rec["equivalents"], ensure_ascii=False),
                        rec["example_en"], rec["example_mi"]))
    if rec["source_id"] == "te_matatiki":
        return (BASE_COLS + ("gloss_en", "derivation", "williams_refs"),
                base + (rec["gloss_en"], rec["derivation"],
                        json.dumps(rec["williams_refs"])))
    return BASE_COLS + ("gloss_en",), base + (rec["gloss_en"],)


def import_source(con: sqlite3.Connection, source_id: str) -> int:
    path = PARSED_DIR / f"{source_id}.json"
    if not path.exists():
        return 0
    records = json.loads(path.read_text(encoding="utf-8"))
    table = SOURCE_TO_TABLE[source_id]
    n = 0
    for rec in records:
        cols, vals = row_for(rec)
        placeholders = ",".join("?" * len(vals))
        con.execute(
            f'INSERT OR REPLACE INTO {table} ({",".join(cols)}) VALUES ({placeholders})',
            vals,
        )
        n += 1
    con.commit()
    con.execute("UPDATE source_metadata SET entry_count=?, last_updated=datetime('now') "
                "WHERE source_id=?", (n, source_id))
    con.commit()
    return n


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Import parsed Wakareo JSON.")
    ap.add_argument("--source", action="append", choices=sorted(SOURCE_TO_TABLE),
                    help="component to import; repeatable. Default: all present.")
    args = ap.parse_args()
    targets = args.source or sorted(SOURCE_TO_TABLE)

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    total = 0
    for source_id in targets:
        n = import_source(con, source_id)
        total += n
        if n:
            print(f"  {source_id:22s} {n:6,d} rows")
    print(f"\nImported {total:,} rows.")
    con.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the import and verify**

```bash
PYTHONUTF8=1 py scripts/41_wakareo_import.py
PYTHONUTF8=1 py -c "
import sqlite3
c = sqlite3.connect('data/staging_dictionary.db')
for t in ('ngata_entries','te_matatiki_entries'):
    print(t, c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
print(c.execute('SELECT headword, equivalents, example_en FROM ngata_entries LIMIT 2').fetchall())
print(c.execute('SELECT headword, gloss_en, williams_refs FROM te_matatiki_entries LIMIT 2').fetchall())
"
```

Expected: non-zero counts for both; Ngata rows show a JSON `equivalents` array; Te Matatiki rows show `gloss_en` and a `williams_refs` array.

- [ ] **Step 5: Confirm the import is idempotent**

Run: `PYTHONUTF8=1 py scripts/41_wakareo_import.py` a second time, then re-check the two counts.
Expected: identical counts — `INSERT OR REPLACE` on `source_entry_id` must not duplicate.

- [ ] **Step 6: Commit**

```bash
git add scripts/41_wakareo_parse.py scripts/41_wakareo_import.py
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): parse driver and landing-table importer"
```

---

### Task 6: Unify builders with EN→MI inversion

**Files:**
- Modify: `scripts/50_build_unified.py:44` (import line), `:51` (`SOURCES`), `:402` (`BUILDERS`), plus new builder functions before `BUILDERS`

**Interfaces:**
- Consumes: the ten landing tables (Task 4/5); the existing `Builder` class (`add_entry`, `add_sense`, `add_example`, `add_form`, `add_relation`), `jload`.
- Produces: unified `entry`/`sense`/`example`/`form`/`relation` rows for the ten sources, with `entry.headword` always Māori.

- [ ] **Step 1: Extend the import line and the SOURCES tuple**

At `scripts/50_build_unified.py:44`, add `normalise_sort_key` (currently only `normalise_search_key` is imported):

```python
from utils import (DB_PATH, normalise_search_key, normalise_sort_key,
                   compute_content_hash)
```

At `:51`, extend `SOURCES`:

```python
WAKAREO_SOURCES = (
    "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
    "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
    "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
)
SOURCES = ("williams", "te_aka", "hepatakakupu", "paekupu", "papakupu",
           "taikupu") + WAKAREO_SOURCES
```

- [ ] **Step 2: Write the two generic builders**

Insert before the `BUILDERS` dict at `:402`:

```python
# --- Wakareo components (session 67) --------------------------------------
# Five components are English-headword. They are INVERTED here so
# entry.headword is always Māori: one entry per Māori equivalent, carrying the
# English lemma in headword_en, with siblings cross-linked as synonyms. The
# landing table keeps the true one-lemma-many-equivalents shape.
#
# Siblings share a WR- reference, so source_entry_id is suffixed '#1', '#2', …
# to stay distinct. Duplicate Māori headwords are NOT deduped — same rule as
# taikupu; homonym_no stays NULL.


def _wakareo_en_mi(con, b, table):
    sql = (f"SELECT source_entry_id, headword, part_of_speech, search_scope, "
           f"equivalents, example_en, example_mi, body_raw "
           f"FROM {table} ORDER BY id")
    for (seid, lemma_en, pos, scope, equivs, ex_en, ex_mi, raw) in con.execute(sql):
        equivalents = [e for e in jload(equivs) if e]
        if not equivalents:
            continue                      # nothing to hang a Māori headword on
        variants = jload(scope)
        siblings = []
        for i, mi in enumerate(equivalents, start=1):
            eid = b.add_entry(
                f"{seid}#{i}", mi, normalise_sort_key(mi), normalise_search_key(mi),
                pos=pos, headword_en=lemma_en,
                material={"hw": mi, "en": lemma_en, "ex": [ex_en, ex_mi]})
            sid = b.add_sense(eid, None, lemma_en, None, raw, part_of_speech=pos)
            b.add_example(sid, eid, ex_mi, ex_en, None, None, 0)
            for v in variants:
                b.add_form(eid, v, "variant")
            siblings.append((eid, mi))
        for eid, _ in siblings:
            for other_eid, other_mi in siblings:
                if other_eid != eid:
                    b.add_relation(eid, "synonym", other_mi, other_eid)


def _wakareo_mi_en(con, b, table, matatiki=False):
    extra = ", derivation, williams_refs" if matatiki else ""
    sql = (f"SELECT source_entry_id, headword, part_of_speech, search_scope, "
           f"gloss_en, body_raw{extra} FROM {table} ORDER BY id")
    for row in con.execute(sql):
        seid, hw, pos, scope, gloss, raw = row[:6]
        eid = b.add_entry(seid, hw, normalise_sort_key(hw), normalise_search_key(hw),
                          pos=pos, material={"hw": hw, "gloss": gloss})
        b.add_sense(eid, None, gloss, None, raw, part_of_speech=pos)
        for v in jload(scope):
            b.add_form(eid, v, "variant")
        if matatiki:
            derivation, refs = row[6], jload(row[7])
            for page in refs:
                b.add_relation(eid, "cross_ref", f"W.{page}", None,
                               note=(derivation or "")[:500])


def build_tregear_exceptions(con, b):  _wakareo_mi_en(con, b, "tregear_exceptions_entries")
def build_tai_kupu_variants(con, b):   _wakareo_mi_en(con, b, "tai_kupu_variants_entries")
def build_nga_tini_a_tangaroa(con, b): _wakareo_mi_en(con, b, "nga_tini_a_tangaroa_entries")
def build_maori_law_lexicon(con, b):   _wakareo_mi_en(con, b, "maori_law_lexicon_entries")
def build_te_matatiki(con, b):         _wakareo_mi_en(con, b, "te_matatiki_entries", matatiki=True)

def build_ngata(con, b):           _wakareo_en_mi(con, b, "ngata_entries")
def build_kimikupu_hou(con, b):    _wakareo_en_mi(con, b, "kimikupu_hou_entries")
def build_he_kupu_arotake(con, b): _wakareo_en_mi(con, b, "he_kupu_arotake_entries")
def build_kupu_rorohiko(con, b):   _wakareo_en_mi(con, b, "kupu_rorohiko_entries")
def build_kupu_mataora(con, b):    _wakareo_en_mi(con, b, "kupu_mataora_entries")
```

- [ ] **Step 3: Register them in BUILDERS**

Extend the `BUILDERS` dict at `:402`:

```python
BUILDERS = {
    "williams": build_williams,
    "te_aka": build_te_aka,
    "hepatakakupu": build_hepatakakupu,
    "paekupu": build_paekupu,
    "papakupu": build_papakupu,
    "taikupu": build_taikupu,
    "tregear_exceptions": build_tregear_exceptions,
    "ngata": build_ngata,
    "te_matatiki": build_te_matatiki,
    "kimikupu_hou": build_kimikupu_hou,
    "he_kupu_arotake": build_he_kupu_arotake,
    "kupu_rorohiko": build_kupu_rorohiko,
    "tai_kupu_variants": build_tai_kupu_variants,
    "nga_tini_a_tangaroa": build_nga_tini_a_tangaroa,
    "kupu_mataora": build_kupu_mataora,
    "maori_law_lexicon": build_maori_law_lexicon,
}
```

- [ ] **Step 4: Unify the two smoke-run sources and verify the inversion**

```bash
PYTHONUTF8=1 py scripts/50_build_unified.py --source ngata --source te_matatiki
PYTHONUTF8=1 py -c "
import sqlite3
c = sqlite3.connect('data/staging_dictionary.db'); c.row_factory = sqlite3.Row
print('-- ngata: headword must be MAORI, headword_en the English lemma --')
for r in c.execute(\"SELECT source_entry_id, headword, headword_en FROM entry WHERE source_id='ngata' LIMIT 5\"):
    print(dict(r))
print('-- synonym siblings --')
print(c.execute(\"SELECT COUNT(*) FROM relation r JOIN entry e ON e.id=r.entry_id WHERE e.source_id='ngata' AND r.rel_type='synonym'\").fetchone()[0])
print('-- te_matatiki williams cross-refs --')
print(c.execute(\"SELECT target_headword, substr(note,1,40) FROM relation r JOIN entry e ON e.id=r.entry_id WHERE e.source_id='te_matatiki' AND r.rel_type='cross_ref' LIMIT 3\").fetchall())
"
```

Expected: `headword` holds Māori text and `headword_en` holds English; `source_entry_id` ends in `#1`/`#2`; the synonym count is non-zero; Te Matatiki cross-refs read `W.<page>`.

- [ ] **Step 5: Confirm re-unifying is idempotent and FK-clean**

```bash
PYTHONUTF8=1 py scripts/50_build_unified.py --source ngata
PYTHONUTF8=1 py -m unittest tests.test_build_unified_fk tests.test_unified -v
```

Expected: PASS; the second unify reports the same entry count as the first.

- [ ] **Step 6: Commit**

```bash
git add scripts/50_build_unified.py
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): unify builders with EN-to-MI headword inversion"
```

---

### Task 7: Export exclusion + guard test

**Files:**
- Modify: `scripts/60_export_app_db.py:56-75` (add exclusion constants), `:118-122` (the copy loop)
- Create: `tests/test_wakareo_provenance.py`

**Interfaces:**
- Consumes: `WAKAREO_SOURCES` naming from Task 6.
- Produces: an app DB containing zero Wakareo rows.

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_wakareo_provenance.py`:

```python
"""Wakareo sources: provenance integrity in staging, absence from the app DB.

Assumes the pipeline has run:
    py scripts/41_wakareo_import.py
    py scripts/50_build_unified.py --source <each>
    py scripts/60_export_app_db.py
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

APP_DB = Path(__file__).parent.parent / "data" / "maori_dict.db"

WAKAREO_SOURCES = (
    "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
    "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
    "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
)

TAG_FOR_SOURCE = {
    "tregear_exceptions": "TE", "ngata": "HMN", "te_matatiki": "TM",
    "kimikupu_hou": "KKH", "he_kupu_arotake": "HKA", "kupu_rorohiko": "HKR",
    "tai_kupu_variants": "TK", "nga_tini_a_tangaroa": "NT",
    "kupu_mataora": "KM", "maori_law_lexicon": "CL",
}


class Provenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    def test_every_entry_carries_its_own_tag(self):
        for source_id, tag in TAG_FOR_SOURCE.items():
            with self.subTest(source=source_id):
                bad = self.con.execute(
                    "SELECT COUNT(*) FROM entry "
                    "WHERE source_id=? AND source_entry_id NOT LIKE ?",
                    (source_id, f"WR-{tag}.%"),
                ).fetchone()[0]
                self.assertEqual(bad, 0, f"{source_id} has {bad} mistagged entries")

    def test_no_williams_corpus_rows_landed(self):
        n = self.con.execute(
            "SELECT COUNT(*) FROM entry WHERE source_entry_id LIKE 'WR-WWC.%'"
        ).fetchone()[0]
        self.assertEqual(n, 0, "Wordstream Williams Corpus rows must never land")

    def test_en_mi_entries_have_maori_headword_and_english_lemma(self):
        for source_id in ("ngata", "kimikupu_hou", "he_kupu_arotake",
                          "kupu_rorohiko", "kupu_mataora"):
            with self.subTest(source=source_id):
                total = self.con.execute(
                    "SELECT COUNT(*) FROM entry WHERE source_id=?", (source_id,)
                ).fetchone()[0]
                if not total:
                    self.skipTest(f"{source_id} not imported yet")
                missing = self.con.execute(
                    "SELECT COUNT(*) FROM entry "
                    "WHERE source_id=? AND (headword_en IS NULL OR headword_en='')",
                    (source_id,),
                ).fetchone()[0]
                self.assertEqual(missing, 0)


class AppDbExclusion(unittest.TestCase):
    def test_no_wakareo_source_reaches_the_app_db(self):
        if not APP_DB.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(APP_DB)
        placeholders = ",".join("?" * len(WAKAREO_SOURCES))
        entries = con.execute(
            f"SELECT COUNT(*) FROM entry WHERE source_id IN ({placeholders})",
            WAKAREO_SOURCES,
        ).fetchone()[0]
        meta = con.execute(
            f"SELECT COUNT(*) FROM source_metadata WHERE source_id IN ({placeholders})",
            WAKAREO_SOURCES,
        ).fetchone()[0]
        con.close()
        self.assertEqual(entries, 0, "Wakareo entries leaked into the app DB")
        self.assertEqual(meta, 0, "Wakareo source_metadata leaked into the app DB")

    def test_app_db_has_no_dangling_relation_targets(self):
        if not APP_DB.exists():
            self.skipTest("app DB not built")
        con = sqlite3.connect(APP_DB)
        dangling = con.execute(
            "SELECT COUNT(*) FROM relation WHERE target_entry_id IS NOT NULL "
            "AND target_entry_id NOT IN (SELECT id FROM entry)"
        ).fetchone()[0]
        con.close()
        self.assertEqual(dangling, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify the exclusion test fails**

```bash
PYTHONUTF8=1 py scripts/60_export_app_db.py
PYTHONUTF8=1 py -m unittest tests.test_wakareo_provenance -v
```

Expected: `Provenance` tests PASS; `test_no_wakareo_source_reaches_the_app_db` FAILS — the export currently copies every row.

- [ ] **Step 3: Add the exclusion filter to the export**

In `scripts/60_export_app_db.py`, after the `APP_FTS` definition (~line 75):

```python
# Sources extracted from Wakareo ā-ipurangi. Wordstream licenses most components
# from third parties (see docs/superpowers/specs/2026-09-05-wakareo-extraction-design.md),
# so they are held in staging and never shipped. Removing a source_id from this
# tuple is a licensing decision, not a technical one.
EXCLUDED_SOURCES = (
    "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
    "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
    "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
)

_EXCL = ",".join(f"'{s}'" for s in EXCLUDED_SOURCES)
_KEPT_ENTRIES = f"(SELECT id FROM stg.entry WHERE source_id NOT IN ({_EXCL}))"

# WHERE clause applied when copying each table out of staging. Tables absent
# from this map are copied whole.
TABLE_FILTER = {
    "source_metadata": f"WHERE source_id NOT IN ({_EXCL})",
    "entry":           f"WHERE source_id NOT IN ({_EXCL})",
    "form":            f"WHERE entry_id IN {_KEPT_ENTRIES}",
    "sense":           f"WHERE entry_id IN {_KEPT_ENTRIES}",
    "example":         f"WHERE entry_id IN {_KEPT_ENTRIES}",
    "relation":        f"WHERE entry_id IN {_KEPT_ENTRIES}",
    "entry_domain":    f"WHERE entry_id IN {_KEPT_ENTRIES}",
    "ETY_entry_link":  f"WHERE entry_id IN {_KEPT_ENTRIES}",
}
```

Replace the copy line in the `for t in APP_TABLES:` loop:

```python
    for t in APP_TABLES:
        out.execute(_ddl(stg, t))
        where = TABLE_FILTER.get(t, "")
        out.execute(f'INSERT INTO main."{t}" SELECT * FROM stg."{t}" {where}')
        cnt = out.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0]
        print(f"  table  {t:<22} {cnt:>8,} rows")
```

Then, immediately after that loop, null out relation targets that pointed at excluded entries (otherwise `foreign_key_check` reports dangling refs):

```python
    # A kept entry may cross-reference an excluded one; drop the pointer, keep
    # the row (target_headword still carries the human-readable target).
    orphaned = out.execute(
        "UPDATE relation SET target_entry_id = NULL WHERE target_entry_id IS NOT NULL "
        "AND target_entry_id NOT IN (SELECT id FROM entry)"
    ).rowcount
    if orphaned:
        print(f"  nulled {orphaned:,} relation targets pointing at excluded sources")
```

- [ ] **Step 4: Re-export and verify the test passes**

```bash
PYTHONUTF8=1 py scripts/60_export_app_db.py
PYTHONUTF8=1 py -m unittest tests.test_wakareo_provenance -v
```

Expected: all PASS; the export prints `foreign_key_check: clean`.

- [ ] **Step 5: Confirm no previously-shipped source was lost**

```bash
PYTHONUTF8=1 py -c "
import sqlite3
c = sqlite3.connect('data/maori_dict.db')
for r in c.execute('SELECT source_id, COUNT(*) FROM entry GROUP BY source_id ORDER BY source_id'):
    print(r)
"
```

Expected: exactly the six pre-existing word-list sources — `hepatakakupu`, `paekupu`, `papakupu`, `taikupu`, `te_aka`, `williams` — with counts unchanged from before this work. No Wakareo source appears.

- [ ] **Step 6: Commit**

```bash
git add scripts/60_export_app_db.py tests/test_wakareo_provenance.py
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "feat(wakareo): exclude Wakareo sources from the app DB export"
```

---

### Task 8: Full extraction run + documentation

**Files:**
- Modify: `SESSIONS.md`, `DATABASE_REFERENCE.md`, `docs/UPDATE_WORKFLOW.md`, `.claude/skills/update-dictionary/SKILL.md`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: a complete extraction and updated trackers.

- [ ] **Step 1: Back up, then start the full sweep**

The sweep takes roughly 23 hours and is fully resumable — interrupt and rerun the same command at any time.

```bash
cp data/staging_dictionary.db data/staging_dictionary.db.bak-$(date +%Y%m%d-%H%M%S)-wakareo-full
PYTHONUTF8=1 py scripts/41_wakareo_scrape.py
```

Expected on completion: `Stopping: 50 consecutive empty IDs.` and a tag summary covering all ten non-Williams tags.

- [ ] **Step 2: Verify the tag counts against the spec's estimates**

```bash
PYTHONUTF8=1 py -c "
import json
from pathlib import Path
m = json.loads(Path('sources/wakareo/raw/manifest.json').read_text(encoding='utf-8'))
for tag, n in sorted(m['tag_counts'].items(), key=lambda kv: -kv[1]):
    print(f'{tag:5s} {n:7,d}')
print('files saved:', len(m['fetched']))
"
```

Expected: ten tags plus `WWC`; `HMN` and `KKH` are the two largest (~21,500 and ~22,500). Counts that differ from the spec's estimates by more than ~10% mean the ID ranges shifted — record the real numbers, the estimates were always provisional.

- [ ] **Step 3: Run the full pipeline**

```bash
PYTHONUTF8=1 py scripts/41_wakareo_parse.py
PYTHONUTF8=1 py scripts/41_wakareo_import.py
PYTHONUTF8=1 py scripts/50_build_unified.py --source tregear_exceptions --source ngata \
  --source te_matatiki --source kimikupu_hou --source he_kupu_arotake \
  --source kupu_rorohiko --source tai_kupu_variants --source nga_tini_a_tangaroa \
  --source kupu_mataora --source maori_law_lexicon
PYTHONUTF8=1 py scripts/08b_pollex_entry_linker.py --write --reset
PYTHONUTF8=1 py scripts/52_build_etymology_unified.py --reset
PYTHONUTF8=1 py scripts/06_fts_rebuild.py
PYTHONUTF8=1 py scripts/35_detect_pairs.py
```

`08b` and `52` are mandatory after any unify — `50_build_unified.py` clears the entry-link tables it depends on, and the app DB ships only the `ETY_*` layer.

- [ ] **Step 4: Persist any new POS values to the durable seed**

Wakareo contributes 35 POS values. Most are already-known atomic terms (`noun`,
`transitive verb`, …) that `resolve_pos` maps via `std_pos`; genuinely new ones arrive as
`needs_review`. `std_pos` lives in the gitignored DB, so decisions must be dumped to the
committed seed or a from-scratch rebuild loses them.

```bash
PYTHONUTF8=1 py -c "
import sqlite3
c = sqlite3.connect('data/staging_dictionary.db')
rows = c.execute(\"SELECT raw_pos, source_counts FROM std_pos WHERE status='needs_review' ORDER BY raw_pos\").fetchall()
print(f'{len(rows)} POS values need review:')
for raw, counts in rows[:40]:
    print(f'  {raw!r:32s} {counts}')
"
```

Map any new atomic codes by editing `std_pos` directly (combos auto-compose), for example:

```sql
UPDATE std_pos SET canonical_en='Noun', canonical_mi='Tūingoa', status='reviewed'
WHERE raw_pos='noun';
```

Then bake and persist:

```bash
PYTHONUTF8=1 py scripts/50_build_unified.py --source ngata
PYTHONUTF8=1 py scripts/16_dump_std_pos_seed.py
git add seeds/std_pos_seed.csv
```

Expected: `seeds/std_pos_seed.csv` gains rows for any codes you reviewed. If the review list
is empty, skip the edits and the dump — Wakareo introduced no new POS codes.

- [ ] **Step 5: Run the whole test suite**

Run: `PYTHONUTF8=1 py -m unittest discover -s tests -p "test_*.py"`
Expected: all green. Investigate any failure before continuing — do not proceed to export on a red suite.

- [ ] **Step 6: Export and confirm the app DB is untouched by this work**

```bash
PYTHONUTF8=1 py scripts/60_export_app_db.py
PYTHONUTF8=1 py -m unittest tests.test_wakareo_provenance -v
```

Expected: PASS, and the per-source counts printed by the export match the six pre-existing sources only.

- [ ] **Step 7: Update the trackers**

- **`SESSIONS.md`** — add a row: session 67, date 2026-09-05, sources added (all ten with their real row counts from Step 2), what changed, and the note that nothing ships pending licence clearance.
- **`DATABASE_REFERENCE.md`** — document the ten landing tables and their columns, and the ten new `source_metadata` rows. Note in the export section that `EXCLUDED_SOURCES` filters them out.
- **`docs/UPDATE_WORKFLOW.md`** — add a Wakareo per-source recipe (scrape → parse → import → unify) and add the ten rows to the *Quick reference* table.
- **`.claude/skills/update-dictionary/SKILL.md`** — add the ten sources to the source/unify mapping table, with a note that they are staging-only.

- [ ] **Step 8: Commit**

```bash
git add SESSIONS.md DATABASE_REFERENCE.md docs/UPDATE_WORKFLOW.md \
  .claude/skills/update-dictionary/SKILL.md seeds/std_pos_seed.csv
git -c user.name="Richard Kaio" -c user.email="Richard.Kaio+GITFNDC@fndc.govt.nz" \
  commit -m "docs(wakareo): record session 67 extraction and update trackers"
```
