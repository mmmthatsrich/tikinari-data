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
from utils import DB_PATH, normalise_search_key, compute_content_hash
from williams_senses import split_senses
from williams_xref import parse_see_also_targets
from papakupu_gloss import clean_gloss

NOW = datetime.now(timezone.utc).isoformat()

SOURCES = ("williams", "te_aka", "hepatakakupu", "paekupu", "papakupu", "taikupu")
CORE_TABLES = ("entry", "form", "sense", "example", "relation", "entry_domain")

# trailing citation / source markers in example strings (same patterns as the prototype)
CITE_PAREN = re.compile(r"\s*\(([^()]*\d[^()]*)\)\s*$")        # Te Aka: (Te Toa Takitini 1/3/1930:1992)
SRC_BRACKET = re.compile(r"\s*\[([A-Z0-9][A-Z0-9/]*)\]\s*$")   # [TTU] [NGH3] [041126]


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
    """Strip a trailing (citation); return (text, citation|None)."""
    m = CITE_PAREN.search(s)
    return (s[:m.start()].strip(), m.group(1)) if m else (s.strip(), None)


class Builder:
    """Inserts into the unified core, using autoincrement rowids for FK wiring."""

    def __init__(self, con, source_id, dialect, first_seen_map):
        self.con = con
        self.source_id = source_id
        self.dialect = dialect
        self.first_seen_map = first_seen_map      # {source_entry_id: first_seen}
        self.counts = {t: 0 for t in CORE_TABLES}

    def add_entry(self, source_entry_id, headword, headword_sort, headword_search,
                  pos=None, headword_en=None, loan_marker=None, audio_url=None,
                  locator=None, homonym_no=None, material=None):
        seid = str(source_entry_id)
        first_seen = self.first_seen_map.get(seid) or NOW
        content_hash = compute_content_hash(material) if material else None
        cur = self.con.execute(
            "INSERT INTO entry (source_id, source_entry_id, headword, headword_sort, "
            "headword_search, homonym_no, headword_en, part_of_speech, loan_marker, "
            "dialect, audio_url, locator, content_hash, first_seen, created_at, last_updated) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.source_id, seid, headword, headword_sort, headword_search, homonym_no,
             headword_en, pos, loan_marker, self.dialect, audio_url, locator,
             content_hash, first_seen, NOW, NOW))
        self.counts["entry"] += 1
        return cur.lastrowid

    def add_sense(self, entry_id, sense_number, gloss_en, gloss_mi, definition_raw,
                  register=None, parent_sense_id=None, part_of_speech=None):
        cur = self.con.execute(
            "INSERT INTO sense (entry_id, sense_number, parent_sense_id, gloss_en, "
            "gloss_mi, definition_raw, register, part_of_speech) VALUES (?,?,?,?,?,?,?,?)",
            (entry_id, sense_number, parent_sense_id, gloss_en, gloss_mi,
             definition_raw, register, part_of_speech))
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
    for tok in (t.strip() for t in raw.split(",")):
        if not tok:
            continue
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
           "source_section FROM williams_entries ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, sn, xr, pg, sec) in con.execute(sql):
        examples = [e.strip() for e in jload(ux) if isinstance(e, str)]
        eid = b.add_entry(id_, hw, hs, hse, pos=pos,
                          locator=f"p{pg}/{sec}" if pg else sec,
                          material={"hw": hw, "pos": pos, "def": d,
                                    "ex": examples, "xr": jload(xr)})
        senses = split_senses(d) or [{"sense_number": 1, "part_of_speech": None,
                                      "gloss_en": d, "definition_raw": d}]
        first_sid = None
        for s in senses:
            sid = b.add_sense(eid, s["sense_number"], s["gloss_en"], None,
                              s["definition_raw"], part_of_speech=s["part_of_speech"])
            if first_sid is None:
                first_sid = sid
        for i, ex in enumerate(examples):
            b.add_example(first_sid, eid, ex, None, None, None, i)   # examples -> sense 1
        for t in jload(xr):
            if isinstance(t, dict):                       # typed ‖ cross-ref
                b.add_relation(eid, t.get("type") or "cross_ref", t.get("target"))
            elif isinstance(t, str):                      # legacy bare string
                b.add_relation(eid, "cross_ref", t)


def build_te_aka(con, b):
    sql = ("SELECT word_id, headword, headword_sort, headword_search, part_of_speech, "
           "definition, senses, usage_examples, audio_url, synonyms, filters "
           "FROM te_aka_entries ORDER BY word_id")
    for (wid, hw, hs, hse, pos, d, sj, ux, au, syn, filt) in con.execute(sql):
        examples = [e for e in jload(ux) if isinstance(e, str)]
        senses = [s for s in jload(sj) if isinstance(s, dict)]
        eid = b.add_entry(wid, hw, hs, hse, pos=pos, audio_url=au,
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
            for i, ex in enumerate(e for e in (s.get("examples") or []) if isinstance(e, str)):
                text, cite = split_cite(ex)            # Te Aka example = Māori + (citation)
                b.add_example(sid, eid, text, None, None, cite, i)

        for sy in jload(syn):
            if isinstance(sy, dict):
                # word_id is a SOURCE id, not a unified entry.id — stash it in note and
                # resolve to target_entry_id after all te_aka entries exist (see below).
                wid_note = f"te_aka_word_id={sy.get('word_id')}" if sy.get("word_id") else None
                b.add_relation(eid, "synonym", sy.get("text"), None, note=wid_note)
            elif isinstance(sy, str):
                b.add_relation(eid, "synonym", sy)
        for fdom in jload(filt):
            b.add_domain(eid, first_sid, fdom if isinstance(fdom, str) else str(fdom), "en")


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
           "alternative_words, subject_areas FROM paekupu_entries ORDER BY id")
    for (slug, hw, hs, hse, hen, pos, d, dmi, ux, au, alt, subj) in con.execute(sql):
        examples = [e.strip() for e in jload(ux) if isinstance(e, str)]
        raw = (d or "") + (" || MI: " + dmi if dmi else "")
        eid = b.add_entry(slug, hw, hs, hse, pos=pos, headword_en=hen, audio_url=au,
                          locator=f"slug={slug}",
                          material={"hw": hw, "hen": hen, "pos": pos, "def": d,
                                    "def_mi": dmi, "ex": examples, "alt": jload(alt),
                                    "subj": jload(subj)})
        sid = b.add_sense(eid, None, d, dmi, raw, part_of_speech=pos)
        for i, ex in enumerate(examples):
            b.add_example(sid, eid, ex, None, None, None, i)   # Paekupu example = Māori only
        for w in jload(alt):
            b.add_form(eid, w if isinstance(w, str) else str(w), "alt_spelling")
        for s in jload(subj):
            b.add_domain(eid, sid, s if isinstance(s, str) else str(s), "en")


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


BUILDERS = {
    "williams": build_williams,
    "te_aka": build_te_aka,
    "hepatakakupu": build_hepatakakupu,
    "paekupu": build_paekupu,
    "papakupu": build_papakupu,
    "taikupu": build_taikupu,
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
    con.close()


if __name__ == "__main__":
    main()
