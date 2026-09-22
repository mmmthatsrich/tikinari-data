"""A derivation row names the source that actually supports it.

`derived_from` was a Williams-only relation, so collect_derivations selected
every one of them and stamped the Williams evidence string on it without
checking. ngata now writes derived_from too, from a different kind of
warrant: Williams PRINTS the derivative inside its base entry's paragraph,
while ngata merely lists both in one run and our suffix rules matched the
spellings. The first is attested, the second is segmented — which is what
derivation.derived exists to separate.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "word_origin",
    Path(__file__).parent.parent / "scripts" / "53_build_word_origin.py")
word_origin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(word_origin)


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, headword TEXT,
            loan_marker TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            gloss_en TEXT);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER, note TEXT);
        -- collect_derivations reads form to see whether another source
        -- independently records an ngata derived form; empty here, so
        -- these rows stay 'probable'.
        CREATE TABLE form (
            id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT,
            form_type TEXT, note TEXT);
        INSERT INTO entry VALUES (1, 'williams', 'hopukia', NULL),
                                 (2, 'williams', 'hopu',    NULL),
                                 (3, 'ngata',    'ahutia',  NULL),
                                 (4, 'ngata',    'ahu',     NULL);
        INSERT INTO sense VALUES (10, 1, 1, NULL), (11, 2, 1, NULL),
                                 (12, 3, 1, NULL), (13, 4, 1, NULL);
        INSERT INTO relation VALUES
            (100, 1, 'derived_from', 'hopu', 2, NULL),
            (101, 3, 'derived_from', 'ahu',  4, NULL);
    """)
    return con


class Evidence(unittest.TestCase):
    def setUp(self):
        self.rows = {r["base_form"]: r
                     for r in word_origin.collect_derivations(_db())}

    def test_williams_keeps_its_own_evidence(self):
        self.assertEqual(self.rows["hopu"]["evidence"],
                         "williams: printed under this base entry")

    def test_ngata_is_not_labelled_as_williams(self):
        self.assertEqual(self.rows["ahu"]["evidence"],
                         "ngata: printed in one run with its base")

    def test_an_attested_row_stays_attested(self):
        self.assertEqual(
            (self.rows["hopu"]["derived"], self.rows["hopu"]["confidence"]),
            (0, "certain"))

    def test_a_segmented_row_says_so(self):
        # derived=1 is 'segmented, not attested' per the schema comment. The
        # longest-base rule in derived_from_list makes the match good, not
        # certain: 'patu' + '-kia' also fits 'pātukia', which is really
        # 'pātuki' + '-a'.
        self.assertEqual(
            (self.rows["ahu"]["derived"], self.rows["ahu"]["confidence"]),
            (1, "probable"))

    def test_a_source_with_no_recorded_warrant_is_skipped(self):
        # Silence beats inheriting whichever label happened to sit in the
        # block — the exact defect this mapping replaces.
        con = _db()
        con.executescript("""
            INSERT INTO entry VALUES (5, 'te_aka', 'kakea', NULL),
                                     (6, 'te_aka', 'kake',  NULL);
            INSERT INTO sense VALUES (14, 5, 1, NULL), (15, 6, 1, NULL);
            INSERT INTO relation VALUES
                (102, 5, 'derived_from', 'kake', 6, NULL);
        """)
        bases = [r["base_form"] for r in word_origin.collect_derivations(con)]
        self.assertNotIn("kake", bases)
        self.assertEqual(sorted(bases), ["ahu", "hopu"])

    def test_both_still_read_their_affix_off_the_spellings(self):
        self.assertEqual(self.rows["hopu"]["process"], "suffix")
        self.assertEqual(self.rows["ahu"]["affix"], "-tia")
