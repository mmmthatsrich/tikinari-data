# Word Formation — design note

**Question.** Can the app show where a Māori word came from *within Māori* — that
`hīmoemoe` is `hī-` + `moemoe`, that `Ahopae` is `aho` + `pae`, that
`whakamātau` is the causative of `mātau`?

**Short answer.** Most of the decomposition is already extracted and already
resolved — 9,501 component references pointing at real entries — but it is
stored as `cross_ref`, the same relation type as "see also", so nothing can tell
a component from a cross-reference. Separately, 7,142 entries show no ancestry
at all, because the etymology layer matches on spelling: `moe` carries five
cognate sets and `moemoe` carries none.

---

## 1. What the corpus holds today

| Fact | Recorded? | Where |
|---|---|---|
| This word is built from these parts | **yes, but untyped — 9,501 resolved references** | `relation.rel_type = 'cross_ref'` |
| …in this order | **no** | not modelled |
| …by this process (causative, nominalisation, …) | **almost never — 221** | papakupu `part_of_speech` = `'Causative'`, `'Derived Noun'` |
| What each component means | **yes — 6,517** | `relation.note`, as free text |
| The base's own descent from Proto-Polynesian | yes for the base, invisible from the derived form | `ETY_*` |

Three sources state word formation, each in its own shape:

    te_matatiki  "Latitude [aho W.3 'string, line, cross threads of a mat'
                            pae W.244 'horizontal ridges, circumference']"
    paekupu      "(ara) whakaako wetehere"  ->  note 'wete - to release, set free'
                                            ->  note 'here - tie, shackle'
    papakupu     part_of_speech = 'Causative'                      (221 senses)
    tregear      "MOE, to sleep; moega, a bed"                     (prose only)

Te Matatiki is the richest: 1,639 senses cite two or more Williams headwords
inside their bracketed source note, and 1,928 entries already carry two or more
**resolved** component references. Paekupu adds 606 more. Its notes are the only
place in the corpus where a component's Māori form and its English gloss sit
together as data.

### The relation type is the whole problem

`te_matatiki:Ahopae` has two `cross_ref` rows, to `aho` and to `pae`. A Williams
entry meaning "see also `kaikōmako`" has a `cross_ref` row too. Same type,
opposite relationship — one says *this word is made of that*, the other says
*look over there*. An app cannot render them differently, and neither can the
concept layer.

---

## 2. The 7,142 entries that lose their ancestry

`hīmoemoe` is the case in point, and it is not an obscure one — six sources
carry it and they all agree.

- Te Matatiki states the derivation: `hīmoemoe W.50 'acid, sour'`,
  `moemoe W.205 'sour, acid, i.e., causing one to close the eyes'`.
- Both cross-references **resolve correctly**, to `williams:1163` and
  `williams:1503304`.
- `moemoe` carries **0** cognate sets.
- `moe` carries five: POLLEX `MP.MOHE` 'Sleep', two Tregear `MOE` entries, and
  ABVD `tosleep-10` / `tosleep-109`.

So the chain `hīmoemoe → moemoe → moe → *mohe` is present in the corpus in three
separate places and joined in none of them.

Measured across the whole corpus — keys whose morphological base is itself an
entry:

| Class | Keys | Entries | Safe to derive? |
|---|---:|---:|---|
| `whaka-` causative | 1,882 | 7,956 | yes |
| full reduplication (XX) | 871 | 7,132 | yes |
| `-tanga` nominaliser | 795 | 1,516 | yes |
| `-nga` nominaliser | 841 | 3,621 | **no** |
| `kai-` compound | 645 | 1,787 | **no** |
| **union** | **4,879** | **21,439** | |
| …carrying no etymology while the base has it | 2,334 | **7,142** | |

### Why `-nga` and `kai-` are not safe

`runga` 'above' is not `ru` + `-nga`. `tonga` 'south' is not `to` + `-nga`.
`ranga`, `tanga`, `whanga`, `hinga` all decompose to a real entry and none of
them is derived from it. A minimum-length guard does not rescue the class: it
drops `akonga` 'student', which genuinely is `ako` + `-nga`, while keeping
several of the false ones. A rule over these two classes yields plausible-looking
wrong answers, which is worse than yielding none.

---

## 3. What to add

A **table**, for the same reason `loan_origin` is a table — and one more.

```sql
CREATE TABLE derivation (
    id             INTEGER PRIMARY KEY,
    entry_id       INTEGER NOT NULL REFERENCES entry(id),
    sense_id       INTEGER REFERENCES sense(id),    -- when only one sense is derived
    base_entry_id  INTEGER REFERENCES entry(id),
    base_sense_id  INTEGER REFERENCES sense(id),
    base_form      TEXT NOT NULL,   -- the component as the source writes it
    base_gloss     TEXT,            -- the source's gloss for that component
    position       INTEGER,         -- 1, 2, 3 for compounds; NULL for affixation
    process        TEXT,            -- compound | causative | nominalisation |
                                    -- reduplication | agentive | passive
    affix          TEXT,            -- 'whaka-', '-tanga', NULL for compounds
    evidence       TEXT NOT NULL,   -- which source said so, or which rule derived it
    derived        INTEGER NOT NULL DEFAULT 0,  -- 1 = segmented, not attested
    confidence     TEXT             -- certain | probable | uncertain
);
```

