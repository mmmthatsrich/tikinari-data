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
                   compute_content_hash, pos_atoms, resolve_unambiguous_senses)
from williams_senses import split_senses
from williams_examples import split_gloss_examples
from williams_headword import parse_headword_note
from williams_xref import parse_see_also_targets
from papakupu_gloss import clean_gloss
from temarareo_gloss import build_raw, clean_definition, dedupe_species
from wakareo_records import example_owners, parse_derivation, parse_tregear
from sweep_patch import apply_patches

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


class Builder:
    """Inserts into the unified core, using autoincrement rowids for FK wiring."""

    def __init__(self, con, source_id, dialect, first_seen_map):
        self.con = con
        self.source_id = source_id
        self.dialect = dialect
        self.first_seen_map = first_seen_map      # {source_entry_id: first_seen}
        self.counts = {t: 0 for t in CORE_TABLES}
        self._lemmas = {}                         # {entry_id: {headword, sort}} for add_form

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
        self.con.execute(
            "INSERT INTO example (sense_id, entry_id, text_mi, text_en, source_abbrev, "
            "citation, sort_no) VALUES (?,?,?,?,?,?,?)",
            (sense_id, entry_id, text_mi, text_en, source_abbrev, citation, sort_no))
        self.counts["example"] += 1

    def add_form(self, entry_id, form, form_type, note=None):
        if not form:
            return
        # A form that merely restates the headword or its macron-stripped sort
        # key is not a variant: headword_search already normalises both, so the
        # row adds nothing and inflates the app's "has variants" signal.
        if form.casefold() in self._lemmas.get(entry_id, ()):
            return
        self.con.execute(
            "INSERT INTO form (entry_id, form, form_search, form_type, note) "
            "VALUES (?,?,?,?,?)",
            (entry_id, form, normalise_search_key(form), form_type, note))
        self.counts["form"] += 1

    def add_relation(self, entry_id, rel_type, target_headword, target_entry_id=None,
                     note=None):
        if not target_headword:
            return
        self.con.execute(
            "INSERT INTO relation (entry_id, rel_type, target_headword, target_entry_id, "
            "note) VALUES (?,?,?,?,?)",
            (entry_id, rel_type, target_headword, target_entry_id, note))
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
           "source_section, headword_note FROM williams_entries ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, sn, xr, pg, sec, hnote) in con.execute(sql):
        # '(pl. wāhine)', '(poetical)', '(less correctly tūāhu)' printed with the
        # headword. Eight are plural forms — a lexical fact the form table exists
        # for — and the rest qualify the entry rather than define it.
        note = parse_headword_note(hnote)
        examples = [e.strip() for e in jload(ux) if isinstance(e, str)]
        eid = b.add_entry(id_, hw, hs, hse, pos=pos,
                          locator=f"p{pg}/{sec}" if pg else sec,
                          material={"hw": hw, "pos": pos, "def": d,
                                    "ex": examples, "xr": jload(xr)})
        senses = split_senses(d) or [{"sense_number": 1, "part_of_speech": None,
                                      "gloss_en": d, "definition_raw": d}]
        first_sid = None
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
            if first_sid is None:
                first_sid = sid
        # The parser's own <span lang="mi"> examples (61 entries) have no sense
        # of their own to sit on.
        for i, ex in enumerate(examples):
            b.add_example(first_sid, eid, ex, None, None, None, i)
        for pl in note["plural"]:
            b.add_form(eid, pl, "plural")
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

        # Explode the structured senses into per-sense rows, each with its own POS
        # and examples. Drop exact-duplicate senses (some source entries repeat the
        # same def-div N times, e.g. "Rua o Takurua, Te"), then renumber 1..n.
        # Fall back to the packed definition for data parsed before senses existed.
        if not senses:
            senses = [{"sense_number": 1, "part_of_speech": pos,
                       "gloss_en": d, "definition_raw": d, "examples": examples}]

        first_sid = None
        seen_senses = set()
        out_no = 0
        for s in senses:
            key = _ws(s.get("definition_raw") or s.get("gloss_en") or "").lower()
            if key and key in seen_senses:
                continue
            seen_senses.add(key)
            out_no += 1
            sid = b.add_sense(eid, out_no, s.get("gloss_en"), None,
                              s.get("definition_raw"),
                              part_of_speech=s.get("part_of_speech"))
            if first_sid is None:
                first_sid = sid
            for i, ex in enumerate(s.get("examples") or []):
                parsed = te_aka_example(ex)
                if parsed:
                    text, en, cite = parsed
                    b.add_example(sid, eid, text, en, None, cite, i)

        for sy in jload(syn):
            if isinstance(sy, dict):
                # word_id is a SOURCE id, not a unified entry.id — stash it in note and
                # resolve to target_entry_id after all te_aka entries exist (see below).
                wid_note = f"te_aka_word_id={sy.get('word_id')}" if sy.get("word_id") else None
                b.add_relation(eid, "synonym", sy.get("text"), None, note=wid_note)
            elif isinstance(sy, str):
                b.add_relation(eid, "synonym", sy)
        for fdom in filter_domains:
            b.add_domain(eid, first_sid, fdom, "en")


