# Historical Dictionary Curation Guide

How to provide modern Māori headwords for Maunsell (1862) and He Karao (~1815) OCR entries.
Only approved entries are imported into the database.

---

## One-time setup: macron input on Windows

Pick one method:

**Option A — Māori keyboard layout (best for bulk work)**
1. Settings → Time & Language → Language → English (New Zealand) → Options
2. Add keyboard → **Māori**
3. Switch layouts with `Win` + `Space`
4. Backtick then vowel: `` `a `` = ā · `` `e `` = ē · `` `i `` = ī · `` `o `` = ō · `` `u `` = ū

**Option B — Windows symbol picker**
Press `Win` + `.`, go to the Symbols tab, find the vowel.

**Option C — Copy-paste reference**
Keep this line handy: `ā ē ī ō ū Ā Ē Ī Ō Ū`

---

## Running the curation script

Open a terminal in the project folder:

```
cd "C:\Local Git\Dictionaries"
```

### Maunsell (start here — better OCR quality)

```
py scripts/25c_curate.py --source maunsell --skip-name-only
```

`--skip-name-only` skips the 144 entries that are purely "Name of a person".

### He Karao (noisier — do after Maunsell)

```
py scripts/25c_curate.py --source hekarao --min-conf 60
```

`--min-conf 60` filters to higher-confidence entries (~200). Lower to 50 or 40 to see more.

---

## At each entry

```
-------------------------------------------------------
Page 182  pos: s.
OCR:  "Aho"
Def:  A fishing-line, any line.

[1/1923] Modern Maori form  [Enter=skip  d=discard  q=quit  ?=more]:
```

| Input | Action |
|-------|--------|
| `āho` + Enter | **Approve** — stored with modern headword `āho` |
| Enter alone | **Skip** — stays in queue for next session |
| `d` + Enter | **Discard** — OCR noise, garbled entry, not a real word |
| `?` + Enter | **More** — shows full definition and usage examples |
| `q` + Enter | **Quit** — saves progress, safe to stop any time |

**Decide rules:**
- Recognise the word and can give the modern spelling → approve it
- Garbled OCR nonsense (`Adu mia mai`, `2.2.5`, `rol`, `ee`) → discard it
- Unsure → skip it and come back later
- You are only providing the modern **headword** — the definition stays as OCR'd

Progress is saved after every single decision. Quit any time and resume where you left off.

---

## Check progress

```
py -c "
import sys, json; sys.stdout.reconfigure(encoding='utf-8')
for src in ['maunsell', 'hekarao']:
    cur = json.load(open(f'sources/{src}/curated/{src}_curation.json', encoding='utf-8'))
    approved  = sum(1 for v in cur.values() if v['status'] == 'approved')
    discarded = sum(1 for v in cur.values() if v['status'] == 'discarded')
    print(f'{src}: {approved} approved, {discarded} discarded')
"
```

---

## Import to database

Once you have a batch of approved entries, run (session 26 scripts):

```
py scripts/26a_maunsell_import.py
py scripts/26b_hekarao_import.py
```

Re-run any time to refresh the database with your latest approvals.

---

## Curation files

Stored at:
- `sources/maunsell/curated/maunsell_curation.json`
- `sources/hekarao/curated/hekarao_curation.json`

These are plain JSON — you can also hand-edit them directly if needed.
