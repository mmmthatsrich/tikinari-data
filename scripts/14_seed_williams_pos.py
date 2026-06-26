"""Seed/patch std_pos canonical labels for the Williams inline POS abbreviations.
canonical_mi only where Paekupu pos_mi matches (Title-cased); else NULL. Idempotent."""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# raw -> (canonical_en, canonical_mi)
SEED = {
    "l.n.":    ("Locative", "Tūwāhi"),
    "ad.":     ("Adverb", "Tūkē"),
    "pt.":     ("Particle", None),
    "pos.":    ("Determiner (possessive)", None),
    "def.":    ("Determiner (definite)", None),
    "indef.":  ("Determiner (indefinite)", None),
    "prefix.": ("Prefix", None),
    "num.":    ("Numeral", None),
}

def seed(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        for raw, (en, mi) in SEED.items():
            exists = conn.execute("SELECT 1 FROM std_pos WHERE raw_pos=?", (raw,)).fetchone()
            if exists:
                conn.execute(
                    "UPDATE std_pos SET canonical_en=?, canonical_mi=?, "
                    "status=CASE WHEN status IS NULL OR status IN ('needs_review','seeded') THEN 'seeded' ELSE status END "
                    "WHERE raw_pos=?",
                    (en, mi, raw),
                )
            else:
                conn.execute(
                    "INSERT INTO std_pos (raw_pos, source_counts, total_count, is_loan, "
                    "canonical_en, canonical_mi, status, notes) "
                    "VALUES (?, '{}', 0, 0, ?, ?, 'seeded', 'williams inline abbrev')",
                    (raw, en, mi),
                )
        conn.commit()
    print(f"Seeded {len(SEED)} Williams POS abbreviations.")

if __name__ == "__main__":
    seed()
