"""Build the part-of-speech normalisation table (std_pos) — ATOMIC codes only.

Collects every distinct part_of_speech value across the source dictionaries, **splits
comma-combined values into atomic codes** (e.g. He Pātaka Kupu 'mahp, ing, āhua' →
'mahp' + 'ing' + 'āhua'), records which sources use each atomic code and how often, and
provides canonical_en / canonical_mi columns. Compound combos are never stored — the
unify build (`50_build_unified.py` `resolve_pos`) composes them from the atomic rows.

PRESERVES existing review work: before rebuilding, current canonical_en / canonical_mi /
status / notes are read and carried forward for any raw_pos that already had them, so
direct edits in std_pos and prior seeds (incl. `14_seed_williams_pos.py`) survive a
re-run. Only genuinely new or still-unmapped codes fall back to the SEED dict below or
to status='needs_review'.

Confident mappings are pre-seeded (English from standard grammar, Māori from Paekupu's
authoritative pos_mi vocabulary). Everything else is left needs_review for an expert.

Read-only against source tables; only std_pos is dropped/created.

Usage:
    py scripts/13_build_pos_normalisation.py
"""
import csv, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

NOW = datetime.now(timezone.utc).isoformat()
SEED_CSV = Path(__file__).parent.parent / "seeds" / "std_pos_seed.csv"
SOURCES = {
    "williams": "williams_entries", "te_aka": "te_aka_entries",
    "hepatakakupu": "hepatakakupu_entries", "paekupu": "paekupu_entries",
    "papakupu": "papakupu_entries", "pollex": "pollex_entries",
}

# atomic raw value (lower-cased) -> (canonical_en, canonical_mi|None)
# Māori terms taken from Paekupu pos_mi (authoritative) where confident; else None.
SEED = {
    "noun": ("Noun", "Tūingoa"),
    "simple noun": ("Noun", "Tūingoa"),
    "personal noun": ("Noun (personal)", "Tūingoa"),
    "n.": ("Noun", "Tūingoa"),
    "proper noun - person": ("Proper noun (person)", "Tūingoa"),
    "proper noun - place": ("Proper noun (place)", "Tūingoa"),
    "proper noun - other": ("Proper noun", "Tūingoa"),
    "name": ("Proper noun", "Tūingoa"),
    "personal name": ("Proper noun (person)", "Tūingoa"),
    "verb": ("Verb", "Tūmahi"),
    "v.": ("Verb", "Tūmahi"),
    "transitive verb": ("Verb (transitive)", "Tūmahi whiti"),
    "transitive universal verb": ("Verb (transitive)", "Tūmahi whiti"),
    "v.t.": ("Verb (transitive)", "Tūmahi whiti"),
    "intransitive verb": ("Verb (intransitive)", "Tūmahi poro"),
    "intransitive universal verb": ("Verb (intransitive)", "Tūmahi poro"),
    "v.i.": ("Verb (intransitive)", "Tūmahi poro"),
    "stative": ("Stative", "Tūāhua"),
    "location": ("Locative", "Tūwāhi"),
    "locative": ("Locative", "Tūwāhi"),
    "adjective": ("Modifier", "Tūāhua"),
    "a.": ("Modifier", "Tūāhua"),
    "modifier": ("Modifier", "Tūāhua"),
    "particle": ("Particle", None),
    "interjection": ("Interjection", None),
    "int.": ("Interjection", None),
    "pronoun": ("Pronoun", None),
    "pron.": ("Pronoun", None),
    "numeral": ("Numeral", None),
    "adverb": ("Adverb", None),
    "ad.": ("Adverb", "Tūkē"),
    "conjunction": ("Conjunction", None),
    "conj.": ("Conjunction", None),
    "determiner": ("Determiner", None),
    "negative": ("Negative", None),
    "causative": ("Verb (causative)", None),
    "universal": ("Universal", None),
    # He Pātaka Kupu atomic codes — official key (Tohu poto / Ingoa roa,
    # hepatakakupu.co.nz/comprehension). Māori authoritative; English best-effort
    # (NULL where uncertain, e.g. thu/tkp particle classes).
    "ing": ("Noun", "Tūingoa"),
    "mahw": ("Verb (transitive)", "Tūmahi whiti"),
    "mahp": ("Verb (intransitive)", "Tūmahi poro"),
    "maho": ("Verb (neuter)", "Tūmahi oti"),
    "mahh": ("Verb (passive)", "Tūmahi hāngū"),
    "āhua": ("Stative", "Tūāhua"),
    "hono": ("Conjunction", "Tūhono"),
    "tūkē": ("Adverb", "Tūkē"),
    "kore": ("Negative", "Tūwhakakāhore"),
    "pāt": ("Interrogative", "Tūpātai"),
    "wāhi": ("Locative", "Tūwāhi"),
    "wā": ("Locative (time)", "Tūwā"),
    "tau": ("Numeral", "Tūtau"),
    "kīa": ("Saying", "Kīanga"),
    "kīw": ("Idiom", "Kīwaha"),
    "pīa": ("Particle", "Pīmua"),
    "pīi": ("Particle", "Pīmuri"),
    "pma": ("Particle", "Pūmahi"),
    "pmi": ("Particle", "Pūmuri"),
    "pmu": ("Particle", "Pūmau"),
    "ptm": ("Particle", "Pūtūmua"),
    "thu": (None, "Tūhau"),
    "tkp": (None, "Tūkapi"),
    # Williams inline abbreviations (POS lives in the definition, surfaced into
    # sense.part_of_speech by williams_senses.split_senses).
    "l.n.": ("Locative", "Tūwāhi"),
    "pt.": ("Particle", None),
    "pos.": ("Determiner (possessive)", None),
    "def.": ("Determiner (definite)", None),
    "indef.": ("Determiner (indefinite)", None),
    "prefix.": ("Prefix", None),
    "num.": ("Numeral", None),
}

