"""Build a REVIEW SAMPLE of the proposed canonical schema (see SCHEMA_PROPOSAL.md).

Creates std_* tables and populates them with 10 entries from each of the 5 source
dictionaries, transformed onto the unified entry -> form/sense/example/relation/domain
model. Read-only against the source tables; only std_* objects are dropped/created.

A flattened std_review view (one row per example, or per sense if no example) is
provided for easy eyeballing in a DB browser.

Usage:
    py scripts/12_build_standard_sample.py
"""
import json, re, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

NOW = datetime.now(timezone.utc).isoformat()

DDL = """
DROP VIEW  IF EXISTS std_review;
DROP TABLE IF EXISTS std_example;
DROP TABLE IF EXISTS std_form;
DROP TABLE IF EXISTS std_relation;
DROP TABLE IF EXISTS std_entry_domain;
DROP TABLE IF EXISTS std_sense;
DROP TABLE IF EXISTS std_entry;

CREATE TABLE std_entry (
    id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
    headword TEXT, headword_sort TEXT, headword_search TEXT, homonym_no INTEGER,
    headword_en TEXT, part_of_speech TEXT, loan_marker TEXT, audio_url TEXT,
    locator TEXT, created_at TEXT, last_updated TEXT);
CREATE TABLE std_form (
    id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT, form_search TEXT,
    form_type TEXT, note TEXT);
CREATE TABLE std_sense (
    id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
    parent_sense_id INTEGER, gloss_en TEXT, gloss_mi TEXT, definition_raw TEXT,
    register TEXT);
CREATE TABLE std_example (
    id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
    text_mi TEXT, text_en TEXT, source_abbrev TEXT, citation TEXT, sort_no INTEGER);
CREATE TABLE std_relation (
    id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
    target_headword TEXT, target_entry_id INTEGER, note TEXT);
CREATE TABLE std_entry_domain (
    id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
    domain TEXT, domain_lang TEXT);

CREATE VIEW std_review AS
SELECT e.source_id, e.headword, e.headword_en, e.part_of_speech AS pos,
       s.sense_number AS sense, s.gloss_en, s.gloss_mi,
       x.text_mi AS ex_mi, x.text_en AS ex_en, x.source_abbrev AS ex_src,
       x.citation AS ex_cite, e.audio_url, e.locator
FROM std_entry e
LEFT JOIN std_sense s   ON s.entry_id = e.id
LEFT JOIN std_example x ON x.sense_id = s.id
ORDER BY e.source_id, e.id, s.sense_number, x.sort_no;
"""

# trailing citation/source markers in example strings
CITE_PAREN = re.compile(r"\s*\(([^()]*\d[^()]*)\)\s*$")   # Te Aka: (Te Toa Takitini 1/3/1930:1992)
SRC_BRACKET = re.compile(r"\s*\[([A-Z0-9][A-Z0-9/]*)\]\s*$")  # [TTU] [NGH3] [041126]


def jload(s):
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


def split_src(s):
    """Strip a trailing [SRC] code; return (text, src|None)."""
    m = SRC_BRACKET.search(s)
    return (s[:m.start()].strip(), m.group(1)) if m else (s.strip(), None)


def split_cite(s):
    """Strip a trailing (citation); return (text, citation|None)."""
    m = CITE_PAREN.search(s)
    return (s[:m.start()].strip(), m.group(1)) if m else (s.strip(), None)


