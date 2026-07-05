"""
Build POLLEX protoform ancestry into staging_dictionary.db so an app can render a
decomposition tree: Maori reflex -> cognate set -> ancestral reconstruction
levels (CE -> EP -> NP -> PN -> ... -> POc -> PMP/PAn) as far back as the data
allows.

POLLEX stores ancestry only as *N-coded cross-references inside the `notes`
field (e.g. "*1 Cf. PPN *qaa", "*4 POC *watu", "*5 PMP *atu"). There is no
structured parent pointer on the site or its API. This script:

  schema   create reconstruction_levels + protoform_ancestry; add origin col
  fetch    BFS-fetch ancestor protoforms POLLEX has but we lack (no Maori
           reflex), via /api/txt/, so refs resolve and the tree reaches the top
  edges    parse every notes field -> internal ancestry edges (ancestor must
           outrank child per the level ladder)
  ext      map POc/PMP/PAn refs (+ existing etymology_links) -> LPO/ACD edges
  status   counts

Resumable: fetched protoforms are marked origin='ancestor_only'; a fetch_log
table records attempts so re-runs skip done/404 slugs.

Usage:
    py scripts/pollex_ancestry.py schema
    py scripts/pollex_ancestry.py fetch [max]
    py scripts/pollex_ancestry.py edges
    py scripts/pollex_ancestry.py ext
    py scripts/pollex_ancestry.py status
"""
import sqlite3, sys, re, time, urllib.request, urllib.parse, urllib.error, datetime

sys.stdout.reconfigure(encoding="utf-8")
DB = r"C:\Local Git\Dictionaries\data\staging_dictionary.db"
UA = {"User-Agent": "Mozilla/5.0 (maori-dict research; contact rich@kaio.co.nz)"}