DDL = """
DROP TABLE IF EXISTS std_pos;
CREATE TABLE std_pos (
    id            INTEGER PRIMARY KEY,
    raw_pos       TEXT NOT NULL,        -- atomic POS code as stored in a source
    source_counts TEXT,                 -- JSON {source_id: count}
    total_count   INTEGER,
    is_loan       INTEGER DEFAULT 0,    -- atomic code is a 'loan' marker
    canonical_en  TEXT,                 -- normalised English POS (controlled vocab)
    canonical_mi  TEXT,                 -- Māori translation
    status        TEXT,                 -- seeded | reviewed | needs_review | not_pos
    notes         TEXT,
    created_at    TEXT
);
"""


def load_seed(con, path=SEED_CSV):
    """Apply committed expert POS decisions (seeds/std_pos_seed.csv) — FILL-ONLY.

    Never overwrites a row already 'reviewed'/'not_pos' in the live DB (live edits win);
    only fills/seeds other rows, and inserts a row if the code is absent. This is the
    from-empty safety net: on a fresh rebuild the seed restores reviewer decisions.
    """
    if not path.exists():
        return 0
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw = (row.get("raw_pos") or "").strip()
            if not raw:
                continue
            cur = con.execute("SELECT status FROM std_pos WHERE raw_pos=?", (raw,)).fetchone()
            if cur and cur[0] in ("reviewed", "not_pos"):
                continue  # live decision wins
            en = (row.get("canonical_en") or "").strip() or None
            mi = (row.get("canonical_mi") or "").strip() or None
            st = (row.get("status") or "").strip() or "reviewed"
            notes = (row.get("notes") or "").strip() or None
            if cur:
                con.execute(
                    "UPDATE std_pos SET canonical_en=?, canonical_mi=?, status=?, notes=? "
                    "WHERE raw_pos=?", (en, mi, st, notes, raw))
            else:
                con.execute(
                    "INSERT INTO std_pos (raw_pos,source_counts,total_count,is_loan,"
                    "canonical_en,canonical_mi,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (raw, "{}", 0, 1 if "loan" in raw.lower() else 0, en, mi, st, notes, NOW))
            n += 1
    con.commit()
    return n


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    con = sqlite3.connect(DB_PATH)

    # 1. preserve any existing review work before the table is dropped
    preserved = {}
    try:
        for raw, en, mi, st, notes in con.execute(
            "SELECT raw_pos, canonical_en, canonical_mi, status, notes FROM std_pos"
        ):
            preserved[raw] = (en, mi, st, notes)
    except sqlite3.OperationalError:
        pass  # first build: no table yet

    # 2. atomic inventory: split comma-combined POS into atomic codes.
    # Source from the unified core's sense.part_of_speech — it carries EVERY source's
    # per-sense POS, including Williams inline abbreviations (n./v.t./l.n./…) that live
    # in the definition and never reach williams_entries.part_of_speech. Requires the
    # core to be built (run 50_build_unified.py first). Falls back to the raw *_entries
    # columns only if the core is empty (e.g. a fresh DB before the first unify).
    allp = {}
    core_rows = con.execute(
        "SELECT e.source_id, s.part_of_speech, COUNT(*) "
        "FROM sense s JOIN entry e ON e.id = s.entry_id "
        "WHERE s.part_of_speech IS NOT NULL AND s.part_of_speech!='' "
        "GROUP BY e.source_id, s.part_of_speech"
    ).fetchall()
    if core_rows:
        for sid, pos, n in core_rows:
            for tok in (x.strip() for x in pos.split(",")):
                if not tok:
                    continue
                allp.setdefault(tok, {})
                allp[tok][sid] = allp[tok].get(sid, 0) + n
    else:
        for sid, t in SOURCES.items():
            for pos, n in con.execute(
                f"SELECT part_of_speech, COUNT(*) FROM {t} "
                f"WHERE part_of_speech IS NOT NULL AND part_of_speech!='' GROUP BY part_of_speech"
            ):
                for tok in (x.strip() for x in pos.split(",")):
                    if not tok:
                        continue
                    allp.setdefault(tok, {})
                    allp[tok][sid] = allp[tok].get(sid, 0) + n

    con.executescript(DDL)
    rid = seeded = review = kept = 0
    for raw in sorted(allp, key=lambda k: -sum(allp[k].values())):
        rid += 1
        counts = allp[raw]
        is_loan = 1 if "loan" in raw.strip().lower() else 0
        prev = preserved.get(raw)
        notes = prev[3] if prev else None
        if prev and (prev[0] or prev[1] or prev[2] in ("reviewed", "not_pos")):
            # carry forward existing canonical / reviewed / not_pos decision
            canon_en, canon_mi, status = prev[0], prev[1], prev[2] or "seeded"
            kept += 1
        else:
            em = SEED.get(raw.strip().lower())
            if em:
                canon_en, canon_mi, status = em[0], em[1], "seeded"
                seeded += 1
            else:
                canon_en = canon_mi = None
                status = "needs_review"
                review += 1
        con.execute(
            "INSERT INTO std_pos (id,raw_pos,source_counts,total_count,is_loan,"
            "canonical_en,canonical_mi,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, raw, json.dumps(counts, ensure_ascii=False), sum(counts.values()),
             is_loan, canon_en, canon_mi, status, notes, NOW))
    con.commit()
    print(f"std_pos rebuilt ATOMIC-only: {rid} codes "
          f"(preserved={kept}, freshly seeded={seeded}, needs_review={review})")
    applied = load_seed(con)
    if applied:
        print(f"  applied {applied} committed decisions from {SEED_CSV.name} (fill-only)")
    tot = con.execute("SELECT SUM(total_count) FROM std_pos").fetchone()[0]
    cov = con.execute(
        "SELECT SUM(total_count) FROM std_pos WHERE canonical_en IS NOT NULL"
    ).fetchone()[0] or 0
    print(f"  canonical_en coverage: {cov}/{tot} code-occurrences ({100*cov/tot:.1f}%)")
    print("\ntop needs_review atomic codes (expert to map):")
    for raw, n, sc in con.execute(
        "SELECT raw_pos,total_count,source_counts FROM std_pos "
        "WHERE status='needs_review' ORDER BY total_count DESC LIMIT 15"
    ):
        print(f"  {n:6} {raw!r:18} {sc}")
    con.close()


if __name__ == "__main__":
    main()
