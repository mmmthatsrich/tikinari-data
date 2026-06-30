# Feature Spec — Word Etymology / Ancestry Tree

**Audience:** implementing agent. **Stack:** agnostic (SQL + JSON contract + UI behaviour; no framework code).
**DB:** `data/maori_dict.db` (SQLite, WAL). Schema in `DATABASE_REFERENCE.md` — see "Etymology Layer".

---

## 1. What it does

Given a Māori headword, show its etymological ancestry as a tree:

- **Top (wide):** the word's same-level cognates — other Polynesian/Oceanic languages that share the reflex, grouped by subgroup.
- **Climbing down:** ancestral reconstructions, level by level, back as far as the data asserts (e.g. `CE → AN → POc → PAn`).

Sparse **by design** — most words are terminal (only ~1,189 of 2,931 climb higher; 325 reach Proto-Austronesian/ACD). A word with no ancestry is correct, not broken.

### Worked example — `wahine`
```
CE.WAHINE  [CE]  "Woman, female"          ← headword node
 └─ AN.FAFINE [AN] "Woman, female"   (descends)
     ├─ POc *papine "woman"  (LPO)   (descends)
     └─ PAn *bahi  "female"  (ACD)   (descends)
```

---

## 2. Data model (read-only)

Tables (full detail in `DATABASE_REFERENCE.md`):

| Table | Role |
|---|---|
| `pollex_cognatesets` | nodes (protoforms). `origin` = `maori_reflex` (searchable) \| `ancestor_only` (tree-only) |
| `protoform_ancestry` | directed child→ancestor edges (~1,599). `ancestor_kind` ∈ `pollex`/`lpo`/`acd` routes `ancestor_id` to its table |
| `lpo_cognatesets`, `acd_cognatesets` | external proto nodes (Proto-Oceanic; Proto-Austronesian/MP) |
| `pollex_reflexes` | per-language reflexes (the horizontal axis) |
| `pollex_entry_links` | unified `entry` → `cognateset_id` (the entry point: resolve a looked-up word to its tree without text matching) |
| `pollex_languages` | language → subgroup/region (groups the horizontal axis) |
| `reconstruction_levels` | level ladder; `depth_rank` orders the vertical axis (bigger = more recent) |

**Edge semantics:**
- `relation`: `descends` (solid line) \| `cf` (POLLEX "compare" — render tentative/greyed).
- `confidence`: `0.95` curated/`<<` · `0.75` internal `Cf.` · `0.7` name-matched external. Use to style certainty.

---

## 3. Queries (already designed — copy verbatim)

**Resolve headword → cognateset_id (preferred):** from a unified `entry` the user
looked up, join `pollex_entry_links` directly — no text matching needed:
```sql
SELECT pel.cognateset_id
FROM pollex_entry_links pel
WHERE pel.entry_id = :entry_id;
```
(One entry may map to several cognatesets — homonyms; render each as its own tree.)
Fallback when you only have a raw word: look it up in `pollex_entries` /
`pollex_reflexes` and take its `cognateset_id`.

**A. Horizontal — same-level cognates:**
```sql
SELECT r.language, pl.subgroup, r.reflex, r.gloss, te.audio_url
FROM pollex_reflexes r
LEFT JOIN pollex_languages pl ON pl.language_slug = r.language_slug
WHERE r.cognateset_id = :cognateset_id
ORDER BY pl.subgroup, r.language;
```

**B. Vertical — recursive climb:**
```sql
WITH RECURSIVE up(child_id, ancestor_kind, ancestor_id, ancestor_level, relation, confidence, depth) AS (
    SELECT child_id, ancestor_kind, ancestor_id, ancestor_level, relation, confidence, 1
        FROM protoform_ancestry WHERE child_id = :cognateset_id
    UNION ALL
    SELECT a.child_id, a.ancestor_kind, a.ancestor_id, a.ancestor_level, a.relation, a.confidence, up.depth + 1
        FROM protoform_ancestry a
        JOIN up ON a.child_id = up.ancestor_id AND up.ancestor_kind = 'pollex'
)
SELECT * FROM up ORDER BY depth, confidence DESC;
```
Resolve each ancestor node by `ancestor_kind`: `pollex`→`pollex_cognatesets`, `lpo`→`lpo_cognatesets`, `acd`→`acd_cognatesets`.

