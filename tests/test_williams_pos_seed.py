import sqlite3, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from utils import DB_PATH

EXPECT = {
    "l.n.": ("Locative", "Tūwāhi"),
    "ad.":  ("Adverb", "Tūkē"),
    "pt.":  ("Particle", None),
    "pos.": ("Determiner (possessive)", None),
    "def.": ("Determiner (definite)", None),
    "indef.": ("Determiner (indefinite)", None),
    "prefix.": ("Prefix", None),
    "num.": ("Numeral", None),
}

class TestWilliamsPOSSeed(unittest.TestCase):

    def test_williams_abbrevs_mapped(self):
        with sqlite3.connect(DB_PATH) as conn:
            for raw, (en, mi) in EXPECT.items():
                row = conn.execute(
                    "SELECT canonical_en, canonical_mi FROM std_pos WHERE raw_pos=?", (raw,)
                ).fetchone()
                self.assertIsNotNone(row, f"{raw} missing")
                self.assertEqual(row[0], en, f"{raw} en {row[0]!r}!={en!r}")
                self.assertEqual(row[1], mi, f"{raw} mi {row[1]!r}!={mi!r}")
