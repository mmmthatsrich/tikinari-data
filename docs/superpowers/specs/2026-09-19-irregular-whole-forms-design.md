# Irregular whole forms — design

**Date:** 2026-09-19
**Status:** approved, ready for an implementation plan
**Builds on:** `2026-09-17-suffix-forms-design.md` (the storage contract and
the 23-suffix vocabulary), `2026-09-17-hepatakakupu-suffix-parse-design.md`

## 1. What this recovers

Sixteen derived forms that paekupu prints in full and the pipeline throws
away.

A Māori passive or nominalisation is usually the base plus a suffix, and the
shipped readers exploit that: they read a fragment (`~nga`, `(-tia)`) and
compose it onto the headword. Some derivations cannot be written that way.
The stem itself changes:

    hau      -> hāua        vowel lengthens
    kukuti   -> kūtia       stem contracts
    momotu   -> motukia     the reduplication is undone
    wewete   -> wetekina    the reduplication is undone

For these, paekupu prints the whole word after a tilde instead of a
fragment. `strip_suffix_notation` removes every tilde run the suffix
vocabulary recognises and then truncates at the first tilde still standing,
which is correct for deriving `headword_search` — `'hau ~hāua ~tanga'` must
key on `hau` — but it means the whole form is discarded. Ten of the thirteen
affected entries currently carry no derived form at all.

## 2. The two sources use the tilde in opposite senses

This is the finding that shaped the scope, and it is not documented anywhere
else in the repo.

**paekupu replaces.** `'hau ~hāua'` names `hāua` as a whole word. It does
not mean `hauhāua`.

**papakupu appends.** Its notation lives in the `definition` column, not the
headword — `'eke': '~a, ~ria, ~ngia; ~nga (1) put oneself on something…'` —
and `~a` there means `ekea`. `build_papakupu` already reads it this way and
composes, which is why papakupu contributes 212 derived forms today.

The corpus settles which reading is right for each source. Testing every
candidate against the exact spellings other dictionaries hold:

| paekupu, replace reading | attested in | append reading | attested in |
|---|---|---|---|
| `motuhanga` | hepatakakupu, ngata, paekupu, te_aka | `momotumotuhanga` | nothing |
| `kūtia` | ngata | `kukutikūtia` | nothing |
| `wetekina` | ngata | `wewetewetekina` | nothing |
| `tākina` | ngata, papakupu | `takitākina` | nothing |

| papakupu, append reading | attested in |
|---|---|
| `uwhiuwhi` | hepatakakupu, ngata, te_aka, williams |
| `raurau` | hepatakakupu, kimikupu_hou, ngata, te_aka, williams |
| `whakamātautau` | 7 sources |

Match on exact spelling, never on `headword_search`. That key strips macrons
and collapses doubled vowels, which folds `hauhāua` onto `hauhauā` — a
different word meaning hostile — and reports a fabricated six-source
attestation for a word that appears nowhere.

## 3. The sixteen forms

Thirteen paekupu source rows, thirteen unified entries; three rows name two
irregular forms each. The suffix is read off the form's own ending by the
existing longest-match rule, never off the base.

| entry headword | whole form | suffix | class |
|---|---|---|---|
| `hau ~hāua ~tanga` | `hāua` | `-a` | passive |
| `kaweatu ~kawea atu` | `kawea atu` | `-a` | passive |
| `kawemai ~kawea mai` | `kawea mai` | `-a` | passive |
| `kukuti ~nga ~kūtia` | `kūtia` | `-tia` | passive |
| `kukuti ~kūtia ~nga` | `kūtia` | `-tia` | passive |
| `momotu ~motukia ~motuhanga` | `motukia` | `-kia` | passive |
| `momotu ~motukia ~motuhanga` | `motuhanga` | `-hanga` | nominalisation |
| `taki ~tākina` | `tākina` | `-kina` | passive |
| `tāpiri-atu ~tāpiritia-atu ~tāpiritanga-atu` | `tāpiritia-atu` | `-tia` | passive |
| `tāpiri-atu ~tāpiritia-atu ~tāpiritanga-atu` | `tāpiritanga-atu` | `-tanga` | nominalisation |
| `tiki atu ~tīkina atu` | `tīkina atu` | `-kina` | passive |
| `tiki ake ~tīkina ake` | `tīkina ake` | `-kina` | passive |
| `tuku atu ~tukuna atu` | `tukuna atu` | `-na` | passive |
| `uta anō ~utaina anō` | `utaina anō` | `-ina` | passive |
| `wewete ~wetekina ~wetekanga` | `wetekina` | `-kina` | passive |
| `wewete ~wetekina ~wetekanga` | `wetekanga` | `-kanga` | nominalisation |

**13 passive, 3 nominalisation.**

Two shapes need the suffix read from the form's first element rather than
its last character:

* **multi-word** — `kawea atu` is `kawe` + `-a` followed by the directional
  particle `atu`. Reading the tail gives `-tu`, which is not a suffix.
* **hyphenated** — `tāpiritia-atu` is the same shape with a hyphen.

Splitting on whitespace or hyphen and classifying the first element handles
both. `kukuti ~kūtia ~nga` and `kukuti ~nga ~kūtia` are the same entry
printed twice with the runs in either order, so order must not matter.

## 4. What changes

### 4.1 `read_whole_forms(headword)` — new, in `scripts/suffix_forms.py`

Returns `[(form, suffix, form_type), …]` for every tilde run the suffix
vocabulary does not recognise, classified off the run's first element.
Returns `[]` for a headword with no tilde, and for one whose tilde runs are
all recognised suffixes.

