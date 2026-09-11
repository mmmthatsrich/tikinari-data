# Audit Sweep Rubric — v2

The standard the cluster sweep judges by. Every finding records the rubric
version that produced it (`sweep_finding.rubric_version`), and every completed
cluster records it too (`sweep_cluster.rubric_version`), so when this document
changes, `requeue_before_rubric()` can reopen exactly the clusters judged under
the superseded version.

**Read this before the first cluster and again whenever it changes.** A finding
class discovered at cluster 40,000 invalidates the 39,999 before it. Adding one
is not a failure of the rubric — it is the rubric working — but it must be
recorded as a version bump, not slipped in.

---

## 1. Scope

One cluster at a time: one normalised headword (`entry.headword_search`), every
source's entries for it, their senses, examples, forms, relations and domains,
and every cognate set linked into any of them. `scripts/sweep_batch.py` assembles
it; nothing is truncated.

Four judgements come out of that one read, and they inform each other:

1. **Field placement** — is each piece of content in the column it belongs in?
2. **Cross-source consistency** — where sources disagree, is one of them wrong?
3. **Etymology → sense** — which sense does each cognate set actually mean, and
   is the link descent or homophony?
4. **Identity** — which entries are the same word, and which merely share a
   spelling?

Judging any of them separately is worse than judging them together. The sense
inventory is what tells you which sense a protoform matches; the cross-source
senses are what tell you a link is spurious.

---

## 2. Hard rules

These are not preferences. A finding that breaks one of them is a defect in the
sweep, not in the data.

**Never invent lexicographic content.** No gloss is written that the sources do
not supply. Deriving across languages is allowed only through a controlled
vocabulary — `std_pos` for parts of speech, `subject_area`/`subject_area_en` for
domains — where both forms are given. Translating a gloss from one language into
the other is authoring, not auditing, and is forbidden. A missing gloss is
reported, never filled.

**Never rewrite a source's own voice.** Williams 1957 printed `s.` and `Aho`;
that is the record, and under CC BY-SA a quotation. Normalisation happens in the
parallel canonical fields (`part_of_speech_en`/`_mi`, and for spelling a future
canonical column), never in the raw ones. Correcting a *transcription* error is
in scope; correcting the *source* is not.

**Never touch `body_raw` or the landing tables.** Patches address `entry` and
`sense` fields only, through `sweep_patch`. The per-source `*_entries` tables and
the raw archives are provenance.

**Never address `entry.id`.** It is volatile across rebuilds. Findings and
patches name `source_id:source_entry_id`, with `#n` for a sense.

**Never merge entries across sources.** Provenance is deliberate — the app shows
"also in Williams". Identity findings produce concept membership, not deletions.

**Every finding states its evidence.** `detail` says what in the batch supports
the judgement. "Looks wrong" is not a finding.

---

## 3. Finding kinds