`relation` cannot carry this. It has no `position`, and **order is meaning**:
`aho pae` is latitude and `pae aho` is nothing. It has no field for the process,
so `whakamātau` and `mātautanga` would be indistinguishable rows against the same
base. And its `note` already holds the component gloss as free text
(`'wete - to release, set free'`), which is data trapped in prose.

`derived` is load-bearing here exactly as in `loan_origin`. A row segmented by
the `whaka-` rule is a weaker claim than one Te Matatiki spelled out with a
Williams page reference, and the app should be able to show the difference.

`base_sense_id` matters more than it first appears. `whakamate` is formed from
one sense of `mate`, not from all of them, and the sweep is already recording
which sense a cognate set belongs to for the same reason.

---

## 4. Keep it out of the `ETY_*` layer

The reason is **not** the one that applies to loans, and the difference matters.

Borrowing and inheritance are mutually exclusive — that is what made the
`loan_origin` separation obvious. Derivation and inheritance are *not*
exclusive: `moemoe` really does descend from `*mohe`, by way of `moe`. So the
argument has to be narrower, and it is this:

**POLLEX already decides, case by case, whether a derived form is separately
reconstructible, and 312 of its 3,424 Māori reflexes are themselves
reduplications or `whaka-` forms.** `Moemoeā` has a set of its own —
`CE.MOEMOE-AA.*` 'Dream'. The absence of `moemoe` from `MP.MOHE` is therefore a
judgement the source made, not a gap for us to fill.

Writing a cognate link from `moemoe` to `MP.MOHE` would overwrite that judgement
and assert POLLEX reconstructed something it did not. That is the same failure
D23 removed 8,314 instances of — links created because a Māori spelling
coincided with a set — reached from the opposite direction.

The app can still present one **Origin** panel with three rows, because three
tables is a storage decision, not a display one:

    borrowed from   ->  loan_origin
    formed from     ->  derivation
    descended from  ->  ETY_*

---

## 5. Where the data would come from

**Attested, already extracted, needs only re-typing**

- Te Matatiki: 1,928 entries with two or more resolved component references
  (6,676 resolved `cross_ref` rows, 83% of its total).
- Paekupu: 606 entries with two or more resolved (2,825 resolved, 43%), plus
  6,517 notes carrying a component and its gloss.

This is the cheap half and it invents nothing — the references exist, resolve,
and are simply mistyped. Order can be recovered from the position of each
component in the source's bracketed note.

**Attested, needs parsing**

- papakupu's 221 senses that name the process (`'Causative'`, `'Derived Noun'`)
  but not the base.
- Tregear's prose, which lists derived forms inside the parent entry
  (`MOE, to sleep; moega, a bed`).
- Te Māra Reo's 16 cognate-set notes that describe a derivation.

**Derivable, flagged as such**

- `whaka-`, full reduplication and `-tanga` where the base is an entry, as
  `derived = 1, confidence = probable`.
- **Not** `-nga` or `kai-`. Those go to the sweep, which sees the gloss and the
  whole cluster at once.

---

## 6. Sequence

1. Create `derivation` and re-type the attested references — roughly 2,500
   entries, all `derived = 0`. No new lexicographic claims, and it fixes the
   `cross_ref` ambiguity that currently makes a component indistinguishable
   from a "see also".
2. Segment the safe affix classes as `derived = 1`. About 3,500 keys, and the
   app can choose whether to show them.
3. Leave `-nga`, `kai-` and the component glosses' finer structure to the sweep.

Step 1 alone answers the question the app is asking wherever a source took the
trouble to say so.

---

## 7. Two cleanups this note assumes

Neither blocks the design; both are recorded so the next person does not
rediscover them.

- **About 185 component references point an entry at itself** — 170 paekupu,
  6 papakupu, 1 temarareo, plus 8 already resolved that way. For a
  single-component term the component *is* the headword
  (`paekupu:ahua-maoa cross_ref -> 'maoa'`, note `'maoa - be cooked'`), so the
  relation points home and carries nothing, while the note carries the data.
  Under this design they become `derivation` rows with one component and no
  self-link.
- **The component gloss lives in `relation.note` as `'wete - to release, set
  free'`** — form and gloss joined by a hyphen in one text field. Splitting it
  is mechanical, but it should be split *into* `derivation.base_form` and
  `base_gloss` rather than parsed at read time.
