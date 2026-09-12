# Concept Layer — design

**Date:** 2026-09-12 · **Status:** approved, not yet implemented

A concept is **one word, as eleven dictionaries record it**. `hiwi` "ridge of a
hill" is a single concept whose witnesses are `williams:1251#1`, `te_aka:1284#1`,
`papakupu:442#1` and two He Pātaka Kupu senses. The layer exists to deduplicate
the corpus, to elect a canonical spelling (which is what D18 has been waiting
for), and to give the sweep a better unit of work than a headword cluster.

It groups. It never merges, rewrites or deletes a source entry — the rubric's
ruling that "identity findings produce concept membership, not deletions".

---

## 1. What a concept is not

**Not a synonym set.** This distinction was got wrong once already and is worth
stating plainly, because the corpus's richest evidence is on the other side of
it.

He Pātaka Kupu publishes a `master_definition` pointer on 14,370 senses (D35),
and 14,298 of them point at a **different headword** — `itinga` → `tamarikitanga`,
`aewa` → `matemate`. It is a synonym-set marker. So is the shared-definition
convention behind D34: `aho` and `au` carry one definition because they are
synonyms, not because they are one word.

Both findings are sound and both resolve real references. What was wrong was
reading them as evidence of *word identity*. They are evidence of *shared
meaning*, and a sense-set layer built on them would be well-evidenced and cheap
— but it would not deduplicate the corpus or settle a single macron.

**Not a sense inventory.** A concept has members; it does not yet model its own
senses. `williams:1251#1` (ridge) and `#2` (line of descent) both join the
`hiwi`-ridge concept. Structuring senses *within* a concept is deferred (§9).

---

## 2. Why the evidence is thin, and what follows

Within a source, identity is stated: each source groups its own senses into
words. Across sources it must be inferred.

| | Evidence | Volume |
|---|---|---|
| same meaning | master pointers · shared definitions · synonym relations | 14,298 · 3,763 · ~144,000 |
| **same word** | te_matatiki→williams citations · shared example sentences on one key · cognate sets spanning sources | **5,503 · 867 · 11,029 sets** |

Only 5,503 resolved relations cross a source boundary at all, and every one is
te_matatiki→williams.

Two consequences the design accepts rather than works around:

- Most cross-source memberships will land at `probable`, on gloss overlap.
- Many concepts will be singletons. A singleton is **correct**; a premature
  merge is a visible error in a dictionary whose users will notice.

Scale: 175,101 senses and 55,765 headword keys, of which 36,319 are
single-source and 19,446 span two or more.

The sweep queue holds 55,827 rows against those 55,765 keys. The 62 extra are
dead: they are D31's truncated Ngata fragments — `atawhait`, `kairangit`,
`ngot` — queued before D31 removed the entries that produced them. They should
be pruned from `sweep_cluster` when this lands.

---

## 3. Schema

```sql
CREATE TABLE concept (
    id                INTEGER PRIMARY KEY,
    status            TEXT NOT NULL,   -- proposed | confirmed | rejected
    confidence        TEXT NOT NULL,   -- certain | probable | uncertain
    -- Elected, never written. Each value names the member it came from.
    headword          TEXT,
    headword_from     INTEGER REFERENCES concept_member(id),
    gloss_en          TEXT,
    gloss_en_from     INTEGER REFERENCES concept_member(id),
    gloss_mi          TEXT,
    gloss_mi_from     INTEGER REFERENCES concept_member(id),
    created_at        TEXT,
    last_updated      TEXT
);

CREATE TABLE concept_member (
    id                INTEGER PRIMARY KEY,
    concept_id        INTEGER NOT NULL REFERENCES concept(id),
    -- Stable addressing. entry_id/sense_id are a CACHE, re-resolved after every
    -- 50_build_unified, because entry.id is volatile across rebuilds.
    source_id         TEXT NOT NULL,
    source_entry_id   TEXT NOT NULL,
    sense_number      INTEGER,
    entry_id          INTEGER REFERENCES entry(id),
    sense_id          INTEGER REFERENCES sense(id),
    status            TEXT NOT NULL,   -- proposed | confirmed | rejected
    confidence        TEXT NOT NULL,
    created_at        TEXT,
    UNIQUE (concept_id, source_id, source_entry_id, sense_number)
);

CREATE TABLE concept_member_evidence (
    id                INTEGER PRIMARY KEY,
    member_id         INTEGER NOT NULL REFERENCES concept_member(id),
    kind              TEXT NOT NULL,
    detail            TEXT NOT NULL,   -- the specific reason, in words
    weight            REAL NOT NULL
);
```

