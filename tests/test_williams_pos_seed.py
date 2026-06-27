import sqlite3, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from utils import DB_PATH

# Williams inline POS abbreviations that 13_build_pos_normalisation seeds. Exact
# canonical_en/mi are NOT asserted — std_pos is expert-reviewed and reviewers may
# change labels; this test only guards that each abbrev exists and is mapped (has a
# canonical_en) so the seeding wiring doesn't silently drop them.
WILLIAMS_ABBREVS = ["l.n.", "ad.", "pt.", "pos.", "def.", "indef.", "prefix.", "num."]

class TestWilliamsPOSSeed(unittest.TestCase):

    def test_williams_abbrevs_mapped(self):
        with sqlite3.connect(DB_PATH) as conn:
            for raw in WILLIAMS_ABBREVS:
                row = conn.execute(
                    "SELECT canonical_en, status FROM std_pos WHERE raw_pos=?", (raw,)
                ).fetchone()
                self.assertIsNotNone(row, f"{raw} missing from std_pos")
                # mapped (seeded/reviewed) unless a reviewer marked it not_pos
                if row[1] != "not_pos":
                    self.assertIsNotNone(row[0], f"{raw} has no canonical_en (status={row[1]})")