> Recursion only follows `ancestor_kind='pollex'` (internal). `lpo`/`acd` are leaf nodes — terminal by nature.

---

## 4. API contract (stack-agnostic JSON)

`GET /etymology/{headword}` → 200:

```json
{
  "headword": "wahine",
  "cognateset_id": "wahine",
  "found": true,
  "root": {
    "id": "wahine",
    "level": "CE",
    "level_name": "Central-Eastern Polynesian",
    "form": "WAHINE",
    "gloss": "Woman, female",
    "kind": "pollex",
    "cognates": [
      { "language": "Hawaiian", "subgroup": "Eastern Polynesian", "reflex": "wahine", "gloss": "woman", "audio_url": null }
    ],
    "ancestors": [
      {
        "id": "fafine", "level": "AN", "level_name": "Proto-Austronesian",
        "form": "FAFINE", "gloss": "Woman, female", "kind": "pollex",
        "relation": "descends", "confidence": 0.95,
        "ancestors": [
          { "id": "...", "level": "POc", "form": "papine", "gloss": "woman", "kind": "lpo", "relation": "descends", "confidence": 0.95, "ancestors": [] },
          { "id": "...", "level": "PAn", "form": "bahi",   "gloss": "female", "kind": "acd", "relation": "descends", "confidence": 0.7,  "ancestors": [] }
        ]
      }
    ]
  }
}
```

Rules:
- `found:false` with `root:null` when the headword has no POLLEX cognateset (common — handle gracefully).
- `ancestors:[]` = terminal node (most words). Not an error.
- Server builds the nested tree from query B's flat rows (group children under their `ancestor_id`).
- `cognates` only on the root node (horizontal axis is same-level — top of tree only).

---

## 5. UI behaviour (framework-neutral)

**Layout:** vertical tree, root (headword) at top, ancestors descending. Each node shows: level badge, form (italic, `*`-prefixed for external proto), gloss.

**Node states:**
- `relation='cf'` → render dashed/greyed edge + "cf." tag (tentative).
- `confidence < 0.8` → subtle "uncertain" affordance (lighter weight / tooltip).
- `kind='lpo'`→ tag "LPO / Proto-Oceanic"; `kind='acd'`→ "ACD / Proto-Austronesian". Source attribution required (CC-BY-4.0).

**Cognates (root):** collapsible, grouped by `subgroup` headers. Audio play button when `audio_url` present.

**Empty/edge cases:**
- No ancestry → show root + cognates only, with a one-line "No deeper reconstruction recorded" note (NOT an error/empty state).
- No cognates and no ancestry → still show the headword node alone.
- Branching ancestors (multiple at one level, e.g. LPO + ACD siblings) → render as sibling branches.

**Interactions:** tap a `pollex` node → navigate to that protoform as new root (re-query). External (`lpo`/`acd`) nodes are leaves — show detail popover, no navigation.

**Attribution footer (required):** POLLEX (permission pending), LPO (CC-BY-4.0), ACD (CC-BY-4.0).

---

## 6. Out of scope
- Morphological decomposition (splitting `whaka-` + `māori`) — different feature, no data.
- Editing/curating ancestry edges — read-only.
- The `etymology_links` table is the *source* of some ancestry edges; the app reads `protoform_ancestry`, not `etymology_links` directly.

## 7. Acceptance
- `wahine` renders the 4-node tree in §1.
- A terminal word (e.g. a `CE`-only innovation) renders root + cognates, no error.
- `cf` edges visually distinct from `descends`.
- LPO/ACD nodes attributed; recursion never loops (only follows `pollex` kind).