Evidence is a table, not a column, because a membership usually has several
independent reasons and the sweep must see them separately to judge.

`status` lives on both concept and member: a concept can be confirmed while one
member is still proposed, which is the common case.

---

## 4. Evidence model

### Positive, strongest first

| Kind | What it is | Confidence |
|---|---|---|
| `cites_source` | Te Matatiki citing `hīmoemoe W.50`, resolved to the Williams entry | certain |
| `shared_example` | two sources printing the same Māori sentence under one key | certain |
| `attributed_quote` | Te Aka citing `W 1971:54` / He Pātaka Kupu on one key | probable |
| `shared_cognate_set` | one key, and both senses carry the same cognate set | probable |
| `gloss_overlap` | one key, compatible POS, glosses sharing content words | probable |

The `gloss_overlap` threshold is the one tuning parameter here. It is set during
implementation by measuring against the judged calibration clusters (§8.4) and
recorded in the builder, not left to taste: too loose merges homographs, too
tight leaves every cross-source pair a singleton.

**Same `headword_search` alone is never evidence.** It generates candidates.
Nothing more. The key is macron-blind and homograph-blind: `hiwi` is eight words
on one key, and `hia`/`hīa` share a key only because macrons are stripped.

### Negative evidence blocks a membership

First-class, and the safety mechanism of the whole design.

- **A source's own homograph numbering.** Williams files `Hiwi` as 1250, 1251,
  1252 — that is Williams stating these are different words. Senses from
  different Williams entries must not share a concept without a positive
  override.
- **Macron disagreement with no other link.** `hia` vs `hīa`.
- **Incompatible part of speech.**
- **Disjoint glosses.**

### Confidence

The strongest positive kind present, **downgraded to `uncertain` if any negative
evidence applies**. A concept never rises above the weakest of its confirmed
members.

---

## 5. Formation — seed and attach

### Step 1: single-source lexemes seed the concepts

Each source groups its own senses into words, differently. This is stated
structure, so seeds are `certain` unless noted:

```
williams, te_aka   one entry = one lexeme
hepatakakupu       entry.locator 'word_id=N' groups the senses
papakupu           headword + its sense run (D37 landed the numbers)
paekupu            one entry per sense, kept apart by subject domain
ngata              headword within the source — PROBABLE, not certain: right
                   for 'hoatu' (14 rows, one word, 13 English lemmas) but it
                   would merge two genuine Ngata homographs, and nothing in
                   Ngata's structure would say otherwise
```

### Step 2: cross-source attachment, without transitivity

Within a `headword_search` key, a seed joins a concept only when:

1. it has **positive evidence linking it to the concept** — not merely to one
   member; and
2. **no negative evidence holds against any existing member**.

Clause 2 is the anti-chaining rule. If `hiwi`(ridge) and `hiwi`(jerk) are
separated by Williams's numbering, no third source compatible with each can
later join them. It is the discipline of D29 and D34 — *accept only when exactly
one reading survives* — applied to membership.

### Step 3: the remainder are singletons

A seed with no qualifying attachment becomes a one-source concept.
`paekupu:hoi` "soy, soya" genuinely is its own word.

---

## 6. Election — and D18

Each concept elects a canonical `headword`, `gloss_en` and `gloss_mi`, each
recording the member that supplied it. **The elected value is always a string
some member actually wrote.** Never composed. This is what lets the corpus state
a canonical form without inventing lexicographic content.

### Headword, in order

1. **Morphological evidence.** If `derivation` (D38, 6,778 rows) says the word is
   base + affix and the base is macronised, that settles it. `hōmai` is long
   because it is `hō` + `mai`.