class Builder:
    def __init__(self, con):
        self.con = con
        self.eid = self.sid = self.xid = self.fid = self.rid = self.did = 0

    def add_entry(self, **k):
        self.eid += 1
        cols = ("id,source_id,source_entry_id,headword,headword_sort,headword_search,"
                "homonym_no,headword_en,part_of_speech,loan_marker,audio_url,locator,"
                "created_at,last_updated")
        self.con.execute(
            f"INSERT INTO std_entry ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.eid, k["source_id"], str(k.get("source_entry_id") or ""), k["headword"],
             k["headword_sort"], k["headword_search"], k.get("homonym_no"),
             k.get("headword_en"), k.get("pos"), k.get("loan_marker"),
             k.get("audio_url"), k.get("locator"), NOW, NOW))
        return self.eid

    def add_sense(self, entry_id, n, gloss_en, gloss_mi, raw):
        self.sid += 1
        self.con.execute(
            "INSERT INTO std_sense (id,entry_id,sense_number,parent_sense_id,gloss_en,"
            "gloss_mi,definition_raw,register) VALUES (?,?,?,?,?,?,?,?)",
            (self.sid, entry_id, n, None, gloss_en, gloss_mi, raw, None))
        return self.sid

    def add_example(self, sense_id, entry_id, mi, en, src, cite, sort_no):
        self.xid += 1
        self.con.execute(
            "INSERT INTO std_example (id,sense_id,entry_id,text_mi,text_en,source_abbrev,"
            "citation,sort_no) VALUES (?,?,?,?,?,?,?,?)",
            (self.xid, sense_id, entry_id, mi, en, src, cite, sort_no))

    def add_form(self, entry_id, form, ftype):
        self.fid += 1
        self.con.execute(
            "INSERT INTO std_form (id,entry_id,form,form_search,form_type,note) "
            "VALUES (?,?,?,?,?,?)", (self.fid, entry_id, form, form.lower(), ftype, None))

    def add_rel(self, entry_id, rtype, target, tid=None):
        self.rid += 1
        self.con.execute(
            "INSERT INTO std_relation (id,entry_id,rel_type,target_headword,"
            "target_entry_id,note) VALUES (?,?,?,?,?,?)",
            (self.rid, entry_id, rtype, target, tid, None))

    def add_domain(self, entry_id, sense_id, domain, lang):
        self.did += 1
        self.con.execute(
            "INSERT INTO std_entry_domain (id,sense_id,entry_id,domain,domain_lang) "
            "VALUES (?,?,?,?,?)", (self.did, sense_id, entry_id, domain, lang))


def rows(con, sql, n=10):
    return con.execute(sql).fetchmany(n)


