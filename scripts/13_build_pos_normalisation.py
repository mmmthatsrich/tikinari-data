"""Build the part-of-speech normalisation table (std_pos).

Collects every distinct raw part_of_speech value used across the source dictionaries,
records which sources use it and how often, and provides canonical_en / canonical_mi
columns so the 315+ raw variants can be normalised to one controlled vocabulary and
translated to Māori.

Confident mappings are pre-seeded (English from standard grammar, Māori from Paekupu's
authoritative pos_mi vocabulary: tūingoa, tūmahi, tūmahi whiti, tūmahi poro, tūāhua,
tūwāhi). Everything else is left with status='needs_review' for an expert to complete —
especially the He Pātaka Kupu compound abbreviation codes (ing, mahp, mahw, āhua, …).

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

# raw value (lower-cased) -> (canonical_en, canonical_mi|None)
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
    raw_pos       TEXT NOT NULL,        -- exact value as stored in a source
    source_counts TEXT,                 -- JSON {source_id: count}
    total_count   INTEGER,
    is_loan       INTEGER DEFAULT 0,    -- raw value carried a 'loan' marker
    canonical_en  TEXT,                 -- normalised English POS (controlled vocab)
    canonical_mi  TEXT,                 -- Māori translation
    status        TEXT,                 -- seeded | needs_review
    notes         TEXT,
    created_at    TEXT
);
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    con = sqlite3.connect(DB_PATH)

    allp = {}
    for sid, t in SOURCES.items():
        for pos, n in con.execute(
            f"SELECT part_of_speech, COUNT(*) FROM {t} "
            f"WHERE part_of_speech IS NOT NULL AND part_of_speech!='' GROUP BY part_of_speech"
        ):
            allp.setdefault(pos, {})[sid] = n

    con.executescript(DDL)
    rid = 0
    seeded = review = 0
    for raw in sorted(allp, key=lambda k: -sum(allp[k].values())):
        rid += 1
        counts = allp[raw]
        key = raw.strip().lower()
        is_loan = 1 if "loan" in key else 0
        # strip a leading 'loan,' for mapping lookup
        lookup = key.replace("loan,", "").replace("loan", "").strip().strip(",").strip()
        en_mi = SEED.get(key) or SEED.get(lookup)
        if en_mi:
            canon_en, canon_mi = en_mi
            status = "seeded"
            seeded += 1
        else:
            canon_en = canon_mi = None
            status = "needs_review"
            review += 1
        con.execute(
            "INSERT INTO std_pos (id,raw_pos,source_counts,total_count,is_loan,"
            "canonical_en,canonical_mi,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, raw, json.dumps(counts, ensure_ascii=False), sum(counts.values()),
             is_loan, canon_en, canon_mi, status, None, NOW))
    con.commit()
    print(f"std_pos: {rid} distinct raw POS values  (seeded={seeded}, needs_review={review})")
    print("\ncanonical_en coverage by row-volume:")
    tot = con.execute("SELECT SUM(total_count) FROM std_pos").fetchone()[0]
    cov = con.execute("SELECT SUM(total_count) FROM std_pos WHERE status='seeded'").fetchone()[0]
    print(f"  {cov}/{tot} entry-rows ({100*cov/tot:.1f}%) covered by seeded mappings")
    print("\ntop needs_review (expert to map):")
    for raw, n, sc in con.execute(
        "SELECT raw_pos,total_count,source_counts FROM std_pos "
        "WHERE status='needs_review' ORDER BY total_count DESC LIMIT 15"
    ):
        print(f"  {n:6} {raw!r:30} {sc}")
    con.close()


if __name__ == "__main__":
    main()