2. **Macron-informative preference.** Where members disagree, prefer the
   macronised spelling. The evidence is asymmetric: a source marking length
   makes a claim; a source omitting it may simply not mark length. Williams 1957
   is the case in point.
3. **Source precedence, tie-break only** — te_aka (1,943), hepatakakupu (1,530),
   ngata (1,075), per D18.

**Where no member macronises, no macron is elected.** A Williams-only concept
keeps its unmacronised spelling and the gap stays visible. That is D18's 2,297,
honestly reported rather than guessed at.

### Glosses

`gloss_en` by source precedence, verbatim. `gloss_mi` from hepatakakupu where a
member is there — the only substantial Māori-gloss source, 24,900 senses.

**Ngata must never supply `gloss_en`.** Its gloss is the English *lemma the word
was listed under*, not a definition: `huripari`, a hurricane, is glossed `Wind`
because it sits in a list of fifteen named winds. Ranking Ngata anywhere but
last would put that in front of users as the definition.

---

## 7. Integration

### Sweep — reuses everything

No new queue. `sweep_batch.assemble` gains a CONCEPTS section — members,
evidence, elected forms — and the runner's payload gains `concept_actions`
nested inside findings exactly as patches already nest: confirm a membership,
reject one, split a concept, merge two. Queue, runner, findings log, rubric and
the 121 findings already recorded keep working.

### App export

`concept` and `concept_member` join `APP_TABLES`; the evidence table stays in
staging as sweep-facing detail. Export is filtered to
`status = 'confirmed' OR confidence IN ('certain','probable')`, so an uncertain
grouping cannot reach users by accident.

### Rebuild — the one real departure

`derivation` and `loan_origin` are pure projections, deleted and rebuilt.
`concept_member` will hold **sweep judgements**, which must survive a rebuild.
So:

- membership is keyed on `(source_id, source_entry_id, sense_number)`;
  `entry_id`/`sense_id` are re-resolved after each build (the `sweep_patch`
  pattern);
- the builder adds or updates rows still `proposed`, and **never** overwrites
  `confirmed` or `rejected`.

### Fixing the derived-chain foot-gun

The chain is now `52 → 08b → 53 → 54 → 60`. It has been got wrong twice in one
session — tests run against a half-rebuilt DB, and an app DB left 12 MB short.
A single `59_rebuild_derived.py` runs them in order, and a test asserts the app
DB is not stale against staging.

---

## 8. Testing

1. **Unit** — scoring, block rules, election, all pure.
2. **Fixture DB** — attachment, non-transitivity, each block rule, and that a
   rebuild preserves `confirmed` members while refreshing `proposed` ones.
3. **Invariants** — no sense in two concepts; no elected headword that no member
   wrote; no two senses from different Williams entries in one concept without a
   recorded override.
4. **Acceptance, from the 21 judged calibration clusters.** These are real,
   already-reasoned answers:
   - `hiwi` yields eight concepts, not one
   - `hia` does not put `hia` and `hīa` together
   - `himoemoe` unifies six sources into one
   - `hoi` separates ten words, and `paekupu:hoi` "soy" stays alone
   - `homai` elects `hōmai`, from morphology

---

## 9. Out of scope

- **Senses within a concept.** Members are senses; the concept does not yet
  order or merge them.
- **The synset layer.** Well-evidenced and cheap (§1), but it is a different
  layer for a different purpose, and it is not what dedup or D18 need.
- **Editorial override.** No field for a canonical form no source wrote.
  Election chooses among witnesses only.
- **Cross-source relation resolution.** Unchanged; `resolve_*` still refuses to
  guess.

---

## 10. Sequence

1. Schema, and the formation builder (`54_build_concepts.py`) — seeds and
   attachment, everything `proposed`.
2. Election.
3. Sweep integration — batch section and `concept_actions`.
4. App export at the confidence threshold.
5. `59_rebuild_derived.py` and the staleness test.

Steps 1–2 deliver dedup and D18. Step 3 makes the remaining clusters tractable. Step 4 is what users see.
