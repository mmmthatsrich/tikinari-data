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
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

NOW = datetime.now(timezone.utc).isoformat()
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
    "ad.": ("Adverb", None),
    "conjunction": ("Conjunction", None),
    "conj.": ("Conjunction", None),
    "determiner": ("Determiner", None),
    "negative": ("Negative", None),
    "causative": ("Verb (causative)", None),
    "universal": ("Universal", None),
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

    # 2. atomic inventory: split comma-combined POS into atomic codes
    allp = {}
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