Each kind lists what triggers it, what evidence is required, and what action
follows. `action` is one of `applied` (a patch was written), `queued` (a change
is proposed but needs the concept layer or a human), `none` (recorded only), or
`deferred` (real, but out of this version's remit).

### `field_placement`

Content sitting in a column that is not for it.

*Triggers.* An example sentence inside `definition_raw` or `gloss_*`; a citation
inside a gloss; a POS label inside a definition; a cross-reference or synonym
trailing a definition; a register or domain marker inline; markup of any kind; a
variant form inside prose; a gloss that is merely the headword repeated.

*Evidence.* Quote the offending substring and name the column it belongs in.

*Action.* `applied` where the correction is fully determined by the observation
— removing a trailing marker, moving a citation into `example.citation`. `queued`
where content must be *created* elsewhere (a new `example` row), because the
patch layer updates fields and does not insert rows.

*Confidence.* `certain` only when the target column is unambiguous.

### `consistency`

Sources disagree about the same word in a way that makes one of them wrong.

*Triggers.* One source's gloss contradicts the others; a sense is present in
every source but one and its absence looks like loss rather than editorial
choice; punctuation or capitalisation of a gloss is out of step in a way that
changes reading.

*Not a trigger.* Different source conventions. Williams writes `s.`, He Pātaka
Kupu writes `ing`, Te Aka writes `noun`; all three are correct and the canonical
layer already reconciles them. Different depth of definition is editorial, not
error.

*Action.* Usually `none` or `queued`. A consistency finding that rewrites one
source to match another is almost always a hard-rule breach — say so instead.

### `etymology_sense`

Which sense a cognate set means.

*Triggers.* An entry with more than one sense carries a link; or an entry carries
competing sets whose glosses are incompatible.

*Evidence.* Quote the protoform's gloss and the sense's gloss, and say why they
match or do not. `kauere` is the worked example: `KAUERE 'crumpled, shrivelled'`
fits the sense glossed *Ka pūreherehe katoa*, while `CK.KAUERE 'A tree'` fits the
sense glossed *He rākau e 20 mita te tipu*.

*Action.* `queued` — writing `ETY_entry_link.sense_id` is a link-table update,
not a field patch.

*Remember what the link asserts.* Every link is `match_method='headword_exact'`:
matched on spelling, never on meaning. 89% already carry a `sense_id` resolved
mechanically because the entry had one sense — that made the pointer precise,
not correct. A single-sense entry can still hold a spurious link.

### `spurious_etymology`

The link is homophony, not descent.

*Triggers.* The protoform's gloss has no plausible semantic relation to any sense
of the entry; or two sets on one entry are mutually exclusive and only one can
be right.

*Evidence.* Both glosses, and the reason they cannot be the same word. `aho` is
the case: PPN \*afo "fishing line" and \*aho "daylight" share a search key and
are different words.

*Action.* `queued`. Deleting a link is destructive and belongs behind review.

### `duplicate`

Two entries are the same word.

*Triggers.* Same cluster, compatible senses, and — cross-source — nothing in
either that contradicts the other.

*Action.* `queued`, as concept membership. Never a deletion, and never a
cross-source merge.

*Within a source* a genuine repeat is a defect; say which entry is canonical and
why, but still `queued`.

### `homograph`

Two entries share a spelling and are **not** the same word.

*Triggers.* Incompatible senses under one search key; distinct etymologies;
distinct macronisation.

*Action.* `none` — recorded so nothing re-flags them as duplicates later. This is
the finding that protects against the worst error the sweep can make.

### `macronisation`

One word, spelled with and without macrons across sources.

*Action.* `none` in v1. See D18: it cannot be resolved before the concept layer,
because inheriting a macron on search-key identity alone merges homographs.
Record the disagreement; the concept work consumes it.

### `observation`

Anything real that no other kind covers, including source typography errors.
Williams contains 10 unbalanced brackets that are errors in the 1957 printing.
Record them; do not "fix" them by inventing the missing character.

---

## 4. Known-correct patterns — do not flag

Established by reading the sources during the discovery pass. Flagging these is
noise, and noise in the log is what makes a log unreadable.

| Pattern | Why it is correct |
|---|---|
| He Pātaka Kupu has `gloss_mi` and no `gloss_en` | It is a monolingual Māori dictionary |
| He Pātaka Kupu examples have no `text_en` | Same reason — 24,447 of them |
| Paekupu examples have no `text_en` | Paekupu publishes Māori sentences; its English is per-word tooltips, not sentence translations |
| Williams examples have no `text_en` | The English is the gloss, not a per-example translation |
| Williams POS is `s.`, `a.`, `v.t.` | 1957 convention; the canonical layer reconciles it |
| A Māori word with no macron | Most Māori words have no long vowel. Only a cross-source disagreement is evidence |
| `(i)`, `(ii)` after a Williams headword | Homograph numerals, already lifted into `sense_number` |
| Latin binomials in a gloss | `Myrsine australis`, `Apteryx` are the definition for plant and bird entries |
| Te Māra Reo glosses that are species lists | 86 entries have no prose definition; the species list is the content the source gives |
| A source's entry having exactly one sense | Normal, not a truncation |
| A relation rendered `[UNRESOLVED]` where the target headword is carried by several entries in that source | Expected, not a defect. 9,656 rows. `resolve_within_source_relations` deliberately resolves only the 5,197 unambiguous ones; choosing among homographs needs the concept layer. Do not flag per cluster |
| The same Māori sentence appearing twice on one sense with different English | Two sources' renderings, e.g. papakupu's 'Maranga mai.' as both 'Rise and shine.' [TWK] and 'Get up.' [MWA] |

---

## 5. Out of remit

Not the sweep's to decide, even when visible in a batch.

- **The 423 `needs_review` POS codes.** `plural of tāna`, Williams `pl.` — expert
  lexicographic decisions, recorded in `std_pos` for a human.
- **Whether a source's editorial judgement is right.** If Williams and Te Aka
  genuinely disagree about meaning, that is scholarship, not a defect.
- **Anything requiring the source PDFs or the live sites.** The sweep judges what
  is in the database. A suspected transcription loss is an `observation` naming
  what to check, not a correction.
- **Macronisation changes** — blocked on the concept layer (D18).
- **Deleting rows.** Nothing in v1 deletes.

---

## 6. Version history

**v2** — added two rows to the known-correct table after the first calibration
cluster: relations left unresolved because the target headword is ambiguous
within its source, and one Māori sentence carrying two sources' translations.
Both would otherwise have been flagged on thousands of clusters. Two defects the
same cluster found — duplicate examples, and hepatakakupu synonyms that were
resolvable — were fixed in the pipeline instead (D19, D20) rather than written
into the rubric, because a systemic defect belongs in the script that causes it.

**v1** — initial, seeded from the 18 discovery findings.

## 7. Calibration and versioning

The first 500 clusters are the calibration slice (`priority = 0`), stratified
125 per tier and deterministic. The sweep stops after them. You read the log,
and the rubric is corrected while the blast radius is 500 clusters rather than
55,827 — a log is only a control if it is read early enough to change the
outcome.

Bump the version in `scripts/sweep_rubric.py` and here together when:

- a finding kind is added, removed, or its triggers change
- a hard rule changes
- an entry is added to the known-correct table that would previously have been
  flagged

Then run `requeue_before_rubric(con, ["v2"])` to reopen everything judged under
the old standard. Leaving it unbumped is how a corpus ends up with its early
half judged by a weaker standard than its late half — the exact inconsistency
this work exists to remove.