def build_hepatakakupu(con, b):
    sql = ("SELECT id, word_id, headword, headword_sort, headword_search, "
           "part_of_speech, definition, usage_examples, sense_number, synonyms, "
           "semantic_domain FROM hepatakakupu_entries ORDER BY word_id, sense_number, id")
    for (id_, wid, hw, hs, hse, pos, d, ux, sn, syn, dom) in con.execute(sql):
        # He Pātaka Kupu word_id is NOT unique per row (same word_id repeats across
        # senses, and some word_ids are shared sentinels), so it cannot be the device-id
        # stem. Use the source row PK — guaranteed unique and stable. word_id is kept in
        # locator for provenance / sense grouping.
        seid = str(id_)
        examples = [e for e in jload(ux) if isinstance(e, str)]
        eid = b.add_entry(seid, hw, hs, hse, pos=pos, locator=f"word_id={wid}",
                          material={"hw": hw, "pos": pos, "def_mi": d, "sn": sn,
                                    "ex": examples, "syn": jload(syn), "dom": dom})
        sid = b.add_sense(eid, sn, None, d, d, part_of_speech=pos)  # monolingual Māori -> gloss_mi
        for i, ex in enumerate(examples):
            text, src = split_src(ex)
            b.add_example(sid, eid, text, None, src, None, i)
        for sy in jload(syn):
            b.add_relation(eid, "synonym",
                           sy.get("text") if isinstance(sy, dict) else sy)
        if dom:
            b.add_domain(eid, sid, dom, "mi")


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
        for i, ex in enumerate(examples):
            b.add_example(sid, eid, ex, None, None, None, i)   # Paekupu example = Māori only
        for w in jload(alt):
            b.add_form(eid, w if isinstance(w, str) else str(w), "alt_spelling")
        # The curriculum learning areas are bilingual in the source:
        # subject_area 'Pūtaiao' / subject_area_en 'Science'. The builder used
        # `subject_areas` instead — a JSON list of URL slugs ('ngā-toi') — and
        # tagged all 16,486 of them 'en' though every value was Māori.
        # domain_lang is the only thing telling the app how to render these.
        if subj_mi:
            b.add_domain(eid, sid, subj_mi, "mi")
        if subj_en:
            b.add_domain(eid, sid, subj_en, "en")


def build_papakupu(con, b):
    sql = ("SELECT id, headword, headword_sort, headword_search, part_of_speech, "
           "definition, usage_examples, variant_forms, see_also, source_code, "
           "loan_marker, pdf_page FROM papakupu_entries ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, vf, sa, sc, lm, pg) in con.execute(sql):
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
        sid = b.add_sense(eid, None, gloss, None, d, part_of_speech=pos)
        for i, ex in enumerate(examples):
            b.add_example(sid, eid, ex.get("text_mi"), ex.get("text_en"),
                          ex.get("source_abbrev"), None, i)
        for v in jload(vf):
            b.add_form(eid, v if isinstance(v, str) else str(v), "variant")
        for t in jload(sa):
            b.add_relation(eid, "see_also", t if isinstance(t, str) else str(t))


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
    # body_text, not body_raw: the archive keeps the source HTML, the app surface
    # must not. NULL there means the body held nothing but the lemma.
    sql = (f"SELECT source_entry_id, wakareo_id, headword, part_of_speech, search_scope, "
           f"equivalents, qualifier, example_en, example_mi, body_text "
           f"FROM {table} ORDER BY id")
    for (seid, wid, lemma_en, pos, scope, equivs, qual, ex_en, ex_mi, raw) in con.execute(sql):
        equivalents = [e for e in jload(equivs) if e]
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
            siblings.append((eid, mi))
        for eid, _ in siblings:
            for other_eid, other_mi in siblings:
                if other_eid != eid:
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
    (search_key, roman_sense) tuples; each is matched against a Williams entry by
    headword_search, preferring the homograph with the same roman sense, else any
    entry with that headword (same-source — only williams entries are indexed here).

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

    def match(key, sense):
        cands = by_key.get(key)
        if not cands:
            return None
        if sense:
            for eid, rs, disp in cands:
                if rs and rs.lower() == sense:
                    return eid, disp
        eid, _rs, disp = cands[0]   # fall back to any entry with that headword
        return eid, disp

    rows = con.execute(
        "SELECT r.id, r.entry_id, r.target_headword FROM relation r "
        "JOIN entry e ON e.id = r.entry_id "
        "WHERE r.rel_type = 'see_also' AND e.source_id = 'williams' "
        "  AND r.target_entry_id IS NULL").fetchall()

    resolved = 0
    for rid, entry_id, raw in rows:
        hits = [m for m in (match(k, s) for k, s in parse_see_also_targets(raw)) if m]
        if not hits:
            continue
        first_eid, first_disp = hits[0]
        note = raw if (len(hits) > 1 or first_disp != raw) else None
        con.execute("UPDATE relation SET target_entry_id=?, target_headword=?, note=? "
                    "WHERE id=?", (first_eid, first_disp, note, rid))
        for eid, disp in hits[1:]:
            con.execute("INSERT INTO relation (entry_id, rel_type, target_headword, "
                        "target_entry_id, note) VALUES (?,?,?,?,?)",
                        (entry_id, "see_also", disp, eid, raw))
        resolved += 1
    return resolved, len(rows)


def first_seen_snapshot(con, source_id) -> dict:
    """Preserve first_seen across a rebuild, keyed by source_entry_id."""
    return {r[0]: r[1] for r in con.execute(
        "SELECT source_entry_id, first_seen FROM entry WHERE source_id=?", (source_id,))}


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
    # keep source_metadata.last_updated honest for the unified projection
    con.execute("UPDATE source_metadata SET last_updated=? WHERE source_id=?",
                (NOW, source_id))
    b.counts["_deleted"] = deleted
    b.counts["_dialect"] = dialect
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

    resolved = resolve_unambiguous_senses(con)
    if resolved.get("relation"):
        print(f"resolved {resolved['relation']:,} relation target_sense_id "
              f"(single-sense targets)")
    con.close()


if __name__ == "__main__":
    main()