It reads; it never composes. The source already printed the whole word:
`compose('hau', '-hāua')` returns `hauhāua`, which §2 shows is attested
nowhere.

An unclassifiable run writes nothing and is refused through the existing
`Tally`, exactly as an unrecognised suffix fragment is today.

### 4.2 `strip_suffix_notation` is not touched

Its truncation is load-bearing for `headword_search` and has seven existing
tests in `tests/test_suffix_forms.py`. `read_whole_forms` runs alongside it
and reads the same notation for a different purpose. The plan must include a
test asserting the strip still returns `hau` for `'hau ~hāua ~tanga'` after
the change.

### 4.3 `_add_whole_forms(b, entry_id, forms, source)` — new, in `50_build_unified.py`

A sibling of `_add_suffix_forms`, which cannot be reused: it composes, and
these forms must be stored verbatim. It writes each form through
`b.add_form` unchanged and increments `b.derived_forms_written` on a row
that lands, matching the existing convention that the counter counts rows
rather than attempts.

Wired into `build_paekupu` only. The reader is source-agnostic, but no
other source has been shown to use the replace convention, and applying it
to a source that appends would fabricate words.

### 4.4 The note

`'-a (paekupu, whole)'`.

The existing format is `'<suffix> (<source>)'`, pinned by a test requiring
every derived form's note to match `-%(%)%` — that shape is what makes the
per-suffix counts the app needs cheap to compute. The `, whole` qualifier
keeps the format and the queries intact while recording that this form was
printed rather than composed, which nothing else in the row preserves: for
these sixteen, the suffix in the note is our inference from the spelling,
not a fragment the source wrote.

The multi-source note merge (`'-tia (te_aka, ngata)'`) is unaffected —
`_merge_form_note` folds provenance for a form recorded by several sources,
and none of these sixteen is.

## 5. Expected result

| | before | after |
|---|---|---|
| paekupu derived forms | 1,823 | 1,839 |
| corpus derived forms | 34,978 | 34,994 |
| `form` total | 35,622 | 35,638 |
| passive | 19,743 | 19,756 |
| nominalisation | 15,235 | 15,238 |

Ten of the thirteen entries gain their first derived form. Three already
carry one composed from a recognised suffix in the same headword and gain a
second: `hau ~hāua ~tanga` holds `hautanga`, and both `kukuti` rows hold
`kukutinga`.

Unchanged: `entry` 153,440 · `sense` 175,101 · `relation` 175,407 ·
`derivation` 11,424 · `concept` 91,140 · 18 confirmed judgements.

`derivation` does not move. These are `form` rows. Feeding them to
`53_build_word_origin` would require a `derived_from` relation whose base
and target differ by an irregular stem change, and `describe_derivation`
returns `(None, None)` for exactly that case — it reads an affix off two
spellings and declines to guess when the stem shifts. Recording sixteen
derivations with a NULL process buys nothing.

## 6. Out of scope: reduplication

papakupu's twelve unrecognised tokens are **not** irregular whole forms.
Under its append convention they are mostly a different morphological
process:

| group | count | examples |
|---|---|---|
| reduplication | 5 | `raurau`, `ueue`, `uiui`, `uwhiuwhi`, `whakamātautau` |
| reduplication + suffix | 3 | `uiuia`, `whakamātautauranga`, `meatingia` |
| append yields nothing attested | 4 | `hokohokoa`, `mānuiatia`, `meatinga`, `ukui` |

Reduplication is deferred, and the reason is its size rather than its
difficulty. **873 headwords in the corpus are a stem written twice where the
stem is itself a headword**, and that counts only full reduplication of the
whole key; partial reduplication is commoner in Māori and harder to detect.
`derivation.process` already holds 279 reduplication rows, all Williams, all
found by spelling rather than by notation.

Harvesting papakupu's eight explicit markings would populate a new
`reduplication` form type with roughly one percent of the phenomenon. A
corpus that answers "8" to *how many reduplications are there* is worse than
one that declines to answer: the count reads as data, and nothing in the row
would say it is a sample. Reduplication earns its own spec, detecting from
spellings across all sources the way Williams already does, with papakupu's
notation as confirmation rather than as the source.

The four unattested appends stay refused and counted in the `Tally`, as they
are today.

## 7. Testing

**Unit, one per shape** — vowel change (`hāua`), stem contraction (`kūtia`),
de-reduplication (`motukia` passive and `motuhanga` nominalisation from one
headword), multi-word (`kawea atu`), hyphenated (`tāpiritia-atu`), and both
run orders of `kukuti`.

**Guards** — an all-recognised headword (`'ahu ~nga'`) yields no whole form;
a headword with no tilde yields none; an unclassifiable run writes nothing
and is refused; `strip_suffix_notation` still truncates identically.

**Wiring** — `build_paekupu` writes the row verbatim with the
`', whole'` note, and does not compose.

**Corpus** — paekupu at 1,839, and the sixteen forms present by exact
spelling.

The malformed-form guard in `test_suffix_extraction.py` needs **no change**,
and the plan must not weaken it. It rejects a derived form containing `~`,
`(`, `(-`, `,` or `.`; none of the sixteen contains any of those. It does
not reject spaces, and must not start to: 153 existing derived forms are
legitimately multi-word (`'kī taurangihia'`, `'ngau tuarātia'`), so a
space rule would fail rows that predate this work.

**Invariants** — the table in §5.

## 8. Rebuild

`50_build_unified.py --source paekupu`, then `59_rebuild_derived.py`, then
verify against §5. Snapshot the judgements with `61_export_judgements.py`
first.

`59_rebuild_derived.py` takes no flags and executes on any argument,
including `--help`. Never pipe it through `head`; redirect to a file.