# Standard Austronesian -> Polynesian subgrouping ladder (depth_rank: bigger = more recent/shallower).
# parent_code = the immediately higher reconstruction level on the main spine.
LEVELS = [
    # code, name, parent, depth_rank
    ("AN", "Austronesian",                0, 0),
    ("MP", "Malayo-Polynesian",        "AN", 1),
    ("OC", "Oceanic",                  "MP", 2),
    ("EO", "Eastern Oceanic",          "OC", 3),
    ("RO", "Remote Oceanic",           "EO", 4),
    ("CP", "Central Pacific",          "RO", 5),
    ("FJ", "Fijic",                    "CP", 6),
    ("PN", "Polynesian",               "CP", 6),
    ("TO", "Tongic",                   "PN", 7),
    ("NP", "Nuclear Polynesian",       "PN", 7),
    ("SO", "Samoic-Outlier Polynesian","NP", 8),
    ("EC", "Ellicean",                 "NP", 8),
    ("CC", "Common Core Polynesian",   "EC", 9),
    ("EP", "East Polynesian",          "EC", 9),
    ("CE", "Central-Eastern Polynesian","EP", 10),
    ("TA", "Tahitic",                  "CE", 11),
    ("MQ", "Marquesic",                "CE", 11),
    ("CK", "Cook Islands Maori",       "TA", 12),
    # peripheral / mixed codes: best-effort parent, flagged spine=0
    ("NO", "Nuclear Outlier",          "NP", 8),
    ("FU", "Futunic",                  "NP", 8),
    ("XW", "West Polynesia",           "PN", 7),
    ("XE", "Marquesan/Mangarevan/Easter","CE", 11),
    ("TU", "Tuvaluan",                 "EC", 9),
    ("LO", "Loans",                     0, 99),
    ("??", "Unknown",                   0, 99),

    # ── ACD / LPO backbone codes, normalised onto the same depth axis ──────────
    # These are the raw level codes ACD/LPO write straight into ETY_cognateset
    # (never bridged to Māori entries — comparative backbone only). Mapping them
    # here lets all ~30k sets sort by antiquity via ETY_level.depth_rank.
    # Confidence: HIGH on the AN>MP>OC>CP>PN spine (Māori's lineage); MED on
    # sibling Oceanic/Micronesian/Melanesian nodes (era-correct, node coarse).
    # depth_rank NULL = attested modern language / unresolved -> excluded from sort.
    ("PAn",  "Proto-Austronesian",                       0,      0),   # canon; ACD's PAN normalised here
    ("PAn/PMP", "Austronesian / Malayo-Polynesian",   "AN",      1),   # boundary tag
    ("PMP",  "Proto-Malayo-Polynesian",              "AN",       1),
    ("PWMP", "Proto-Western-Malayo-Polynesian",      "PMP",      1),   # sibling branch
    ("PPH",  "Proto-Philippine",                     "PWMP",     1),
    ("PCEMP","Proto-Central-Eastern-Malayo-Polynesian","PMP",    1),
    ("PCMP", "Proto-Central-Malayo-Polynesian",      "PCEMP",    1),   # sibling branch
    ("PEMP", "Proto-Eastern-Malayo-Polynesian",      "PCEMP",    1),   # Māori's pre-Oceanic node
    ("PSHWNG","Proto-South-Halmahera-West-New-Guinea","PEMP",    1),
    ("POc",  "Proto-Oceanic",                        "PEMP",     2),   # canon; ACD's POC normalised here
    ("Early Oceanic", "Early Oceanic",               "PEMP",     2),
    ("PWOc", "Proto-Western-Oceanic",                "POc",      2),
    ("PNGOc","Proto-North-New-Guinea (Oceanic)",     "PWOc",     2),
    ("PNNG", "Proto-North-New-Guinea",               "PWOc",     2),
    ("PMM",  "Proto-Meso-Melanesian",                "PWOc",     2),
    ("PPT",  "Proto-Papuan-Tip",                     "PWOc",     2),
    ("PAdm", "Proto-Admiralty",                      "POc",      2),
    ("PEAd", "Proto-Eastern-Admiralty",              "PAdm",     2),
    ("Proto Bwaidoga", "Proto-Bwaidoga (Papuan Tip)","PPT",      2),
    ("Proto Mengen", "Proto-Mengen (Meso-Melanesian)","PMM",     2),
    ("Proto Kimbe", "Proto-Kimbe (Meso-Melanesian)", "PMM",      2),
    ("Proto Willaumez","Proto-Willaumez (Meso-Melanesian)","PMM",2),
    ("Proto Cenderawasih Bay","Proto-Cenderawasih-Bay","PWOc",   2),
    ("Proto North Bougainville","Proto-North-Bougainville","PWOc",2),
    ("Proto Northwest Solomonic","Proto-Northwest-Solomonic","PMM",2),
    ("PEOc", "Proto-Eastern-Oceanic",                "POc",      3),
    ("PROc", "Proto-Remote-Oceanic",                 "PEOc",     4),
    ("PNCV", "Proto-North-Central-Vanuatu",          "PROc",     4),
    ("PNCal","Proto-New-Caledonian",                 "PROc",     4),
    ("Proto Central Vanuatu","Proto-Central-Vanuatu","PROc",     4),
    ("Proto Torres-Banks","Proto-Torres-Banks",      "PNCV",     4),
    ("Proto Erakor-Tafea","Proto-Erakor-Tafea",      "PROc",     4),
    ("PSV",  "Proto-South-Vanuatu",                  "PROc",     4),
    ("Proto South Melanesian","Proto-South-Melanesian","PROc",   4),
    ("PSES", "Proto-Southeast-Solomonic",            "PROc",     4),   # canon; LPO's PSS normalised here
    ("Proto Malaita-Makira","Proto-Malaita-Makira",  "PSES",     4),
    ("’Are’are","’Are’are (SE Solomonic language)",  "PSES",     4),
    ("PMic", "Proto-Micronesian",                    "PROc",     4),
    ("Proto Central Micronesian","Proto-Central-Micronesian","PMic",4),
    ("PChk", "Proto-Chuukic",                        "PMic",     4),
    ("Proto Chuukic-Ponapeic","Proto-Chuukic-Ponapeic","PMic",   4),
    ("PGMic","Proto-Greater-Micronesian",            "PMic",     4),
    ("PWMic","Proto-Western-Micronesian",            "PMic",     4),
    ("Nauruan","Nauruan (Micronesian language)",     "PMic",     4),
    ("PCP",  "Proto-Central-Pacific",                "PROc",     5),
    ("PSOc", "Proto-Southern-Oceanic",               "PROc",     5),
    ("PFij", "Proto-Fijian",                         "PCP",      6),
    ("PCP/PPn","Central Pacific / Polynesian",       "PCP",      6),   # boundary tag
    ("PPn",  "Proto-Polynesian",                     "PCP",      6),
    ("PNPn", "Proto-Nuclear-Polynesian",             "PPn",      7),
    ("Proto Samoic","Proto-Samoic",                  "NP",       8),
    ("PCEPn","Proto-Central-Eastern-Polynesian",     "EP",      10),
    ("Proto Tahitic","Proto-Tahitic",                "CE",      11),
    # attested modern languages mistagged into `level` — kept but NULL-ranked
    ("Ambai","Ambai (SHWNG language)",               "PSHWNG",  None),
    ("Aria", "Aria (Oceanic language)",              0,         None),
    ("Buru", "Buru (Central MP language)",           "PCMP",    None),
    ("Hawu", "Hawu (Central MP language)",           "PCMP",    None),
    ("Kambera","Kambera (Central MP language)",      "PCMP",    None),
    ("Kéo",  "Kéo (Central MP language)",            "PCMP",    None),
    ("Lamaholot","Lamaholot (Central MP language)",  "PCMP",    None),
    ("Nauete","Nauete (Central MP language)",        "PCMP",    None),
    ("XO",   "Unresolved tag",                       0,         None),
]
RANK = {c: r for c, _, _, r in LEVELS}