def build_williams(con, b):
    sql = ("SELECT id,headword,headword_sort,headword_search,part_of_speech,definition,"
           "usage_examples,sense_number,cross_refs,page_number,source_section "
           "FROM williams_entries WHERE usage_examples!='[]' ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, sn, xr, pg, sec) in rows(con, sql):
        eid = b.add_entry(source_id="williams", source_entry_id=id_, headword=hw,
                          headword_sort=hs, headword_search=hse, pos=pos,
                          locator=f"p{pg}/{sec}" if pg else sec)
        sid = b.add_sense(eid, sn, d, None, d)
        for i, ex in enumerate(jload(ux)):
            b.add_example(sid, eid, ex.strip(), None, None, None, i)
        for t in jload(xr):
            b.add_rel(eid, "cross_ref", t)


def build_te_aka(con, b):
    sql = ("SELECT id,word_id,headword,headword_sort,headword_search,part_of_speech,"
           "definition,usage_examples,audio_url,synonyms,filters "
           "FROM te_aka_entries WHERE usage_examples!='[]' ORDER BY id")
    for (id_, wid, hw, hs, hse, pos, d, ux, au, syn, filt) in rows(con, sql):
        eid = b.add_entry(source_id="te_aka", source_entry_id=wid, headword=hw,
                          headword_sort=hs, headword_search=hse, pos=pos, audio_url=au,
                          locator=f"word_id={wid}")
        sid = b.add_sense(eid, None, d, None, d)
        for i, ex in enumerate(jload(ux)):
            text, cite = split_cite(ex)
            b.add_example(sid, eid, text, None, None, cite, i)
        for sy in jload(syn):
            if isinstance(sy, dict):
                b.add_rel(eid, "synonym", sy.get("text"), sy.get("word_id"))
        for fdom in jload(filt):
            b.add_domain(eid, sid, fdom if isinstance(fdom, str) else str(fdom), "en")


def build_hepataka(con, b):
    sql = ("SELECT id,word_id,headword,headword_sort,headword_search,part_of_speech,"
           "definition,usage_examples,sense_number,synonyms,semantic_domain "
           "FROM hepatakakupu_entries ORDER BY id")
    for (id_, wid, hw, hs, hse, pos, d, ux, sn, syn, dom) in rows(con, sql):
        eid = b.add_entry(source_id="hepatakakupu", source_entry_id=wid, headword=hw,
                          headword_sort=hs, headword_search=hse, pos=pos,
                          locator=f"word_id={wid}")
        sid = b.add_sense(eid, sn, None, d, d)          # monolingual: gloss_mi
        for i, ex in enumerate(jload(ux)):
            text, src = split_src(ex if isinstance(ex, str) else str(ex))
            b.add_example(sid, eid, text, None, src, None, i)
        for sy in jload(syn):
            b.add_rel(eid, "synonym", sy.get("text") if isinstance(sy, dict) else sy)
        if dom:
            b.add_domain(eid, sid, dom, "mi")


def build_paekupu(con, b):
    sql = ("SELECT id,slug,headword,headword_sort,headword_search,headword_en,"
           "part_of_speech,pos_mi,definition,definition_mi,usage_examples,audio_url,"
           "alternative_words,subject_areas FROM paekupu_entries "
           "WHERE usage_examples!='[]' ORDER BY id")
    for (id_, slug, hw, hs, hse, hen, pos, posmi, d, dmi, ux, au, alt, subj) in rows(con, sql):
        eid = b.add_entry(source_id="paekupu", source_entry_id=slug, headword=hw,
                          headword_sort=hs, headword_search=hse, headword_en=hen,
                          pos=pos, audio_url=au, locator=f"slug={slug}")
        sid = b.add_sense(eid, None, d, dmi, (d or "") + (" || MI: " + dmi if dmi else ""))
        for i, ex in enumerate(jload(ux)):
            b.add_example(sid, eid, ex.strip(), None, None, None, i)
        for w in jload(alt):
            b.add_form(eid, w if isinstance(w, str) else str(w), "alt_spelling")
        for s in jload(subj):
            b.add_domain(eid, sid, s if isinstance(s, str) else str(s), "en")


def build_papakupu(con, b):
    sql = ("SELECT id,headword,headword_sort,headword_search,part_of_speech,definition,"
           "usage_examples,variant_forms,see_also,source_code,loan_marker,pdf_page "
           "FROM papakupu_entries WHERE usage_examples!='[]' ORDER BY id")
    for (id_, hw, hs, hse, pos, d, ux, vf, sa, sc, lm, pg) in rows(con, sql):
        eid = b.add_entry(source_id="papakupu", source_entry_id=id_, headword=hw,
                          headword_sort=hs, headword_search=hse, pos=pos,
                          loan_marker=lm, locator=f"pdf p{pg}; src {sc}" if pg else sc)
        sid = b.add_sense(eid, None, d, None, d)
        for i, ex in enumerate(jload(ux)):
            text, src = split_src(ex)                    # text_en (Māori currently lost)
            b.add_example(sid, eid, None, text, src, None, i)
        for v in jload(vf):
            b.add_form(eid, v, "variant")
        for t in jload(sa):
            b.add_rel(eid, "see_also", t)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    con = sqlite3.connect(DB_PATH)
    con.executescript(DDL)
    b = Builder(con)
    for fn in (build_williams, build_te_aka, build_hepataka, build_paekupu, build_papakupu):
        fn(con, b)
    con.commit()
    print(f"std_entry: {b.eid}  std_sense: {b.sid}  std_example: {b.xid}  "
          f"std_form: {b.fid}  std_relation: {b.rid}  std_entry_domain: {b.did}")
    print("\nstd_review by source:")
    for src, n in con.execute(
            "SELECT source_id, COUNT(DISTINCT headword) FROM std_entry GROUP BY source_id"):
        print(f"  {src}: {n} entries")
    print("\n--- sample rows (one per source) ---")
    for src in ("williams", "te_aka", "hepatakakupu", "paekupu", "papakupu"):
        r = con.execute(
            "SELECT headword,gloss_en,gloss_mi,ex_mi,ex_en,ex_src,ex_cite "
            "FROM std_review WHERE source_id=? AND (ex_mi IS NOT NULL OR ex_en IS NOT NULL) "
            "LIMIT 1", (src,)).fetchone()
        print(f"  [{src}] {r}")
    con.close()


if __name__ == "__main__":
    main()
