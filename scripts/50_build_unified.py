"""Build the canonical unified core (SCHEMA_PROPOSAL.md §3) from the per-source
*_entries tables.

This is a pure DB -> DB projection. The per-source tables remain the raw, curated
landing zone (all session-36/38/39 cleanups live there); this script reads those
curated rows and rebuilds the unified
    entry -> form / sense / example / relation / entry_domain
core, with explicit language tagging (gloss_en / gloss_mi), structured bilingual
examples, and dialect tagging. FTS (entry_fts / sense_fts / example_fts) is kept in
sync automatically by the triggers defined in 00_init_db.py.

Per-source and idempotent: each source's slice is deleted and rebuilt independently,
so you can re-unify ONE dictionary after its annual refresh without touching the
others. Run 00_init_db.py first so the core tables exist.

    py scripts/50_build_unified.py                      # all sources
    py scripts/50_build_unified.py --source te_aka      # one source
    py scripts/50_build_unified.py --source papakupu --source williams

Design notes / current simplifications (see SCHEMA_PROPOSAL.md):
  * Grain = one source row -> one entry -> one sense. Inline-sense sources (Te Aka,
    Paekupu, Papakupu) get a single sense; multi-row sources (Williams, He Pātaka
    Kupu) appear as multiple entry rows that share a headword. Grouping multi-row
    senses under one entry (true entry -> N senses) is the next refinement and needs
    homonym logic — deliberately deferred, not guessed.
  * part_of_speech is RAW passthrough (decision: canonical std_pos wiring waits for
    the expert review of the 249 needs_review rows).
  * source_entry_id is unique within a source so the downstream device id
    '{source_id}:{source_entry_id}' never collides (He Pātaka Kupu word_id repeats
    across senses, so it is suffixed '~{sense}', per amendment 2).
  * Papakupu examples carry both halves: 02_papakupu_extract.py emits
    {text_mi, text_en, source_abbrev} dicts, so example.text_mi is populated from
    the Māori sentence (recovered via the orthography heuristic _maori_tail).
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import (DB_PATH, normalise_search_key, normalise_sort_key,
                   compute_content_hash, pos_atoms, resolve_relations_by_domain,
                   resolve_relations_by_gloss, resolve_unambiguous_senses,
                   resolve_within_source_relations)
from williams_senses import split_senses
from williams_examples import split_gloss_examples
from williams_headword import parse_headword_note
from williams_xref import (parse_equals_variants, pick_target,
                           see_also_spellings, supported_parents)
from papakupu_gloss import clean_gloss
from paekupu_alternatives import parse_alternative
from hepatakakupu_synonyms import pair_synonyms, parse_synonym
from temarareo_gloss import build_raw, clean_definition, dedupe_species
from wakareo_records import (drop_truncated_tail, example_owners,
                            parse_derivation, parse_tregear)
from sweep_patch import apply_patches
import suffix_forms
import reduplication

NOW = datetime.now(timezone.utc).isoformat()

WAKAREO_SOURCES = (
    "tregear_exceptions", "ngata", "te_matatiki", "kimikupu_hou",
    "he_kupu_arotake", "kupu_rorohiko", "tai_kupu_variants",
    "nga_tini_a_tangaroa", "kupu_mataora", "maori_law_lexicon",
)
SOURCES = ("williams", "te_aka", "hepatakakupu", "paekupu", "papakupu",
           "taikupu", "temarareo") + WAKAREO_SOURCES
CORE_TABLES = ("entry", "form", "sense", "example", "relation", "entry_domain")

# trailing citation / source markers in example strings (same patterns as the prototype)
# Te Aka: (Te Toa Takitini 1/3/1930:1992). The sentence's own stop may follow the
# bracket — '... ki te ahuone (Te Ara 2015).' — and anchoring strictly to the end
# of the string left 23,183 citations inside text_mi.
CITE_PAREN = re.compile(r"\s*\(([^()]*\d[^()]*)\)\s*([.!?])?\s*$")
SRC_BRACKET = re.compile(r"\s*\[([A-Z0-9][A-Z0-9/]*)\]\s*$")   # [TTU] [NGH3] [041126]


def _blank_to_null(text):
    """'' / whitespace -> None; anything else through unchanged."""
    return text if text is None or str(text).strip() else None


def jload(s):
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


def _ws(s):
    """Collapse whitespace runs to single spaces; '' for falsy input."""
    return re.sub(r"\s+", " ", s).strip() if s else ""


def split_src(s):
    """Strip a trailing [SRC] code; return (text, src|None)."""
    m = SRC_BRACKET.search(s)
    return (s[:m.start()].strip(), m.group(1)) if m else (s.strip(), None)


def split_cite(s):
    """Strip a trailing (citation); return (text, citation|None).

    A sentence stop that followed the bracket is given back to the sentence —
    it punctuates the Māori, not the citation.
    """
    m = CITE_PAREN.search(s)
    if not m:
        return s.strip(), None
    return (s[:m.start()].strip() + (m.group(2) or "")), m.group(1)


_FORM_NOTE = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")


def _merge_form_note(existing, incoming):
    """Fold a second sighting's provenance into '-tia (te_aka, ngata)'.

    A second sighting usually carries the same suffix, in which case only the
    source list grows. Differing suffixes are rare — across every reader's
    output today there are none — but silently dropping one is exactly what
    this module must not do, so both survive, joined by '; '. A note that
    does not match the '<suffix> (<sources>)' shape is left alone rather than
    reformatted — the variant and plural rows predate this convention.
    """
    if not incoming or incoming == existing:
        return existing
    if not existing:
        return incoming
    old, new = _FORM_NOTE.match(existing), _FORM_NOTE.match(incoming)
    if not (old and new):
        return existing
    if old.group(1) != new.group(1):
        return f"{existing}; {incoming}"
    sources = [s.strip() for s in old.group(2).split(",") if s.strip()]
    for source in (s.strip() for s in new.group(2).split(",")):
        if source and source not in sources:
            sources.append(source)
    return f"{old.group(1)} ({', '.join(sources)})"


def _add_suffix_forms(b, entry_id, headword, suffixes, source, tally=None,
                      marked_headword=None):
    """Write one form row per known suffix, composed against *headword*.

    An unrecognised suffix writes nothing: classify() is the only thing
    separating a real ending from kimikupu_hou's chemistry and the typos in
    the sources' own text.

    *suffixes* may carry a macron the vocabulary is keyed without (paekupu's
    '~hangā'), so classify() is looked up on the FOLDED suffix — classify()
    itself never folds, by design (suffix_forms.classify's own contract) —
    while the suffix passed to compose()/note keeps its original spelling.

    *marked_headword* is the original notation-bearing headword, where the
    caller has one. compose_phrase uses it to find the element the source
    marked: 'heke (~nga) atu' means 'hekenga atu', not 'heke atunga'. Left
    None, composition still steps over a trailing directional particle.

    *tally* is optional and normally left None: the other six sources tally
    inside the reader that produced their suffixes (e.g. read_paren_suffixes
    takes b.suffix_tally directly). hepatakakupu has no reader here — its
    suffixes arrive already parsed in the `suffixes` column — so
    build_hepatakakupu is the one caller that passes b.suffix_tally through
    to here instead. Passing a tally from the other six as well would
    double-count every token.
    """
    for suffix in suffixes or []:
        form_type = suffix_forms.classify(suffix_forms.fold(suffix))
        if tally is not None:
            if form_type:
                tally.keep()
            else:
                tally.refuse(suffix)
        if not form_type:
            continue
        if b.add_form(entry_id,
                      suffix_forms.compose_phrase(headword, suffix,
                                                  marked_headword),
                      form_type, f"{suffix} ({source})"):
            b.derived_forms_written += 1


def _add_whole_forms(b, entry_id, forms, source):
    """Write a whole irregular derived form exactly as the source printed it.

    _add_suffix_forms cannot be reused: it composes, and these forms exist
    precisely because composing does not work — 'hau' + '-hāua' is
    'hauhāua', a word no dictionary in the corpus holds.

    Where the corpus can corroborate the whole-form reading it does, by
    EXACT spelling: 'motuhanga' is a headword in four sources, 'tākina' in
    two, 'kūtia' and 'wetekina' in ngata. 'hāua' itself rests on paekupu
    alone — it is attested in no other source, and the eight entries that
    share its FOLDED key are 'hauā' and 'Hauā', a different word. Never
    count attestation on headword_search; that key strips macrons and
    collapses doubled vowels, and reading a count off it is the specific
    error the spec's §2 exists to warn about.

    The note carries ', whole' because the suffix in it is read off the
    form's spelling rather than printed by the source as a fragment. The
    '<suffix> (<source>...)' shape is preserved so the per-suffix counts
    keep working.
    """
    for form, suffix, form_type in forms or []:
        if b.add_form(entry_id, form, form_type, f"{suffix} ({source}, whole)"):
            b.derived_forms_written += 1


def _hepataka_bases(headword, tally):
    """The base(s) hepatakakupu's own `suffixes` column composes onto.

    Almost every hepatakakupu headword is a single word ('kake'), but a
    handful list alternative spellings joined by a comma ('tīkona,
    tīkoina') or carry a parenthetical. Unlike paekupu's
    suffix_forms.composition_bases, a parenthetical here is not a droppable
    qualifier in general — 'hohou (i te) rongo' is the phrase "to make
    peace", and composition_bases's rule of dropping '(...)' outright would
    turn it into 'hohou rongo', a confidently wrong word rather than a
    visibly malformed one. So: split on commas, and refuse — rather than
    repair — any resulting base that still carries a parenthesis. This
    module's rule is to report what the spellings show and return nothing
    rather than guess, and a phrase passive is exactly the irregular/
    suppletive case spec §7 carves out.

    Each refused base is tallied under the 'base' kind — separately from
    unrecognised suffixes, which are the only refusals the spec's 1%
    tripwire is about.
    """
    bases = []
    for base in (part.strip() for part in headword.split(",")):
        if not base:
            continue
        if "(" in base or ")" in base:
            # 'base', not 'suffix': a headword we cannot compose onto is
            # nothing to do with the suffix vocabulary, and counting it
            # there put a whole phrase in a list of affixes.
            tally.refuse(base, kind="base")
            continue
        bases.append(base)
    return bases


def _add_derived_forms(b, entry_id, triples, source):
    """Write form rows for (base, derived, suffix) triples, stored whole."""
    for _base, derived, suffix in triples or []:
        form_type = suffix_forms.classify(suffix_forms.fold(suffix))
        if not form_type:
            continue
        if b.add_form(entry_id, derived, form_type, f"{suffix} ({source})"):
            b.derived_forms_written += 1


class Builder:
    """Inserts into the unified core, using autoincrement rowids for FK wiring."""

    def __init__(self, con, source_id, dialect, first_seen_map):
        self.con = con
        self.source_id = source_id
        self.dialect = dialect
        self.first_seen_map = first_seen_map      # {source_entry_id: first_seen}
        self.counts = {t: 0 for t in CORE_TABLES}
        self._lemmas = {}                         # {entry_id: {headword, sort}} for add_form
        self._examples = set()                    # (sense_id, mi, en) already inserted
        self._forms = {}                          # (entry_id, form_cf, type) -> (rowid, note)
        # Spec §6's refusal report: tokens seen/refused (suffix_forms.Tally,
        # populated by the reader calls below) and rows actually written
        # (tallied here, at the one place every derived form passes through).
        self.suffix_tally = suffix_forms.Tally()
        self.derived_forms_written = 0

    def add_entry(self, source_entry_id, headword, headword_sort, headword_search,
                  pos=None, headword_en=None, loan_marker=None, audio_url=None,
                  locator=None, homonym_no=None, material=None, dialect=None):
        seid = str(source_entry_id)
        first_seen = self.first_seen_map.get(seid) or NOW
        content_hash = compute_content_hash(material) if material else None
        cur = self.con.execute(
            "INSERT INTO entry (source_id, source_entry_id, headword, headword_sort, "
            "headword_search, homonym_no, headword_en, part_of_speech, loan_marker, "
            "dialect, audio_url, locator, content_hash, first_seen, created_at, last_updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.source_id, seid, headword, headword_sort, headword_search, homonym_no,
             headword_en, pos, loan_marker, dialect or self.dialect, audio_url, locator,
             content_hash, first_seen, NOW, NOW))
        self.counts["entry"] += 1
        self._lemmas[cur.lastrowid] = {(headword or "").casefold(),
                                       (headword_sort or "").casefold()}
        return cur.lastrowid

    def add_sense(self, entry_id, sense_number, gloss_en, gloss_mi, definition_raw,
                  register=None, parent_sense_id=None, part_of_speech=None, note=None):
        # Absent text is NULL, never ''. An empty string reads as
        # present-but-blank to every downstream consumer (the app's "has a
        # definition" test, the audit sweep's emptiness counts, FTS).
        gloss_en, gloss_mi, definition_raw, note = (
            _blank_to_null(v) for v in (gloss_en, gloss_mi, definition_raw, note))
        cur = self.con.execute(
            "INSERT INTO sense (entry_id, sense_number, parent_sense_id, gloss_en, "
            "gloss_mi, definition_raw, register, part_of_speech, note) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (entry_id, sense_number, parent_sense_id, gloss_en, gloss_mi,
             definition_raw, register, part_of_speech, note))
        self.counts["sense"] += 1
        return cur.lastrowid

    def add_example(self, sense_id, entry_id, text_mi, text_en, source_abbrev,
                    citation, sort_no):
        if not (text_mi or text_en):
            return
        # The same sentence twice on one sense is never meaningful. Williams
        # got them from two routes at once — split out of the sense's own text,
        # and again from the parser's entry-level usage_examples — so 91 rows
        # were stored twice. Distinct senses sharing a sentence is legitimate
        # and is not caught here.
        key = (sense_id, text_mi, text_en)
        if key in self._examples:
            return
        self._examples.add(key)
        self.con.execute(
            "INSERT INTO example (sense_id, entry_id, text_mi, text_en, source_abbrev, "
            "citation, sort_no) VALUES (?,?,?,?,?,?,?)",
            (sense_id, entry_id, text_mi, text_en, source_abbrev, citation, sort_no))
        self.counts["example"] += 1

    def add_form(self, entry_id, form, form_type, note=None):
        if not form:
            return False
        # A form that merely restates the headword or its macron-stripped sort
        # key is not a variant: headword_search already normalises both, so the
        # row adds nothing and inflates the app's "has variants" signal.
        if form.casefold() in self._lemmas.get(entry_id, ()):
            return False
        # One row per (entry, form, type). A derived form is routinely recorded
        # by several sources, and by several senses within one source; writing
        # it once per sighting would make the corpus-wide suffix counts report
        # how often a form was mentioned, not how many forms there are.
        key = (entry_id, form.casefold(), form_type)
        if key in self._forms:
            rowid, existing = self._forms[key]
            merged = _merge_form_note(existing, note)
            if merged != existing:
                self.con.execute("UPDATE form SET note = ? WHERE id = ?",
                                 (merged, rowid))
                self._forms[key] = (rowid, merged)
            return False
        cur = self.con.execute(
            "INSERT INTO form (entry_id, form, form_search, form_type, note) "
            "VALUES (?,?,?,?,?)",
            (entry_id, form, normalise_search_key(form), form_type, note))
        self._forms[key] = (cur.lastrowid, note)
        self.counts["form"] += 1
        # True only when a row actually landed. The refusal report counts rows,
        # not attempts: counting attempts would report how often a form was
        # sighted, which is the very thing this method's dedup exists to stop.
        return True

    def add_relation(self, entry_id, rel_type, target_headword, target_entry_id=None,
                     note=None, target_sense_id=None, sense_id=None):
        """`sense_id` is WHICH sense asserts this, where the source says (D46).

        NULL means the source made the claim of the word, not of one sense,
        which is true of every source but te Aka today. It is not "unknown":
        an entry-level claim is what those sources actually print.
        """
        if not target_headword:
            return
        self.con.execute(
            "INSERT INTO relation (entry_id, rel_type, target_headword, target_entry_id, "
            "note, target_sense_id, sense_id) VALUES (?,?,?,?,?,?,?)",
            (entry_id, rel_type, target_headword, target_entry_id, note,
             target_sense_id, sense_id))
        self.counts["relation"] += 1

    def add_domain(self, entry_id, sense_id, domain, domain_lang):
        if not domain:
            return
        self.con.execute(
            "INSERT INTO entry_domain (sense_id, entry_id, domain, domain_lang) "
            "VALUES (?,?,?,?)", (sense_id, entry_id, domain, domain_lang))
        self.counts["entry_domain"] += 1


def load_std_pos(con):
    m = {}
    for raw, en, mi in con.execute("SELECT raw_pos, canonical_en, canonical_mi FROM std_pos"):
        # defensive strip: manual edits can leave trailing CR/LF/space
        m[raw] = (en.strip() if en else en, mi.strip() if mi else mi)
    return m


def resolve_pos(raw, std_pos):
    """Resolve one raw POS string to a list of (en, mi) canonical pairs.

    Whole-string mapping wins (handles pre-composed values like 'loan, noun' or
    'proper noun - person'). If the whole string is unmapped, fall back to
    splitting on commas and mapping each atomic code (handles He Pātaka Kupu
    combos like 'mahp, ing, āhua' once the atomic codes are reviewed into std_pos).
    """
    whole = std_pos.get(raw)
    if whole and (whole[0] or whole[1]):
        return [whole]
    out = []
    for tok in pos_atoms(raw):
        pair = std_pos.get(tok)
        if pair and (pair[0] or pair[1]):
            out.append(pair)
    return out


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
            for en, mi in resolve_pos(r, std_pos):
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


def write_sense_pos(con, std_pos):
    """Bake per-sense canonical POS onto sense.part_of_speech_en / _mi via resolve_pos.

    Combos (e.g. 'mahp, ing, āhua') are split to atomic codes and composed, so the
    app reads finished labels off the sense row with no std_pos join. NULL where no
    canonical mapping exists yet."""
    rows = con.execute(
        "SELECT id, part_of_speech FROM sense WHERE part_of_speech IS NOT NULL"
    ).fetchall()
    for sid, raw in rows:
        seen_en, seen_mi = [], []
        for en, mi in resolve_pos(raw, std_pos):
            if en and en not in seen_en:
                seen_en.append(en)
            if mi and mi not in seen_mi:
                seen_mi.append(mi)
        con.execute(
            "UPDATE sense SET part_of_speech_en=?, part_of_speech_mi=? WHERE id=?",
            (", ".join(seen_en) or None, ", ".join(seen_mi) or None, sid),
        )
    con.commit()


# ── per-source transforms ────────────────────────────────────────────────────

def build_williams(con, b):
    sql = ("SELECT id, headword, headword_sort, headword_search, part_of_speech, "
           "definition, usage_examples, sense_number, cross_refs, page_number, "
           "source_section, headword_note, parent_headword "
           "FROM williams_entries ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, sn, xr, pg, sec, hnote,
         parent_hw) in con.execute(sql):
        # '(pl. wāhine)', '(poetical)', '(less correctly tūāhu)' printed with the
        # headword. Eight are plural forms — a lexical fact the form table exists
        # for — and the rest qualify the entry rather than define it.
        note = parse_headword_note(hnote)
        examples = [e.strip() for e in jload(ux) if isinstance(e, str)]
        eid = b.add_entry(id_, hw, hs, hse, pos=pos,
                          locator=f"p{pg}/{sec}" if pg else sec,
                          material={"hw": hw, "pos": pos, "def": d,
                                    "ex": examples, "xr": jload(xr)})
        _add_derived_forms(
            b, eid, suffix_forms.read_williams_passives(hw, d or "", b.suffix_tally),
            "williams")
        # Williams marks a variant with '=' at the head of an entry
        # ('Ahine. = wahine.'). 611 such entries carried no relation at all and
        # the POS behind the marker stayed stranded in the gloss.
        variants, d = parse_equals_variants(d)
        # A pure-variant entry has nothing left once the marker is lifted out.
        # Synthesise a readable gloss the same way the parser already does for a
        # pure '‖' pointer ("Cf. <targets>."), rather than leaving the bare
        # target word standing as if it were an English gloss.
        if not d and variants:
            d = "Variant of " + ", ".join(variants) + "."

        senses = split_senses(d) or [{"sense_number": 1, "part_of_speech": None,
                                      "gloss_en": d, "definition_raw": d}]
        first_sid = None
        inline_texts = set()
        for s in senses:
            # Williams prints its examples inline, in Māori, after the English
            # gloss — so gloss_en held the whole definition (18,792 senses were
            # byte-identical to definition_raw) and `example` held 61 rows in
            # 14,942 entries. The split is per SENSE, so each example lands on
            # the sense it illustrates rather than all of them on sense 1.
            gloss, inline = split_gloss_examples(s["gloss_en"])
            sid = b.add_sense(eid, s["sense_number"], gloss, None,
                              s["definition_raw"], part_of_speech=s["part_of_speech"],
                              register=note["register"] if first_sid is None else None,
                              note=note["note"] if first_sid is None else None)
            for i, ex in enumerate(inline):
                b.add_example(sid, eid, ex["text"], None, None, ex["citation"], i)
                inline_texts.add(_ws(ex["text"]))
            if first_sid is None:
                first_sid = sid
        # The parser's own <span lang="mi"> examples have no sense of their own,
        # so they go on the first one — but only if the per-sense split did not
        # already place them. Adding them unconditionally put sense 3's example
        # on sense 1, where nothing marks it as misplaced.
        for i, ex in enumerate(e for e in examples if _ws(e) not in inline_texts):
            b.add_example(first_sid, eid, ex, None, None, None, i)
        for pl in note["plural"]:
            b.add_form(eid, pl, "plural")
        for target in variants:
            b.add_relation(eid, "variant_of", target)
        for t in jload(xr):
            if isinstance(t, dict):                       # typed ‖ cross-ref
                b.add_relation(eid, t.get("type") or "cross_ref", t.get("target"))
            elif isinstance(t, str):                      # legacy bare string
                b.add_relation(eid, "cross_ref", t)


def split_filters(filters):
    """Te Aka `filters` -> (loan_marker, semantic domains).

    Te Aka ships one filter value, 'Historical Loan Word', on 18,439 entries,
    and it went into entry_domain — making a register/etymology marker the most
    common "semantic domain" in the database. `entry.loan_marker` is the column
    for it and was NULL everywhere.

    Anything that is NOT a loan marker stays a domain, so a genuine subject
    filter added upstream later lands in the right place without another fix.
    """
    loans, domains = [], []
    for f in filters or []:
        text = f if isinstance(f, str) else str(f)
        (loans if "loan" in text.casefold() else domains).append(text)
    return ("; ".join(loans) or None), domains


def te_aka_example(item):
    """One Te Aka example -> (text_mi, text_en, citation).

    Accepts the {mi, en} dicts the parser now emits and the bare Māori strings
    it emitted before translations were captured, so a slice parsed either way
    projects correctly.
    """
    if isinstance(item, dict):
        mi, en = item.get("mi"), item.get("en")
    elif isinstance(item, str):
        mi, en = item, None
    else:
        return None
    if not mi:
        return None
    text, cite = split_cite(mi)          # Te Aka example = Māori + (citation)
    return text, en, cite


def _add_te_aka_synonyms(b, entry_id, sense_id, sense, emitted):
    """One sense's synonyms, attributed to that sense (D46).

    `emitted` guards (sense, headword) across the duplicate-def-div merge, so
    folding a repeated sense into the one that won cannot double a row.
    """
    for sy in sense.get("synonyms") or []:
        if isinstance(sy, dict):
            text = sy.get("text")
            # word_id is a SOURCE id, not a unified entry.id — stash it in note and
            # resolve to target_entry_id after all te_aka entries exist (see below).
            note = f"te_aka_word_id={sy.get('word_id')}" if sy.get("word_id") else None
        elif isinstance(sy, str):
            text, note = sy, None
        else:
            continue
        if not text or (sense_id, text) in emitted:
            continue
        emitted.add((sense_id, text))
        b.add_relation(entry_id, "synonym", text, None, note=note,
                       sense_id=sense_id)


def build_te_aka(con, b):
    sql = ("SELECT word_id, headword, headword_sort, headword_search, part_of_speech, "
           "definition, senses, usage_examples, audio_url, synonyms, filters "
           "FROM te_aka_entries ORDER BY word_id")
    for (wid, hw, hs, hse, pos, d, sj, ux, au, syn, filt) in con.execute(sql):
        # {mi, en} dicts now; bare strings before translations were captured.
        examples = [e for e in jload(ux) if isinstance(e, (str, dict))]
        senses = [s for s in jload(sj) if isinstance(s, dict)]
        loan_marker, filter_domains = split_filters(jload(filt))
        eid = b.add_entry(wid, hw, hs, hse, pos=pos, audio_url=au,
                          loan_marker=loan_marker,
                          locator=f"word_id={wid}",
                          material={"hw": hw, "pos": pos, "def": d, "ex": examples,
                                    "syn": jload(syn), "filt": jload(filt)})
        # te_aka marks the suffix after the POS and again at the head of each
        # sense's definition. Both name the same forms; add_form dedups.
        _add_suffix_forms(b, eid, suffix_forms.strip_suffix_notation(hw),
                          suffix_forms.read_paren_suffixes(hw, b.suffix_tally),
                          "te_aka")

        # Explode the structured senses into per-sense rows, each with its own POS
        # and examples. Drop exact-duplicate senses (some source entries repeat the
        # same def-div N times, e.g. "Rua o Takurua, Te"), then renumber 1..n.
        # Fall back to the packed definition for data parsed before senses existed.
        if not senses:
            # Parsed before senses existed: the entry-level aggregate is all
            # there is, and it belongs to the one sense synthesised here.
            senses = [{"sense_number": 1, "part_of_speech": pos,
                       "gloss_en": d, "definition_raw": d, "examples": examples,
                       "synonyms": jload(syn)}]

        first_sid = None
        seen_senses = {}
        out_no = 0
        emitted = set()
        for s in senses:
            key = _ws(s.get("definition_raw") or s.get("gloss_en") or "").lower()
            if key and key in seen_senses:
                # A repeated def-div. Its synonyms still belong to the sense
                # that won, or they would be dropped with the duplicate row.
                _add_te_aka_synonyms(b, eid, seen_senses[key], s, emitted)
                continue
            out_no += 1
            sid = b.add_sense(eid, out_no, s.get("gloss_en"), None,
                              s.get("definition_raw"),
                              part_of_speech=s.get("part_of_speech"))
            if key:
                seen_senses[key] = sid
            _add_suffix_forms(
                b, eid, suffix_forms.strip_suffix_notation(hw),
                suffix_forms.read_paren_suffixes(
                    s.get("definition_raw") or "", b.suffix_tally),
                "te_aka")
            if first_sid is None:
                first_sid = sid
            for i, ex in enumerate(s.get("examples") or []):
                parsed = te_aka_example(ex)
                if parsed:
                    text, en, cite = parsed
                    b.add_example(sid, eid, text, en, None, cite, i)
            # D46: te Aka states which sense a synonym belongs to, inside that
            # sense's div. The entry-level `synonyms` column is an aggregate
            # the parser also builds, marked "legacy / FTS", and reading it
            # here threw the attribution away: aho's cord senses and its
            # genealogy senses became mutual synonyms.
            _add_te_aka_synonyms(b, eid, sid, s, emitted)

        for fdom in filter_domains:
            b.add_domain(eid, first_sid, fdom, "en")


def build_hepatakakupu(con, b):
    sql = ("SELECT id, word_id, headword, headword_sort, headword_search, "
           "part_of_speech, definition, usage_examples, sense_number, synonyms, "
           "synonym_senses, master_word_id, master_sense, semantic_domain, "
           "suffixes "
           "FROM hepatakakupu_entries ORDER BY word_id, sense_number, id")
    # He Pataka Kupu addresses a sense as (word_id, sense_number) and splits every
    # sense into its own row, so that pair names exactly one entry. Collected on
    # the way through and used afterwards, because a master definition or a
    # synonym can point at a sense that has not been built yet (D35).
    by_sense: dict = {}          # (word_id, sense_number) -> (entry_id, sense_id)
    by_word: dict = {}           # word_id -> headword, for the target text
    by_key_sense: dict = {}      # (headword_search, sense_number) -> (entry_id, sense_id)
    senses_of_word: dict = {}    # word_id -> [(entry_id, sense_id), ...]
    masters: list = []           # (entry_id, master_word_id, master_sense)
    synonym_refs: list = []      # (entry_id, headword, sense, note)
    for (id_, wid, hw, hs, hse, pos, d, ux, sn, syn, syn_senses,
         master_wid, master_sn, dom, suffixes) in con.execute(sql):
        # He Pātaka Kupu word_id is NOT unique per row (same word_id repeats across
        # senses, and some word_ids are shared sentinels), so it cannot be the device-id
        # stem. Use the source row PK — guaranteed unique and stable. word_id is kept in
        # locator for provenance / sense grouping.
        seid = str(id_)
        examples = [e for e in jload(ux) if isinstance(e, str)]
        eid = b.add_entry(seid, hw, hs, hse, pos=pos, locator=f"word_id={wid}",
                          material={"hw": hw, "pos": pos, "def_mi": d, "sn": sn,
                                    "ex": examples, "syn": jload(syn), "dom": dom})
        # hepatakakupu records its suffixes in a separate element, so hw
        # needs no strip_suffix_notation, unlike paekupu. Each row here is
        # one SENSE and mints its own entry, so these forms do not collapse
        # across a word's senses. A headword can still list more than one
        # base spelling ('tīkona, tīkoina') or carry a phrase's parenthetical
        # ('hohou (i te) rongo'); _hepataka_bases splits the former and
        # refuses the latter rather than composing onto it wrongly.
        suffix_tokens = jload(suffixes)
        # Tally the suffix tokens once per entry, not once per base: a
        # second valid base composes the SAME suffix list again, and passing
        # the tally on every iteration would double-count a kept/refused
        # suffix for the rare entry with more than one base.
        for i, base in enumerate(_hepataka_bases(hw, b.suffix_tally)):
            _add_suffix_forms(b, eid, base, suffix_tokens, "hepatakakupu",
                              b.suffix_tally if i == 0 else None)
        sid = b.add_sense(eid, sn, None, d, d, part_of_speech=pos)  # monolingual Māori -> gloss_mi
        for i, ex in enumerate(examples):
            text, src = split_src(ex)
            b.add_example(sid, eid, text, None, src, None, i)
        # A synonym wrapped in parens is one He Pātaka Kupu does not define:
        # '(whārona awatea )'. The parens are a marker about the reference, not
        # part of the term, and passing them through made 734 targets that could
        # never resolve. Strip them and say so in the note instead (D30).
        for sy, sy_sense in pair_synonyms(jload(syn), jload(syn_senses)):
            parsed = parse_synonym(sy)
            if not parsed:
                continue
            synonym_refs.append((
                eid, parsed["headword"], sy_sense,
                None if parsed["has_entry"]
                else "no entry under this word in He Pātaka Kupu"))
        if dom:
            b.add_domain(eid, sid, dom, "mi")

        by_sense[(wid, sn)] = (eid, sid)
        by_word.setdefault(wid, hw)
        by_key_sense[(hse, sn)] = (eid, sid)
        senses_of_word.setdefault(wid, []).append((eid, sid))
        if master_wid:
            masters.append((eid, master_wid, master_sn))

    # A synonym may name the sense it means — 'hikoki (2)'. Because a sense is a
    # row here, that names one entry outright, where the headword alone leaves
    # several for the sweep to judge.
    for eid, target_hw, sy_sense, note in synonym_refs:
        hit = None
        if sy_sense is not None:
            hit = by_key_sense.get((normalise_search_key(target_hw), sy_sense))
        b.add_relation(eid, "synonym", target_hw,
                       hit[0] if hit else None, note=note,
                       target_sense_id=hit[1] if hit else None)

    # 'This sense's authoritative definition lives at word N, sense M.' The
    # source states it for 14,379 senses and names the sense for 9,854 of them.
    for eid, master_wid, master_sn in masters:
        target_hw = by_word.get(master_wid)
        if not target_hw:
            continue
        hit = by_sense.get((master_wid, master_sn))
        if hit is None:
            # No sense named, or none matching: take the word's own sense only
            # when it has exactly one, and otherwise leave the target open.
            rows = senses_of_word.get(master_wid) or []
            hit = rows[0] if len(rows) == 1 else None
        b.add_relation(eid, "master_definition", target_hw,
                       hit[0] if hit else None,
                       note=f"word_id={master_wid}"
                            + (f" sense={master_sn}" if master_sn else ""),
                       target_sense_id=hit[1] if hit else None)


def build_paekupu(con, b):
    sql = ("SELECT slug, headword, headword_sort, headword_search, headword_en, "
           "part_of_speech, definition, definition_mi, usage_examples, audio_url, "
           "alternative_words, subject_areas, subject_area, subject_area_en "
           "FROM paekupu_entries ORDER BY id")
    for (slug, hw, hs, hse, hen, pos, d, dmi, ux, au, alt, subj,
         subj_mi, subj_en) in con.execute(sql):
        examples = [e.strip() for e in jload(ux) if isinstance(e, str)]
        raw = (d or "") + (" || MI: " + dmi if dmi else "")
        eid = b.add_entry(slug, hw, hs, hse, pos=pos, headword_en=hen, audio_url=au,
                          locator=f"slug={slug}",
                          material={"hw": hw, "hen": hen, "pos": pos, "def": d,
                                    "def_mi": dmi, "ex": examples, "alt": jload(alt),
                                    "subj": jload(subj)})
        # 79% of Paekupu entries carry no definition, only the English headword
        # the Māori term was coined for. That headword IS the gloss; without this
        # projection 13,050 senses hold POS and nothing else (D1).
        sid = b.add_sense(eid, None, d or hen, dmi, raw, part_of_speech=pos)
        # The suffix is written into the headword ('ahu ~nga'). A headword can
        # hold more than one base spelling ('hae, hahae ~a ~nga') or be a
        # compound whose suffix lands on the whole thing ('ārai hapū ~tanga');
        # composition_bases tells the two apart.
        suffixes = suffix_forms.read_tilde_suffixes(hw, b.suffix_tally)
        for base in suffix_forms.composition_bases(hw):
            # hw, not base: the notation has been stripped out of base, and
            # its POSITION is what says which word takes the suffix —
            # 'heke (~nga) atu' is 'hekenga atu'.
            _add_suffix_forms(b, eid, base, suffixes, "paekupu",
                              marked_headword=hw)
        # A tilde run the vocabulary does not recognise is a whole irregular
        # derivation, not a suffix — 'hau ~hāua'. It is stored as printed;
        # composing it would assert a word no source holds.
        _add_whole_forms(
            b, eid, suffix_forms.read_whole_forms(hw, b.suffix_tally),
            "paekupu")
        for i, ex in enumerate(examples):
            b.add_example(sid, eid, ex, None, None, None, i)   # Paekupu example = Māori only
        # alternative_words are not alternative spellings. A dashed item is a
        # component of the coined term with its meaning — the same shape as Te
        # Matatiki's derivations — and a plain one is another term for the same
        # concept. Neither is a variant form, and 11,875 of them were the bulk
        # of every form row in the corpus.
        for w in jload(alt):
            parsed = parse_alternative(w if isinstance(w, str) else str(w))
            if not parsed:
                continue
            if parsed["rel_type"] == "loan_marker":
                # Paekupu marks a borrowing inside alternative_words; it belongs
                # on the entry, where the etymology filter can see it.
                con.execute("UPDATE entry SET loan_marker = ? WHERE id = ?",
                            (parsed["note"], eid))
                continue
            b.add_relation(eid, parsed["rel_type"], parsed["target"],
                           note=parsed["note"])
        # The curriculum learning areas are bilingual in the source:
        # subject_area 'Pūtaiao' / subject_area_en 'Science'. The builder used
        # `subject_areas` instead — a JSON list of URL slugs ('ngā-toi') — and
        # tagged all 16,486 of them 'en' though every value was Māori.
        # domain_lang is the only thing telling the app how to render these.
        if subj_mi:
            b.add_domain(eid, sid, subj_mi, "mi")
        if subj_en:
            b.add_domain(eid, sid, subj_en, "en")


# Tokens papakupu writes that no rule reaches, resolved by the project
# owner's judgement rather than by evidence in the strings.
#
# 'uku ~i' composes to 'ukui', which ends in no vocabulary suffix and is not
# a reduplication. It is another FORM of 'uku' — the passives are 'ukua' and
# 'ukuia' — so it is a variant, not a derived form. Seven sources hold the
# word, most spelling it 'ūkui'; papakupu's own spelling is kept, as
# everywhere else.
#
# A named exception, deliberately. Encoding it as a rule would mean claiming
# that any token composing to an attested word is a variant, and the
# reduplications ('~rau', '~ue', '~uwhi') compose to attested words too.
_PAPAKUPU_RULED = {("uku", "i"): "variant"}


def build_papakupu(con, b):
    sql = ("SELECT id, headword, headword_sort, headword_search, part_of_speech, "
           "definition, usage_examples, variant_forms, see_also, source_code, "
           "loan_marker, sense_number, pdf_page FROM papakupu_entries ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, vf, sa, sc, lm, sn, pg) in con.execute(sql):
        # usage_examples are {text_mi, text_en, source_abbrev} dicts (02_papakupu_extract).
        examples = [e for e in jload(ux) if isinstance(e, dict)]
        eid = b.add_entry(id_, hw, hs, hse, pos=pos, loan_marker=lm,
                          locator=f"pdf p{pg}; src {sc}" if pg else sc,
                          material={"hw": hw, "pos": pos, "def": d, "ex": examples,
                                    "vf": jload(vf), "sa": jload(sa), "lm": lm})
        # gloss_en holds the definition only; the raw blob (def + examples + notes)
        # is preserved in definition_raw. clean_gloss strips everything from the
        # first example onward so example text never bleeds into the gloss.
        gloss = clean_gloss(d, [e.get("text_mi") for e in examples])
        sid = b.add_sense(eid, sn, gloss, None, d, part_of_speech=pos)
        base = suffix_forms.strip_suffix_notation(hw)
        # The bracket notation is inside the headword and its position
        # matters — 'tau [-ria] mai' is 'tauria mai'.
        _add_suffix_forms(
            b, eid, base,
            suffix_forms.read_bracket_suffixes(hw, b.suffix_tally), "papakupu",
            marked_headword=hw)
        # The tilde notation lives in the DEFINITION and composes onto the
        # headword, so there is no mark inside the headword to position by.
        # tight=True because the definition is also prose: papakupu writes
        # 'puri ~ puru' for "puri or puru" and 'Te ~ He hapū' with the
        # tilde standing in for the headword, and both are spaced where
        # real notation is not.
        _add_suffix_forms(
            b, eid, base,
            suffix_forms.read_tilde_suffixes(d or "", b.suffix_tally,
                                             tight=True), "papakupu")
        # The same notation can repeat the headword instead of suffixing it
        # — 'ue ~ue' is 'ueue'. Stored as a form of the base, like the
        # passives above, because that is what the notation names: a form
        # on this entry, not a claim about another entry.
        for form in suffix_forms.read_tilde_reduplications(
                base, d or "", b.suffix_tally):
            if b.add_form(eid, form, "reduplication", f"~{form[len(base):]} (papakupu)"):
                b.derived_forms_written += 1
        # A token can be neither a suffix nor a doubling and still compose
        # into a word that ENDS in one — 'mea ~tingia' gives 'meatingia',
        # ending '-ngia'. Runs after the reduplication reader, which would
        # otherwise lose 'hokohokoa' to its final '-a'. The note carries the
        # suffix the ending shows, so per-suffix counts stay answerable, and
        # ', by ending' marks a class read off the form rather than printed.
        for form, form_type, suffix in suffix_forms.read_tilde_by_ending(
                base, d or "", b.suffix_tally):
            if b.add_form(eid, form, form_type,
                          f"{suffix} (papakupu, by ending)"):
                b.derived_forms_written += 1
        # Last, the tokens no rule reaches, resolved by judgement.
        for (ruled_hw, ruled_tok), ruled_type in _PAPAKUPU_RULED.items():
            if suffix_forms.fold(base) != suffix_forms.fold(ruled_hw):
                continue
            if ruled_tok not in suffix_forms.read_raw_tilde_tokens(d or ""):
                continue
            if b.add_form(eid, suffix_forms.compose(base, ruled_tok),
                          ruled_type, f"~{ruled_tok} (papakupu, ruled)"):
                b.derived_forms_written += 1
                b.suffix_tally.reclassify("-" + ruled_tok, "ruled")
        for i, ex in enumerate(examples):
            b.add_example(sid, eid, ex.get("text_mi"), ex.get("text_en"),
                          ex.get("source_abbrev"), None, i)
        for v in jload(vf):
            b.add_form(eid, v if isinstance(v, str) else str(v), "variant")
        for t in jload(sa):
            b.add_relation(eid, "see_also", t if isinstance(t, str) else str(t))
    _papakupu_reduplications(con, b)


def _papakupu_reduplications(con, b):
    """derived_from relations for the reduplications papakupu states.

    A second pass, not an inline call. The inverse shape is stated on the
    BASE's entry — 'hoko: In the reduplicated forms hohoko and hokohoko' —
    while the relation belongs on the child's, and the child may not have
    been minted when its base row was read.

    The base's sense number is used when the source gives one: 'eke [2]' is
    a different papakupu row from 'eke [1]', and the rows are not stored in
    sense order, so the number has to be matched rather than counted. A
    pair stated from both ends keeps the statement that carries the
    number, whichever row came first.

    A pair whose other end papakupu does not hold is dropped. The word often
    exists in another source — 'taketake' is a headword in 26 — but
    papakupu names no source, so choosing one would invent a pointer it
    never made, and 53_build_word_origin drops an unresolved derived_from
    anyway.
    """
    # headword_search -> {sense_number or None: entry_id}
    index = {}
    for eid, key, sense in con.execute(
            "SELECT e.id, e.headword_search, p.sense_number "
            "  FROM entry e JOIN papakupu_entries p "
            "    ON p.id = CAST(e.source_entry_id AS INTEGER) "
            " WHERE e.source_id = 'papakupu'"):
        index.setdefault(normalise_search_key(key), {})[sense] = eid

    def resolve(word, sense=None):
        by_sense = index.get(normalise_search_key(word))
        if not by_sense:
            return None
        if sense is not None:
            # Stated but absent: papakupu pointed at a sense this extract
            # does not hold. Falling through to another sense of the right
            # word would attach the derivation somewhere the source never
            # named, and 53_build_word_origin stamps these 'certain'. Refuse
            # instead, the way pick_target refuses to guess (D32).
            return by_sense.get(sense)
        # No number is no claim, so the lowest sense is the honest default —
        # the same one _first_sense applies everywhere else.
        return by_sense[sorted(by_sense, key=lambda s: (s is None, s))[0]]

    # A pair can be stated from both ends, and only the forward statement
    # carries the base's sense number. papakupu prints the two in no fixed
    # order, so collect first and keep the richer record; taking whichever
    # row id came first would silently drop the number.
    best, order = {}, []
    for hw, definition in con.execute(
            "SELECT headword, definition FROM papakupu_entries ORDER BY id"):
        for child, base, sense in reduplication.read_reduplications(hw, definition):
            key = (reduplication.fold(child), reduplication.fold(base))
            if key not in best:
                best[key] = (child, base, sense)
                order.append(key)
            elif sense is not None and best[key][2] is None:
                best[key] = (child, base, sense)
    for key in order:
        child, base, sense = best[key]
        child_eid, base_eid = resolve(child), resolve(base, sense)
        if child_eid is None or base_eid is None or child_eid == base_eid:
            continue
        b.add_relation(child_eid, "derived_from", base, base_eid,
                       note="reduplication")


def build_taikupu(con, b):
    sql = ("SELECT source_entry_id, headword, headword_sort, headword_search, "
           "definition, usage_examples, level FROM taikupu_entries ORDER BY id")
    for (seid, hw, hs, hse, d, ux, lvl) in con.execute(sql):
        # usage_examples are {text_mi, text_en} dicts (40_taikupu_import).
        examples = [e for e in jload(ux) if isinstance(e, dict)]
        eid = b.add_entry(seid, hw, hs, hse,
                          locator=f"level {lvl}" if lvl is not None else None,
                          material={"hw": hw, "def": d, "ex": examples, "lvl": lvl})
        # english gloss -> gloss_en; raw blob preserved in definition_raw.
        sid = b.add_sense(eid, None, d, None, d)
        for i, ex in enumerate(examples):
            b.add_example(sid, eid, ex.get("text_mi"), ex.get("text_en"), None, None, i)


def build_temarareo(con, b):
    """Te Māra Reo Māori plant names -> unified core.

    Only the Māori-name slice unifies; the protoform pages are an etymology source
    and are projected into ETY_* by 52_build_etymology_unified.py instead.

    Two grades of record share the table. A name with a page of its own carries a
    real definition; a name that only appears in the index does not, and for those
    the species list IS the definition the source gives, so it becomes the gloss
    rather than leaving the sense empty. `has_page` keeps the two distinguishable.
    """
    sql = ("SELECT source_entry_id, headword, headword_sort, headword_search, "
           "definition, note, species, related_names, ppn_form, stage_no, "
           "stage_name, page, url, has_page FROM temarareo_entries ORDER BY id")
    for (seid, hw, hs, hse, definition, note, species, related, ppn, stage_no,
         stage_name, page, url, has_page) in con.execute(sql):
        sp = dedupe_species([s for s in jload(species) if isinstance(s, str)])
        rel = [r for r in jload(related) if isinstance(r, dict)]

        # stage_name ('P. Polynesian', 'P. Oceanic') is a proto-language
        # reconstruction level, not a semantic domain — it used to be written to
        # entry_domain, which is for subject areas. Its real home is the
        # etymology layer, where ETY_cognateset.level already carries it for
        # these entries; it rides along in the locator so the provenance string
        # still names the stage it came from.
        locator = "; ".join(filter(None, [
            page or "index",
            f"stage {stage_no} ({stage_name})" if stage_no and stage_name
            else (f"stage {stage_no}" if stage_no else None),
            f"*{ppn}" if ppn else None,
        ]))
        eid = b.add_entry(seid, hw, hs, hse, pos="noun", locator=locator,
                          material={"hw": hw, "def": definition, "note": note,
                                    "sp": sp, "ppn": ppn, "stage": stage_no})
        # gloss_en is the definition where the source gives one, else the species it
        # names; definition_raw keeps the record without repeating itself — only
        # the species the definition does not already name are appended.
        definition = clean_definition(definition)
        # 16 records carry their content in `note` alone — '"stalk, stem" [a word
        # once associated with the coconut (niu)]' — and were left glossless.
        gloss = (definition or ("; ".join(sp) if sp else None)
                 or ((note or "").strip() or None))
        raw = build_raw(definition, note, sp)
        sid = b.add_sense(eid, None, gloss, None, raw, part_of_speech="noun")
        # Plant names discussed on the page — attested in its prose, not headwords of
        # their own, so they are cross-references rather than entries.
        for r in rel:
            for name in r.get("names", []):
                b.add_relation(eid, "see_also", name, note=r.get("literal_meaning"))


# --- Wakareo components (session 67) --------------------------------------
# Five components are English-headword. They are INVERTED here so
# entry.headword is always Māori: one entry per Māori equivalent, carrying the
# English lemma in headword_en, with siblings cross-linked as synonyms. The
# landing table keeps the true one-lemma-many-equivalents shape.
#
# Siblings share a WR- reference, so source_entry_id is suffixed '#1', '#2', …
# to stay distinct. Duplicate Māori headwords are NOT deduped — same rule as
# taikupu; homonym_no stays NULL.


def _fold_qualifier(lemma_en, qual):
    """Compose 'lemma (qualifier)' without double-parenthesising.

    qualifier is the fidelity layer and may already arrive parenthesised
    (Kimikupu: '(become absorbed)') or bare (never seen yet, but other
    EN->MI sources are unpopulated and may supply either shape once the
    full sweep runs) — handle both without touching the stored value.
    """
    if not qual:
        return lemma_en
    q = qual.strip()
    if q.startswith("(") and q.endswith(")"):
        return f"{lemma_en} {q}"
    return f"{lemma_en} ({q})"


def _wakareo_en_mi(con, b, table):
    # body_text feeds definition_raw (`raw` below), the app-facing text; the
    # archive's body_raw HTML must never land there. body_raw is read only to
    # recover kimikupu_hou's suffix marker, which body_text's stripped
    # version usually loses (empty for 2,823 of 2,831 rows) — it is used for
    # that lookup alone and never stored in raw/definition_raw.
    sql = (f"SELECT source_entry_id, wakareo_id, headword, part_of_speech, search_scope, "
           f"equivalents, qualifier, example_en, example_mi, body_text, body_raw "
           f"FROM {table} ORDER BY id")
    for (seid, wid, lemma_en, pos, scope, equivs, qual, ex_en, ex_mi, raw,
         body_raw) in con.execute(sql):
        # Wakareo caps this run at 50 characters, so the last equivalent can be
        # a fragment: 'atawhai, atawhait' is 'atawhaitia' cut short. Minting an
        # entry for 'whakah' asserts a word the source never did (D31).
        equivalents = drop_truncated_tail(jload(equivs))
        if not equivalents:
            continue                      # nothing to hang a Māori headword on
        variants = jload(scope)
        # The qualifier narrows the English lemma ('(balanced)' + 'View, argument');
        # fold it into the gloss so it is not lost at the unified layer.
        gloss = _fold_qualifier(lemma_en, qual)
        # One record, one example — but it illustrates only the equivalent it
        # actually uses. Attaching it to every sibling puts a sentence on an
        # entry whose headword it never contains.
        owners = set(example_owners(equivalents, ex_mi))
        siblings = []
        # ngata prints a base and its derived form in one comma-separated run;
        # the equivalents list is already that run, parsed. Only the spellings
        # say which pairs are derivations rather than synonyms.
        source = table.replace("_entries", "")
        pairs = suffix_forms.derived_from_list(equivalents, b.suffix_tally)
        raw_suffixes = suffix_forms.read_paren_suffixes(
            body_raw or "", b.suffix_tally)
        for i, mi in enumerate(equivalents, start=1):
            # seid alone is NOT unique (shared print reference); wakareo_id makes it so.
            eid = b.add_entry(
                f"{seid}#{wid}~{i}", mi, normalise_sort_key(mi), normalise_search_key(mi),
                pos=pos, headword_en=lemma_en,
                material={"hw": mi, "en": lemma_en, "ex": [ex_en, ex_mi]})
            sid = b.add_sense(eid, None, gloss, None, raw, part_of_speech=pos)
            if mi in owners:
                b.add_example(sid, eid, ex_mi, ex_en, None, None, 0)
            for v in variants:
                b.add_form(eid, v, "variant")
            for base, derived, suffix in pairs:
                if base == mi:
                    form_type = suffix_forms.classify(suffix_forms.fold(suffix))
                    if form_type:
                        if b.add_form(eid, derived, form_type,
                                      f"{suffix} ({source})"):
                            b.derived_forms_written += 1
            # kimikupu_hou marks the suffix inside <B> in the raw body; its
            # body_text column is empty for 2,823 of 2,831 rows. mi itself
            # can still carry its own paren notation ('tūtōkai (-tia)'), so
            # compose against the bare form or the suffix glues onto the
            # closing paren instead of the word.
            _add_suffix_forms(b, eid, suffix_forms.strip_suffix_notation(mi),
                              raw_suffixes, source)
            siblings.append((eid, mi))
        # The run holds derivations and synonyms together, and `pairs` above
        # already separated them. Cross-filing the whole run as synonyms says
        # 'ahu' means the same as 'ahutia', which it does not — one is the
        # other's passive. Only the pairs the suffix rules did NOT claim are
        # synonyms of each other.
        bases_of = {}
        for base, derived, _suffix in pairs:
            bases_of.setdefault(derived, set()).add(base)
        for eid, mi in siblings:
            for other_eid, other_mi in siblings:
                if other_eid == eid:
                    continue
                if other_mi in bases_of.get(mi, ()):
                    b.add_relation(eid, "derived_from", other_mi, other_eid)
                elif mi in bases_of.get(other_mi, ()):
                    # The inverse of a derived_from already written from the
                    # other end. derivation.base_entry_id is indexed, so the
                    # pair reads from either side without a second row, and
                    # no rel_type says 'has a derived form'.
                    continue
                else:
                    b.add_relation(eid, "synonym", other_mi, other_eid)


def _williams_page_index(con) -> dict:
    """{headword_search: [(page_number, unified entry.id)]} for Williams.

    Te Matatiki's derivation codes are Williams PAGE numbers, so page + word is
    the resolution key. Empty when Williams has not been projected yet, in which
    case derivations stay unresolved exactly as they were before.
    """
    index = {}
    sql = ("SELECT w.headword_search, w.page_number, e.id "
           "FROM williams_entries w "
           "JOIN entry e ON e.source_id='williams' "
           "               AND e.source_entry_id = CAST(w.id AS TEXT) "
           "WHERE w.page_number IS NOT NULL")
    for hws, page, eid in con.execute(sql):
        index.setdefault(hws, []).append((page, eid))
    return index


def _resolve_williams(index: dict, word: str, page: int | None):
    """Entry id for `word` on Williams page `page`, tolerating a page-break ±1."""
    if not word or page is None:
        return None
    candidates = index.get(normalise_search_key(word))
    if not candidates:
        return None
    for tolerance in (0, 1):
        for p, eid in candidates:
            if abs(p - page) <= tolerance:
                return eid
    return None


def _wakareo_mi_en(con, b, table, matatiki=False):
    extra = ", derivation, williams_refs" if matatiki else ""
    williams_index = _williams_page_index(con) if matatiki else {}
    sql = (f"SELECT source_entry_id, wakareo_id, headword, part_of_speech, search_scope, "
           f"gloss_en, body_text{extra} FROM {table} ORDER BY id")
    for row in con.execute(sql):
        seid, wid, hw, pos, scope, gloss, raw = row[:7]
        # seid alone is NOT unique (shared print reference); wakareo_id makes it so.
        eid = b.add_entry(f"{seid}#{wid}", hw, normalise_sort_key(hw), normalise_search_key(hw),
                          pos=pos, material={"hw": hw, "gloss": gloss})
        b.add_sense(eid, None, gloss, None, raw, part_of_speech=pos)
        for v in jload(scope):
            b.add_form(eid, v, "variant")
        if matatiki:
            # The derivation's source WORD is the target; the W.nnn code is the
            # Williams page it sits on, which disambiguates homographs for free.
            for part in parse_derivation(row[7]):
                word = part["word"] or hw          # a bare [W.nnn] cites the headword
                target = (_resolve_williams(williams_index, word, part["page"])
                          if part["ref"] == "W" else None)
                b.add_relation(eid, "cross_ref", word, target,
                               note=part["gloss"][:500] or None)


def build_tregear_exceptions(con, b):
    """Tregear exceptions: recover the structure the source already labelled.

    Every section is bold-labelled (`Maori Example:`, `Compare With:`,
    `Word Base:`, `See Also:`, `Comments:`) and nothing consumed them, so senses,
    examples, citations, cross-references and editorial notes all landed as prose
    in one sense row. parse_tregear reads body_raw — the markup IS the structure,
    which is why the archive is kept.
    """
    sql = ("SELECT source_entry_id, wakareo_id, headword, part_of_speech, "
           "search_scope, body_text, body_raw FROM tregear_exceptions_entries "
           "ORDER BY id")
    for seid, wid, hw, pos, scope, text, raw in con.execute(sql):
        p = parse_tregear(raw)
        eid = b.add_entry(f"{seid}#{wid}", hw, normalise_sort_key(hw),
                          normalise_search_key(hw), pos=pos, dialect=p["dialect"],
                          material={"hw": hw, "gloss": text})
        senses = p["senses"] or ([text] if text else [None])
        first_sid = None
        for n, sense_text in enumerate(senses, start=1):
            sid = b.add_sense(eid, n if len(senses) > 1 else None, sense_text, None,
                              sense_text, part_of_speech=pos,
                              note=p["comments"] if n == 1 else None)
            first_sid = first_sid or sid
        # Which sense an example illustrates is a judgement call, not a parse:
        # park them on the first and let the audit sweep reassign.
        for i, ex in enumerate(p["examples"]):
            b.add_example(first_sid, eid, ex["text"], None, None, ex["citation"], i)
        for v in jload(scope):
            b.add_form(eid, v, "variant")
        for part in p["compare"] + p["word_base"]:
            b.add_relation(eid, "cross_ref", part["word"], None, note=part["gloss"])
        for target in p["see_also"]:
            b.add_relation(eid, "see_also", target, None)
def build_tai_kupu_variants(con, b):   _wakareo_mi_en(con, b, "tai_kupu_variants_entries")
def build_nga_tini_a_tangaroa(con, b): _wakareo_mi_en(con, b, "nga_tini_a_tangaroa_entries")
def build_maori_law_lexicon(con, b):   _wakareo_mi_en(con, b, "maori_law_lexicon_entries")
def build_te_matatiki(con, b):         _wakareo_mi_en(con, b, "te_matatiki_entries", matatiki=True)

def build_ngata(con, b):           _wakareo_en_mi(con, b, "ngata_entries")
def build_kimikupu_hou(con, b):    _wakareo_en_mi(con, b, "kimikupu_hou_entries")
def build_he_kupu_arotake(con, b): _wakareo_en_mi(con, b, "he_kupu_arotake_entries")
def build_kupu_rorohiko(con, b):   _wakareo_en_mi(con, b, "kupu_rorohiko_entries")
def build_kupu_mataora(con, b):    _wakareo_en_mi(con, b, "kupu_mataora_entries")


BUILDERS = {
    "williams": build_williams,
    "te_aka": build_te_aka,
    "hepatakakupu": build_hepatakakupu,
    "paekupu": build_paekupu,
    "papakupu": build_papakupu,
    "taikupu": build_taikupu,
    "temarareo": build_temarareo,
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


def core_tables_exist(con) -> bool:
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    return all(t in have for t in CORE_TABLES)


# External link tables that FK-reference entry.id: pollex_entry_links (08b) and
# ETY_entry_link (52). Entry ids regenerate on every unify, so their links are
# stale after any rebuild regardless; with foreign_keys=ON they also block
# delete_source_slice. Clear them up front (same rule as 52's global link
# tables) and re-run 08b + 52 afterwards (see docs/UPDATE_WORKFLOW.md).
ENTRY_LINK_TABLES = ("pollex_entry_links", "ETY_entry_link")


def clear_entry_link_tables(con) -> int:
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    n = 0
    for t in ENTRY_LINK_TABLES:
        if t in have:
            n += con.execute(f"DELETE FROM {t}").rowcount
    con.commit()
    return n


def delete_source_slice(con, source_id):
    """Remove one source's rows from every core table (children first, FK-safe)."""
    ids = [r[0] for r in con.execute(
        "SELECT id FROM entry WHERE source_id=?", (source_id,))]
    if not ids:
        return 0
    con.execute("DELETE FROM example WHERE entry_id IN "
                "(SELECT id FROM entry WHERE source_id=?)", (source_id,))
    con.execute("DELETE FROM entry_domain WHERE entry_id IN "
                "(SELECT id FROM entry WHERE source_id=?)", (source_id,))
    con.execute("DELETE FROM relation WHERE entry_id IN "
                "(SELECT id FROM entry WHERE source_id=?)", (source_id,))
    con.execute("DELETE FROM form WHERE entry_id IN "
                "(SELECT id FROM entry WHERE source_id=?)", (source_id,))
    # concept_member is NOT a projection: it holds sweep judgements. entry_id
    # and sense_id are only a cache of where the sense currently lives, so the
    # rebuild nulls the cache and 54_build_concepts re-resolves it from the
    # stable (source_id, source_entry_id, sense_number) address.
    try:
        con.execute(
            "UPDATE concept_member SET entry_id = NULL, sense_id = NULL "
            " WHERE entry_id IN (SELECT id FROM entry WHERE source_id = ?)",
            (source_id,))
    except sqlite3.OperationalError:
        pass            # table not present in an older DB

    # derivation and loan_origin are pure projections of the core, rebuilt in
    # full by 53_build_word_origin, so their rows for this source are dropped
    # rather than released — including ones where this source is the BASE of
    # someone else's derivation, which would otherwise block the delete.
    for sql in (
        "DELETE FROM derivation WHERE entry_id IN "
        "(SELECT id FROM entry WHERE source_id=?) "
        "   OR base_entry_id IN (SELECT id FROM entry WHERE source_id=?)",
        "DELETE FROM loan_origin WHERE entry_id IN "
        "(SELECT id FROM entry WHERE source_id=?)",
    ):
        try:
            con.execute(sql, (source_id, source_id) if "base_entry_id" in sql
                        else (source_id,))
        except sqlite3.OperationalError:
            pass            # table not present in an older DB

    # Sense-level references from other tables must be released before the
    # senses go. Both were added with sense addressability and would otherwise
    # make a source impossible to rebuild — the same failure the relation
    # target_entry_id release below was added for, one level down.
    for sql in (
        "UPDATE ETY_entry_link SET sense_id = NULL WHERE sense_id IN "
        "(SELECT s.id FROM sense s JOIN entry e ON e.id = s.entry_id "
        " WHERE e.source_id = ?)",
        "UPDATE relation SET target_sense_id = NULL WHERE target_sense_id IN "
        "(SELECT s.id FROM sense s JOIN entry e ON e.id = s.entry_id "
        " WHERE e.source_id = ?)",
    ):
        try:
            con.execute(sql, (source_id,))
        except sqlite3.OperationalError:
            pass            # column not present in an older DB
    con.execute("DELETE FROM sense WHERE entry_id IN "
                "(SELECT id FROM entry WHERE source_id=?)", (source_id,))
    # Relations from OTHER sources may point into this one — Te Matatiki
    # derivations resolve to Williams entries — and those foreign keys would
    # block the delete. Release them, then say which sources must be re-unified
    # to earn their targets back; the rows survive, only the resolution is lost.
    has_target = any(r[1] == "target_entry_id"
                     for r in con.execute("PRAGMA table_info(relation)"))
    dangling = con.execute(
        "SELECT e.source_id, COUNT(*) FROM relation r "
        "JOIN entry e ON e.id = r.entry_id "
        "WHERE r.target_entry_id IN (SELECT id FROM entry WHERE source_id=?) "
        "  AND e.source_id <> ? GROUP BY e.source_id",
        (source_id, source_id)).fetchall() if has_target else []
    if dangling:
        con.execute(
            "UPDATE relation SET target_entry_id = NULL WHERE target_entry_id IN "
            "(SELECT id FROM entry WHERE source_id=?)", (source_id,))
        detail = ", ".join(f"{src} ({n})" for src, n in dangling)
        print(f"unresolved {detail} -> {source_id}; re-run "
              f"50_build_unified.py --source " + " --source ".join(s for s, _ in dangling))
    con.execute("DELETE FROM entry WHERE source_id=?", (source_id,))
    return len(ids)


def resolve_te_aka_synonyms(con):
    """Resolve relation.note 'te_aka_word_id=N' stubs to target_entry_id (entry.id).

    Runs after all te_aka entries exist. Two passes:
      1. word_id match — synonym.word_id == entry.source_entry_id (the primary key).
      2. headword fallback — for rows still NULL, match the synonym's target_headword
         to a te_aka entry by headword_search, but ONLY when exactly one te_aka entry
         carries that key (skip homographs to avoid mislinking). Te Aka renumbers
         word_ids over time, so a stale word_id can miss an entry that still exists
         under the same headword (e.g. synonym word_id=8095 -> 'tumera', which now
         lives under source_entry_id 37049).

    Targets that resolve by neither pass (headword absent from the corpus, or
    ambiguous) keep target_entry_id NULL but retain the note for provenance; the app
    renders them as plain (non-clickable) text.
    """
    con.execute("""
        UPDATE relation
           SET target_entry_id = (
               SELECT e.id FROM entry e
                WHERE e.source_id = 'te_aka'
                  AND e.source_entry_id = substr(relation.note, length('te_aka_word_id=') + 1))
         WHERE relation.note LIKE 'te_aka_word_id=%'
           AND relation.entry_id IN (SELECT id FROM entry WHERE source_id = 'te_aka')
    """)

    # Pass 2: headword fallback for unresolved stubs. Build a search-key -> [entry.id]
    # index over te_aka entries; only unambiguous (single-entry) keys are linkable.
    by_key = {}
    for eid, hwk in con.execute(
            "SELECT id, headword_search FROM entry WHERE source_id = 'te_aka'"):
        by_key.setdefault(hwk, []).append(eid)

    unresolved = con.execute(
        "SELECT r.id, r.target_headword FROM relation r "
        "JOIN entry e ON e.id = r.entry_id "
        "WHERE e.source_id = 'te_aka' AND r.rel_type = 'synonym' "
        "  AND r.target_entry_id IS NULL "
        "  AND r.note LIKE 'te_aka_word_id=%' "
        "  AND r.target_headword IS NOT NULL").fetchall()

    recovered = 0
    for rid, target_hw in unresolved:
        cands = by_key.get(normalise_search_key(target_hw))
        if cands and len(cands) == 1:
            con.execute("UPDATE relation SET target_entry_id=? WHERE id=?",
                        (cands[0], rid))
            recovered += 1
    return recovered


def resolve_williams_xrefs(con):
    """Resolve Williams see_also relations to target_entry_id (entry.id).

    Each see_also row holds the raw '‖' target Williams printed (e.g. "apa (i), 2",
    "mataaho, tiaho"). parse_see_also_targets() strips the decoration into linkable
    (search_key, roman_sense, spelling) triples; each is matched against a Williams
    entry by headword_search, preferring the homograph with the same roman sense,
    then the one whose spelling matches exactly — Williams lower-cases a target but
    keeps its macrons, so 'ho' is `Ho` and not `Hō`. Where neither decides, no link
    is made; pick_target refuses to guess (D32).

    Multi-target strings are SPLIT: the first match updates the existing row, each
    further match inserts a new see_also row (raw kept in note for provenance).
    Citations, cognate/relative pointers, and unmatched headwords stay NULL.

    Returns (rows_resolved, rows_total).
    """
    # headword_search -> [(entry_id, roman_sense, display_headword), ...]  (williams only)
    by_key = {}
    for eid, hwk, rsense, disp in con.execute(
            "SELECT e.id, w.headword_search, w.sense_number, w.headword "
            "FROM entry e JOIN williams_entries w "
            "  ON w.id = CAST(e.source_entry_id AS INTEGER) "
            "WHERE e.source_id = 'williams'"):
        by_key.setdefault(hwk, []).append((eid, rsense, disp))

    def match(key, sense, word):
        return pick_target(by_key.get(key) or [], sense, word)

    # variant_of is the same kind of pointer and goes through the same
    # resolver. Williams marks a variant with '=' at the head of an entry
    # ('Ahine. = wahine.') and a compare with the '‖' bar; both name a
    # headword and both carry a roman sense pointer when they need one. Only
    # see_also was ever selected here, which is why see_also was 73% resolved
    # against variant_of's 32% — 150 of 542 unresolved variant_of rows match
    # unambiguously with no new machinery.
    rows = con.execute(
        "SELECT r.id, r.entry_id, r.target_headword, r.rel_type FROM relation r "
        "JOIN entry e ON e.id = r.entry_id "
        "WHERE r.rel_type IN ('see_also', 'variant_of') "
        "  AND e.source_id = 'williams' "
        "  AND r.target_entry_id IS NULL").fetchall()

    resolved = 0
    for rid, entry_id, raw, rel_type in rows:
        hits = [m for m in (match(k, sn, w)
                            for k, sn, w in see_also_spellings(raw)) if m]
        if not hits:
            continue
        first_eid, first_disp = hits[0]
        note = raw if (len(hits) > 1 or first_disp != raw) else None
        con.execute("UPDATE relation SET target_entry_id=?, target_headword=?, note=? "
                    "WHERE id=?", (first_eid, first_disp, note, rid))
        for eid, disp in hits[1:]:
            # The split rows keep the ORIGINAL kind: a variant with several
            # targets is several variants, not several compare-links.
            con.execute("INSERT INTO relation (entry_id, rel_type, target_headword, "
                        "target_entry_id, note) VALUES (?,?,?,?,?)",
                        (entry_id, rel_type, disp, eid, raw))
        resolved += 1
    return resolved, len(rows)


def resolve_williams_parents(con):
    """Point each Williams sub-entry at the base whose paragraph printed it.

    Williams sets a derivative inside its base entry: 'Iti, a. Small ... itinga,
    n. Childhood, youth.' 01_williams_parse splits those out and records the base
    as parent_headword on 3,032 rows, and until D36 the import dropped it, so the
    derivation the source states by layout never reached the database.

    The parent string is the printed headword and carries its decoration, so
    parent_candidates offers the keys worth trying in order and pick_target
    settles a homograph on the roman marker or the spelling, refusing to guess
    otherwise — the same contract as see_also.

    Returns (rows_resolved, rows_total).
    """
    by_key: dict = {}
    for eid, hwk, rsense, disp in con.execute(
            "SELECT e.id, w.headword_search, w.sense_number, w.headword "
            "FROM entry e JOIN williams_entries w "
            "  ON w.id = CAST(e.source_entry_id AS INTEGER) "
            "WHERE e.source_id = 'williams'"):
        by_key.setdefault(hwk, []).append((eid, rsense, disp))

    rows = con.execute(
        "SELECT e.id, w.headword, w.parent_headword FROM entry e "
        "JOIN williams_entries w ON w.id = CAST(e.source_entry_id AS INTEGER) "
        "WHERE e.source_id = 'williams' AND w.parent_headword IS NOT NULL").fetchall()

    emitted = 0
    for entry_id, child_hw, raw in rows:
        # Only a parent the child's own spelling attests. Without this, 308 of
        # 1,875 resolved rows asserted a derivation that is not one — 'itinga'
        # from 'Itaupa', 'atawhai' from 'atatuhi' — because the recorded parent
        # is sometimes just the previous headword on the page.
        hit = None
        for key, sense in supported_parents(raw, child_hw):
            hit = pick_target(by_key.get(key) or [], sense, key)
            if hit:
                break
        if not hit or hit[0] == entry_id:
            continue
        target_id, display = hit
        con.execute(
            "INSERT INTO relation (entry_id, rel_type, target_headword, "
            "target_entry_id, note) VALUES (?,?,?,?,?)",
            (entry_id, "derived_from", display, target_id,
             None if display == raw else raw))
        emitted += 1
    con.commit()
    return emitted, len(rows)


def first_seen_snapshot(con, source_id) -> dict:
    """Preserve first_seen across a rebuild, keyed by source_entry_id."""
    return {r[0]: r[1] for r in con.execute(
        "SELECT source_entry_id, first_seen FROM entry WHERE source_id=?", (source_id,))}


_TALLY_NOUN = {"suffix": "tokens", "pair": "pair tests",
               "base": "bases", "whole": "whole forms",
               "reduplication": "reduplications",
               "ruled": "by ruling"}


def format_suffix_report(source_id, rows_written, tally):
    """Spec §6's refusal report, one line per kind. Pure: returns strings.

    The kinds are not comparable, so they are not summed. §6's tripwire —
    refusals above 1% mean a real suffix has fallen outside the vocabulary,
    the '-hina' signal — applies to `suffix` ALONE. A rejected pair test is
    the ngata discriminator declining a compound; a refused base is a
    parenthesis in a headword; a whole form is a row we wrote. Adding those
    to the suffix count put four of six sources over the threshold without
    one of them having the fault the threshold names.
    """
    out = [f"  [{source_id}] suffix-forms: {rows_written} rows written"]
    for kind in tally.kinds():
        refused = tally.refused_of(kind)
        rate = tally.refusal_rate(kind)
        line = f"      {kind:<7} {tally.seen_of(kind):>6} {_TALLY_NOUN[kind]}"
        if refused:
            line += (f", {len(refused)} "
                     f"{'rejected' if kind == 'pair' else 'refused'}")
            if rate is not None:
                line += f" ({rate:.2%})"
                if kind == "suffix" and rate > 0.01:
                    line += "  <-- OVER 1%: the vocabulary, not the source"
        out.append(line)
        if refused:
            out.append(f"              {refused}")
    return out


def unify_source(con, source_id) -> dict:
    row = con.execute(
        "SELECT default_dialect FROM source_metadata WHERE source_id=?",
        (source_id,)).fetchone()
    dialect = row[0] if row else None
    first_seen_map = first_seen_snapshot(con, source_id)
    deleted = delete_source_slice(con, source_id)
    b = Builder(con, source_id, dialect, first_seen_map)
    BUILDERS[source_id](con, b)
    if source_id == "te_aka":
        resolve_te_aka_synonyms(con)
    if source_id == "williams":
        n, tot = resolve_williams_xrefs(con)
        print(f"  williams see_also resolved {n}/{tot}")
        n, tot = resolve_williams_parents(con)
        print(f"  williams derived_from: {n} recorded of {tot} sub-entries")
    # keep source_metadata.last_updated honest for the unified projection
    con.execute("UPDATE source_metadata SET last_updated=? WHERE source_id=?",
                (NOW, source_id))
    b.counts["_deleted"] = deleted
    b.counts["_dialect"] = dialect
    # Spec §6's refusal report. Silent only for sources with no suffix
    # notation at all (taikupu, temarareo, ...) — nothing to tally there.
    #
    # One line per kind, because they are not comparable. §6's tripwire —
    # refusals above 1% mean a real suffix has fallen outside the
    # vocabulary, the '-hina' signal — applies to the `suffix` kind ALONE. A
    # rejected pair test is the ngata discriminator declining a compound, a
    # refused base is a parenthesis in a headword, and a whole form is a row
    # we wrote. Counting those four together put four of six sources over
    # the threshold without one of them having the fault it names.
    if b.suffix_tally.seen or b.derived_forms_written:
        for line in format_suffix_report(source_id, b.derived_forms_written,
                                         b.suffix_tally):
            print(line)
    return b.counts


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Build the unified canonical core from per-source tables.")
    ap.add_argument("--source", action="append", choices=SOURCES + ("all",),
                    help="source to (re)unify; repeatable. Default: all.")
    args = ap.parse_args()

    targets = SOURCES if (not args.source or "all" in args.source) else tuple(
        dict.fromkeys(args.source))   # dedupe, preserve order

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    if not core_tables_exist(con):
        sys.exit("Core tables missing. Run:  py scripts/00_init_db.py  first.")

    cleared = clear_entry_link_tables(con)
    if cleared:
        print(f"cleared {cleared} stale entry-link rows "
              f"({'/'.join(ENTRY_LINK_TABLES)}) — re-run 08b + 52 after this")

    grand = {t: 0 for t in CORE_TABLES}
    for src in targets:
        counts = unify_source(con, src)
        con.commit()
        for t in CORE_TABLES:
            grand[t] += counts[t]
        dia = f" dialect={counts['_dialect']}" if counts["_dialect"] else ""
        print(f"[{src}] cleared {counts['_deleted']} -> "
              f"entry {counts['entry']}, sense {counts['sense']}, "
              f"example {counts['example']}, form {counts['form']}, "
              f"relation {counts['relation']}, domain {counts['entry_domain']}{dia}")

    if len(targets) > 1:
        print(f"\nTOTAL  entry {grand['entry']}, sense {grand['sense']}, "
              f"example {grand['example']}, form {grand['form']}, "
              f"relation {grand['relation']}, domain {grand['entry_domain']}")

    # scrub values reviewers flagged as NOT a part of speech (std_pos.status='not_pos'):
    # null them off senses so they never surface as POS (raw or canonical). Durable —
    # re-read from std_pos on every build.
    notpos = [r[0] for r in con.execute("SELECT raw_pos FROM std_pos WHERE status='not_pos'")]
    if notpos:
        ph = ",".join("?" * len(notpos))
        n = con.execute(
            f"UPDATE sense SET part_of_speech=NULL WHERE part_of_speech IN ({ph})", notpos
        ).rowcount
        con.commit()
        print(f"scrubbed {n} sense rows with not_pos values ({len(notpos)} codes)")

    std_pos = load_std_pos(con)
    write_sense_pos(con, std_pos)
    write_entry_pos(con, std_pos)

    # relation rows are rebuilt per source, so the sense pointers have to be
    # re-derived on every run, not backfilled once.
    # The projection has just overwritten this source's slice with the source's
    # own values, so the sweep's corrections are replayed on top.
    patched = apply_patches(con)
    if any(patched.values()):
        print(f"patches: {patched['applied']:,} applied, {patched['stale']:,} stale, "
              f"{patched['missing']:,} missing")

    # Resolve relation targets BEFORE senses, so a target resolved here can have
    # its sense picked up in the same run.
    linked = resolve_within_source_relations(con)
    if linked:
        print(f"resolved {linked:,} within-source relation target_entry_id")

    # Then the ones the headword alone could not settle: paekupu and He Pataka
    # Kupu tell same-named entries apart by subject domain.
    by_domain = resolve_relations_by_domain(con)
    if by_domain:
        print(f"resolved {by_domain:,} more relation target_entry_id by subject domain")

    # Last, on what those left: He Pataka Kupu reuses one definition across a
    # whole synonym set, so a repeated definition names the sense meant.
    by_gloss = resolve_relations_by_gloss(con)
    if by_gloss:
        print(f"resolved {by_gloss:,} more relation target_entry_id by shared definition")

    resolved = resolve_unambiguous_senses(con)
    if resolved.get("relation"):
        print(f"resolved {resolved['relation']:,} relation target_sense_id "
              f"(single-sense targets)")
    con.close()


if __name__ == "__main__":
    main()
