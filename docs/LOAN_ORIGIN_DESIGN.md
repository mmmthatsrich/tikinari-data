# Loan Origin — design note

**Question.** Can the app surface where a loanword came from — the source word and
what it means in that language — with the data structure as it stands?

**Short answer.** It can say *that* a word is borrowed, for 22,832 entries. It
cannot say *from what*, because neither the source word nor its meaning is
modelled anywhere. For most Te Aka loans the source word is recoverable from the
gloss, but recovering something is not the same as recording it.

---

## 1. What the corpus holds today

| Fact | Recorded? | Where |
|---|---|---|
| This entry is a loan | **yes — 22,832 entries** | `entry.loan_marker` (18,848) plus Te Aka's part of speech `loan, noun` (3,575, marker NULL) |
| Source language | **almost never — ~100** | 8 paekupu markers naming it; 90 papakupu glosses prefixed `Eng.` |
| The source word | **implicit only** | 93% of Te Aka loan glosses are 1–3 words and effectively *are* the source word |
| Its meaning in the source language | **no** | not modelled |
| Component-level loans | **partially — 200 rows** | paekupu notes such as `moni (kupu mino) - money` |

Three sources encode the same fact three different ways, and only two of them
ever name the language:

    te_aka     entry.loan_marker = 'Historical Loan Word'      18,439   no language
    te_aka     part_of_speech    = 'loan, noun'                 3,575   no language
    paekupu    entry.loan_marker = 'he kupu mino (reo Wīwī)'      409   sometimes
    papakupu   gloss_en          = 'Eng. shirt'                    90   always

The paekupu variants name Japanese (`reo Hapanihi`), French (`reo Wīwī`),
Italian (`reo Itāriana`), Hebrew (`reo Hīperu`) and Cantonese. That is the only
place in 153,543 entries where a borrowing's origin language is stated as data.

### The 93% is a tempting shortcut

Te Aka's loan glosses look like this:

    aehana   'agent.'        hāte    'shirt.'        Aki     'Jack.'
    Aerana   'Ireland.'      āka     'ark.'          āmene   'amen.'

20,974 of 22,515 are three words or fewer. For a transliteration the gloss and
the source word coincide, so a derivation rule would get a long way. It breaks
exactly where precision matters: `Aerana` and `Aerani` both gloss 'Ireland', and
nothing says which spelling transliterates which source, or whether both do. And
it says nothing at all about the roughly one in five of those 18,439 that are
biblical Hebrew or Latin rather than English.

---

## 2. What to add

A **table**, not columns on `entry`:

```sql
CREATE TABLE loan_origin (
    id            INTEGER PRIMARY KEY,
    entry_id      INTEGER NOT NULL REFERENCES entry(id),
    sense_id      INTEGER REFERENCES sense(id),   -- when only one sense is borrowed
    source_lang   TEXT,        -- 'English', 'Hebrew', 'reo Hapanihi' as the source writes it
    source_word   TEXT,        -- 'shirt', 'Ireland', 'agent'
    source_gloss  TEXT,        -- what it means in that language, where it differs
    via_lang      TEXT,        -- 'pirihimana' <- policeman <- Old French
    evidence      TEXT NOT NULL,   -- which source said so, or which rule derived it
    derived       INTEGER NOT NULL DEFAULT 0,  -- 1 = inferred, not attested
    confidence    TEXT         -- certain | probable | uncertain
);
```

Columns on `entry` would force one origin per word and lose the rest. A table
handles the three cases that actually occur: a disputed origin, a chain through
an intermediate language, and a word where only one sense is borrowed.

`derived` is the load-bearing field. A row derived from the 93% rule is not the
same claim as one attested by papakupu's `Eng.`, and the app should be able to
show the difference. The rubric's hard rule — never invent lexicographic content
— is satisfied by recording the derivation *as* a derivation rather than by
refusing to derive at all.

`sense_id` exists because borrowing is often sense-specific. `hāte` is 'shirt'
from English in one entry and 'heart', the playing-card suit, in another; `hamu`
is both 'ham' and 'jam'.

---

## 3. Keep it out of the `ETY_*` layer

This is the one constraint I would not bend.

`ETY_*` models **inherited** descent from Proto-Polynesian. Borrowing is the
opposite relation: a word is either inherited or borrowed, never both. That
distinction is not academic here — it is what D23 used to remove 8,314 wrong
links, where loans had been given Proto-Polynesian ancestors purely because the
Māori spelling of the loan coincided with a Māori word:

    Aki    'Jack.'    <- PN.-QAKI.1  'Formative suffix to verbs'
    Ahua   'Asshur.'  <- NP.AAFUA    'Form, appearance, likeness'
    āka    'ark.'     <- a set for the homophonous Māori word

Putting borrowings into `ETY_cognateset` would recreate that bug by
construction. The app can present both under one "origin" heading; the storage
must stay separate.

---

## 4. Where the data would come from

**Attested, available now**

- paekupu's 409 markers, 8 of which name the language.
- papakupu's 90 `Eng.` glosses — always name it, and the gloss after the marker
  is the source word.
- paekupu's 200 component notes: `moni (kupu mino) - money`, `kāri - card
  (kupu mino)`, `pā (pātene) - button (kupu mino)`. These are the richest rows in
  the corpus for this purpose — Māori form, loan flag, and English meaning
  together — and they describe the *components* of coined terms, 145 distinct
  ones, which is a different and useful axis from whole-word borrowing.

**Derivable, flagged as such**

- Te Aka's 20,974 short glosses, as `derived = 1, confidence = probable`.

**Needs the sweep or an external source**

- Which of Te Aka's 18,439 are Hebrew, Latin or Greek rather than English. The
  marker does not say, and the gloss ('Asshur.', 'Adria.', 'Hagrite.') names the
  referent rather than the language.

---

## 5. Sequence

1. Create `loan_origin` and populate the attested rows — about 700, all with
   `derived = 0`. Cheap and immediately useful.
2. Add the Te Aka derivation as `derived = 1`. Roughly 21,000 rows, and the app
   can choose whether to show them.
3. Leave source-language classification for the sweep, which sees the gloss, the
   POS, the loan marker and the whole cluster at once.

Step 1 alone is enough to answer the question the app is asking, for the entries
where the corpus genuinely knows the answer.

---

## 6. Two cleanups this note assumes

Neither blocks the design; both are recorded here so the next person does not
rediscover them.

- **Te Aka marks loans two ways.** `loan_marker` and a `loan` part of speech,
  with 3,575 entries using only the second. Any query for loans must check both,
  as `52_build_etymology_unified` and `08b_pollex_entry_linker` now do.
- **321 paekupu synonym targets still carry a `(kupu mino)` qualifier** —
  `'ētita (kupu mino)'` should target `ētita`. The qualifier is stripped in the
  dashed branch of `paekupu_alternatives.parse_alternative` but not the plain
  one.
