"""Macron election listens only to attested word formation.

_derived_long settles a macron by morphology: if `derivation` says hōmai is
hō + mai, the long vowel is decided without a vote. That authority rests on
the pairing being the source's own statement.

ngata's rows are not. The source printed 'ahu, ahutia' in one run and our
suffix rules matched the spellings, so the pairing is our segmentation —
derived = 1, confidence 'probable'. Election propagates into the app's
canonical headword and is expensive to audit afterwards, so a probable
pairing does not get to settle a spelling.

This changes no election today: all 1,195 ngata member keys with a macronised
base were measured against the pre-change database and moved zero of 91,140
elected headwords. The guard is here so a future refresh cannot quietly turn
a mis-attributed base into a macron.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "build_concepts",
    Path(__file__).parent.parent / "scripts" / "54_build_concepts.py")
build_concepts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_concepts)


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
            headword TEXT);
        CREATE TABLE derivation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, base_form TEXT,
            evidence TEXT, derived INTEGER, confidence TEXT);
        INSERT INTO entry VALUES (1, 'williams', '10', 'hōmai'),
                                 (2, 'ngata',    '20', 'whākina'),
                                 (3, 'ngata',    '30', 'ahutia');
        INSERT INTO derivation VALUES
            (1, 1, 'hō',    'williams: printed under this base entry', 0, 'certain'),
            (2, 2, 'whāki', 'ngata: printed in one run with its base',  1, 'probable'),
            (3, 3, 'ahu',   'ngata: printed in one run with its base',  1, 'probable');
    """)
    return con


class DerivedLong(unittest.TestCase):
    def setUp(self):
        self.keys = build_concepts._derived_long(_db())

    def test_an_attested_long_base_still_settles_the_macron(self):
        self.assertIn(("williams", "10"), self.keys)

    def test_a_segmented_pairing_does_not_settle_a_macron(self):
        self.assertNotIn(("ngata", "20"), self.keys)

    def test_a_segmented_pairing_with_no_macron_was_never_a_candidate(self):
        self.assertNotIn(("ngata", "30"), self.keys)

    def test_the_attested_row_is_the_only_one_kept(self):
        self.assertEqual(self.keys, {("williams", "10")})

    def test_a_missing_derivation_table_is_still_tolerated(self):
        # The concept-build fixture has no derivation table; the guard that
        # allows that must survive the added WHERE clause.
        bare = sqlite3.connect(":memory:")
        bare.executescript("CREATE TABLE entry (id INTEGER PRIMARY KEY);")
        self.assertEqual(build_concepts._derived_long(bare), set())