# One clean display label per depth_rank (many codes share a rank; this is the
# Māori-lineage spine ancestor for that rung) -> reference table ETY_depth, so
# sort output reads cleanly without an alphabetical MIN(name) pick.
DEPTH_LABELS = [
    # depth_rank, label, spine_code
    (0,  "Austronesian",               "AN"),
    (1,  "Malayo-Polynesian",          "MP"),
    (2,  "Oceanic",                    "OC"),
    (3,  "Eastern Oceanic",            "EO"),
    (4,  "Remote Oceanic",             "RO"),
    (5,  "Central Pacific",            "CP"),
    (6,  "Polynesian",                 "PN"),
    (7,  "Nuclear Polynesian",         "NP"),
    (8,  "Ellicean",                   "EC"),
    (9,  "East Polynesian",            "EP"),
    (10, "Central-Eastern Polynesian", "CE"),
    (11, "Tahitic",                    "TA"),
    (12, "Cook Islands Maori",         "CK"),
    (99, "Loans / Unknown",            None),
]

# POLLEX note prefix -> our level code
PFX = {"PPN": "PN", "PN": "PN", "PNP": "NP", "NP": "NP", "PCE": "CE", "CE": "CE",
       "PEP": "EP", "EP": "EP", "PEC": "EC", "EC": "EC", "PSO": "SO", "SO": "SO",
       "PTA": "TA", "TA": "TA", "PCP": "CP", "CP": "CP", "PFJ": "FJ", "FJ": "FJ",
       "PCC": "CC", "CC": "CC", "PMQ": "MQ", "PCK": "CK", "PROC": "RO", "PNO": "NO",
       "PEO": "EO", "POC": "OC", "PMP": "MP", "PAN": "AN", "PWMP": "MP", "PCEMP": "MP"}
INT = {"PN", "NP", "CE", "EP", "EC", "SO", "TA", "CP", "FJ", "CC", "MQ", "CK", "RO", "NO"}
EXT = {"EO", "OC", "MP", "AN"}

_PFXKEYS = sorted(PFX.keys(), key=len, reverse=True)        # longest first: PPN before PN
REF = re.compile(r'\b(' + '|'.join(_PFXKEYS) + r')\s*\*\s*([^\s",;()*]+)')  # form stops at next * marker


def note_fields(notes):
    """Split POLLEX notes into {field_number: text} on *0..*9 markers."""
    parts = re.split(r'\*(\d)\b', notes or "")
    out = {}
    it = iter(parts[1:])
    for num, txt in zip(it, it):
        out[int(num)] = out.get(int(num), "") + " " + txt
    return out


def ancestor_refs(notes):
    """Yield (level_code, form, relation) ancestry refs from structured note fields.
    *0 with '<<' = this form DESCENDS FROM the ref (real ancestor); '>>' = ref is a
    descendant (skip). *1/*2 = Cf. (weaker). *3-*6 = external proto (POc/PMP/PAn).
    *8 (free-text discussion) is ignored."""
    f = note_fields(notes)
    refs = []
    t0 = f.get(0, "")
    if t0:
        keep, mode = "", "anc"
        for tok in re.split(r'(<<|>>)', t0):
            if tok == "<<": mode = "anc"
            elif tok == ">>": mode = "desc"
            elif mode == "anc": keep += " " + tok
        for pfx, form in REF.findall(keep):
            if pfx in PFX:
                refs.append((PFX[pfx], form, "descends"))
    for fn in (1, 2, 3, 4, 5, 6, 7):
        for pfx, form in REF.findall(f.get(fn, "")):
            if pfx in PFX:
                refs.append((PFX[pfx], form, "descends" if PFX[pfx] in EXT else "cf"))
    return refs


def conn():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def slugify(form):
    return form.lower().strip().rstrip('.,;:')


def fetch_txt(slug):
    u = f"https://pollex.eva.mpg.de/api/txt/pollex/{urllib.parse.quote(slug)}/"
    req = urllib.request.Request(u, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def fetch_html(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read().decode("utf-8", "replace")


def normkey(form):
    """Collapse a protoform/ref to a match key: lowercase, glottal variants folded, strip junk.
    POLLEX writes glottal as q in slugs but as 9 / ? / ' / nothing in notes."""
    s = form.lower().strip()
    s = s.replace("9", "q").replace("?", "q").replace("’", "q").replace("'", "q")
    s = re.sub(r'[^a-z0-9.]', '', s)          # keep letters, digits, dot (homonym marker)
    s = s.replace("q", "")                     # also fold glottal OUT for a second key
    return s


def inventory():
    """Crawl /level/{code}/ for every level POLLEX exposes -> authoritative slug+level list."""
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS pollex_slug_inventory(
        slug TEXT PRIMARY KEY, level TEXT, normkey TEXT)""")
    idx = fetch_html("https://pollex.eva.mpg.de/level/")
    codes = sorted(set(re.findall(r'/level/([A-Z?]{2})/', idx)))
    print("crawling levels:", codes)
    total = 0
    for code in codes:
        seen = set(); p = 1
        while True:
            try:
                h = fetch_html(f"https://pollex.eva.mpg.de/level/{code}/?page={p}")
            except Exception:
                break
            slugs = re.findall(r'/entry/([^/"\'> ]+)/', h)
            new = [s for s in slugs if s not in seen]
            if not new:
                break
            for s in new:
                seen.add(s)
                nk = normkey(re.sub(r'^\.', '', s))
                c.execute("INSERT OR IGNORE INTO pollex_slug_inventory VALUES(?,?,?)", (s, code, nk))
            p += 1
            time.sleep(0.3)
        c.commit()
        total += len(seen)
        print(f"  {code}: {len(seen)} slugs (pages {p-1})")
    print("inventory total slugs:", c.execute("SELECT COUNT(*) FROM pollex_slug_inventory").fetchone()[0])


def schema():
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS reconstruction_levels(
        code TEXT PRIMARY KEY, name TEXT, parent_code TEXT, depth_rank INTEGER)""")
    c.execute("DELETE FROM reconstruction_levels")
    for code, name, parent, rank in LEVELS:
        c.execute("INSERT INTO reconstruction_levels VALUES(?,?,?,?)",
                  (code, name, parent if parent else None, rank))
    # one clean display label per depth_rank -> ETY_depth (via 52_build)
    c.execute("""CREATE TABLE IF NOT EXISTS depth_labels(
        depth_rank INTEGER PRIMARY KEY, label TEXT, spine_code TEXT)""")
    c.execute("DELETE FROM depth_labels")
    for rank, label, spine in DEPTH_LABELS:
        c.execute("INSERT INTO depth_labels VALUES(?,?,?)", (rank, label, spine))
    c.execute("""CREATE TABLE IF NOT EXISTS protoform_ancestry(
        id INTEGER PRIMARY KEY,
        child_id TEXT NOT NULL,
        child_level TEXT,
        ancestor_kind TEXT NOT NULL,          -- 'pollex' | 'lpo' | 'acd'
        ancestor_id TEXT,                     -- cognateset id / lpo id / acd id
        ancestor_level TEXT,
        relation TEXT,                        -- 'cf' (POLLEX cross-ref)
        source TEXT,                          -- 'notes' | 'etymology_links'
        confidence REAL,
        raw_ref TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_anc_child ON protoform_ancestry(child_id)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_anc_anc ON protoform_ancestry(ancestor_kind,ancestor_id)")
    c.execute("""CREATE TABLE IF NOT EXISTS pollex_fetch_log(
        slug TEXT PRIMARY KEY, status TEXT, fetched_at TEXT)""")
    # add origin flag to pollex_cognatesets (additive, default existing rows = maori)
    cols = [r[1] for r in c.execute("PRAGMA table_info(pollex_cognatesets)")]
    if "origin" not in cols:
        c.execute("ALTER TABLE pollex_cognatesets ADD COLUMN origin TEXT DEFAULT 'maori_reflex'")
        c.execute("UPDATE pollex_cognatesets SET origin='maori_reflex' WHERE origin IS NULL")
    c.commit()
    print("schema ok. levels:", c.execute("SELECT COUNT(*) FROM reconstruction_levels").fetchone()[0])


def parse_txt(slug, txt):
    """Return dict(level, protoform, description, notes) or None."""
    lines = txt.splitlines()
    if not lines or not lines[0].startswith("."):
        return None
    m = re.match(r'\.(\S+)\s+(\S+)\s*:?(.*)', lines[0])
    if not m:
        return None
    level, proto, desc = m.group(1), m.group(2), m.group(3).strip()
    notes = " ".join(l for l in lines[1:] if l.startswith("*"))
    return {"slug": slug, "level": level, "protoform": proto,
            "description": desc, "notes": notes}


def load_resolver(c):
    """Build (exact slug set, normkey->slug) from the crawled inventory."""
    inv_slugs = set()
    nk2slug = {}
    for slug, lvl, nk in c.execute("SELECT slug, level, normkey FROM pollex_slug_inventory"):
        inv_slugs.add(slug)
        nk2slug.setdefault(nk, slug)        # first wins; ambiguous keys resolved to one
    return inv_slugs, nk2slug


def resolve(form, inv_slugs, nk2slug):
    """note ref form -> real POLLEX slug, via inventory. None if unresolvable."""
    s = slugify(form)
    if s in inv_slugs:
        return s
    # try with/without trailing homonym .N
    base = re.sub(r'\.\d+[a-z]?$', '', s)
    if base in inv_slugs:
        return base
    return nk2slug.get(normkey(form))


def candidates(c):
    """Internal ancestor slugs referenced in notes that we do NOT yet hold, resolved to real slugs."""
    held = {r[0] for r in c.execute("SELECT id FROM pollex_cognatesets")}
    inv_slugs, nk2slug = load_resolver(c)
    cand = set()
    for (notes,) in c.execute("SELECT notes FROM pollex_cognatesets WHERE notes IS NOT NULL AND length(notes)>0"):
        for lvl, form, rel in ancestor_refs(notes):
            if lvl in INT:
                real = resolve(form, inv_slugs, nk2slug)
                if real and real not in held:
                    cand.add(real)
    return held, cand


def fetch(maxn):
    c = conn()
    inv_slugs, nk2slug = load_resolver(c)
    done = {r[0] for r in c.execute("SELECT slug FROM pollex_fetch_log")}
    held, cand = candidates(c)
    queue = sorted(cand - done)
    now = lambda: datetime.datetime.now().isoformat(timespec="seconds")
    added = ok = miss = 0
    while queue and added < maxn:
        slug = queue.pop(0)
        if slug in done or slug in held:
            continue
        done.add(slug)
        try:
            txt = fetch_txt(slug)
            pf = parse_txt(slug, txt)
            if not pf:
                c.execute("INSERT OR REPLACE INTO pollex_fetch_log VALUES(?,?,?)", (slug, "parsefail", now()))
                miss += 1
            else:
                c.execute("""INSERT OR IGNORE INTO pollex_cognatesets
                    (id, protoform_name, level, level_name, description, reconstruction, notes, pollex_url, origin)
                    VALUES(?,?,?,?,?,?,?,?, 'ancestor_only')""",
                    (slug, f"{pf['level']}.{pf['protoform']}", pf["level"],
                     dict((c2, n) for c2, n, _, _ in LEVELS).get(pf["level"], pf["level"]),
                     pf["description"], f"Reconstructs to {pf['level']}", pf["notes"],
                     f"https://pollex.eva.mpg.de/entry/{slug}/"))
                c.execute("INSERT OR REPLACE INTO pollex_fetch_log VALUES(?,?,?)", (slug, "ok", now()))
                held.add(slug); ok += 1; added += 1
                # transitive: queue this ancestor's own unheld referenced ancestors
                for lvl2, form, rel in ancestor_refs(pf["notes"]):
                    if lvl2 in INT:
                        s2 = resolve(form, inv_slugs, nk2slug)
                        if s2 and s2 not in held and s2 not in done:
                            queue.append(s2)
        except urllib.error.HTTPError as e:
            c.execute("INSERT OR REPLACE INTO pollex_fetch_log VALUES(?,?,?)", (slug, f"http{e.code}", now()))
            miss += 1
        except Exception as e:
            c.execute("INSERT OR REPLACE INTO pollex_fetch_log VALUES(?,?,?)", (slug, "err", now()))
            miss += 1
        if (ok + miss) % 25 == 0:
            c.commit()
        time.sleep(0.4)
    c.commit()
    # ancestor_only rows count toward the table total — keep source_metadata in sync
    c.execute("""UPDATE source_metadata
                 SET entry_count=(SELECT COUNT(*) FROM pollex_cognatesets)
                 WHERE source_id='pollex_cognatesets'""")
    c.commit()
    remaining = len([s for s in (cand - done)])
    print(f"fetch: added={ok} missed/404={miss} queue_remaining~{remaining}")


def edges():
    c = conn()
    c.execute("DELETE FROM protoform_ancestry WHERE source='notes'")
    held = {r[0]: r[1] for r in c.execute("SELECT id, level FROM pollex_cognatesets")}
    inv_slugs, nk2slug = load_resolver(c)
    n = 0
    for cid, lvl, notes in c.execute("SELECT id, level, notes FROM pollex_cognatesets WHERE notes IS NOT NULL AND length(notes)>0"):
        crank = RANK.get(lvl, 50)
        seen = set()
        for code, form, rel in ancestor_refs(notes):
            if code not in INT:
                continue
            s = resolve(form, inv_slugs, nk2slug)
            if not s or s not in held or s == cid:
                continue
            arank = RANK.get(held[s], 50)
            if arank < crank and (s,) not in seen:        # ancestor strictly outranks child
                seen.add((s,))
                conf = 0.95 if rel == "descends" else 0.75
                c.execute("""INSERT INTO protoform_ancestry
                    (child_id,child_level,ancestor_kind,ancestor_id,ancestor_level,relation,source,confidence,raw_ref)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (cid, lvl, "pollex", s, held[s], rel, "notes", conf, f"{code} *{form}"))
                n += 1
    c.commit()
    print(f"edges (internal, notes): {n}")


def ext():
    c = conn()
    c.execute("DELETE FROM protoform_ancestry WHERE source IN ('etymology_links','notes_ext')")
    n = 0
    # 1) reuse existing curated etymology_links -> lpo / acd
    for pid, lpo, acd in c.execute("SELECT pollex_cognateset_id, lpo_cognateset_id, acd_cognateset_id FROM etymology_links"):
        lvl = c.execute("SELECT level FROM pollex_cognatesets WHERE id=?", (pid,)).fetchone()
        lvl = lvl[0] if lvl else None
        if lpo:
            c.execute("""INSERT INTO protoform_ancestry(child_id,child_level,ancestor_kind,ancestor_id,ancestor_level,relation,source,confidence,raw_ref)
                VALUES(?,?,?,?,?,?,?,?,?)""", (pid, lvl, "lpo", lpo, "POc", "descends", "etymology_links", 0.95, None)); n += 1
        if acd:
            c.execute("""INSERT INTO protoform_ancestry(child_id,child_level,ancestor_kind,ancestor_id,ancestor_level,relation,source,confidence,raw_ref)
                VALUES(?,?,?,?,?,?,?,?,?)""", (pid, lvl, "acd", acd, "PAn/PMP", "descends", "etymology_links", 0.95, None)); n += 1
    # 2) parse POc/PMP/PAn note refs -> match LPO/ACD by normalised name
    lpo = {}
    for i, nk in c.execute("SELECT id, name_key FROM lpo_cognatesets WHERE name_key IS NOT NULL"):
        lpo.setdefault(nk.lower(), i)
    acd = {}
    for i, nk in c.execute("SELECT id, name_key FROM acd_cognatesets WHERE name_key IS NOT NULL"):
        acd.setdefault(nk.lower(), i)
    def norm(form):
        return re.sub(r'[^a-z]', '', form.lower())
    m = 0
    for cid, lvl, notes in c.execute("SELECT id, level, notes FROM pollex_cognatesets WHERE notes IS NOT NULL AND length(notes)>0"):
        seen = set()
        for code, form, rel in ancestor_refs(notes):
            if code not in EXT:
                continue
            key = norm(form)
            if not key or key in seen:
                continue
            seen.add(key)
            tgt_tbl, tgt = (None, None)
            if code in ("OC", "EO") and key in lpo:
                tgt_tbl, tgt = "lpo", lpo[key]
            elif code in ("MP", "AN") and key in acd:
                tgt_tbl, tgt = "acd", acd[key]
            if tgt:
                c.execute("""INSERT INTO protoform_ancestry(child_id,child_level,ancestor_kind,ancestor_id,ancestor_level,relation,source,confidence,raw_ref)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (cid, lvl, tgt_tbl, tgt, code, rel, "notes_ext", 0.7, f"{code} *{form}")); m += 1
    c.commit()
    print(f"edges (external): etymology_links={n}  notes->LPO/ACD={m}")


def status():
    c = conn()
    g = lambda q: c.execute(q).fetchone()[0]
    print("cognatesets total:", g("SELECT COUNT(*) FROM pollex_cognatesets"),
          "| ancestor_only:", g("SELECT COUNT(*) FROM pollex_cognatesets WHERE origin='ancestor_only'"))
    print("ancestry edges:", g("SELECT COUNT(*) FROM protoform_ancestry"),
          "| internal:", g("SELECT COUNT(*) FROM protoform_ancestry WHERE ancestor_kind='pollex'"),
          "| lpo:", g("SELECT COUNT(*) FROM protoform_ancestry WHERE ancestor_kind='lpo'"),
          "| acd:", g("SELECT COUNT(*) FROM protoform_ancestry WHERE ancestor_kind='acd'"))
    print("cognatesets with >=1 ancestor:",
          g("SELECT COUNT(DISTINCT child_id) FROM protoform_ancestry"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "schema": schema()
    elif cmd == "inventory": inventory()
    elif cmd == "fetch": fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif cmd == "edges": edges()
    elif cmd == "ext": ext()
    elif cmd == "status": status()
    else: print("unknown cmd")
