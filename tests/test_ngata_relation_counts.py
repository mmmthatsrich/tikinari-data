"""Corpus-wide counts for the ngata base/passive relation split.

Before the fix, _wakareo_en_mi cross-filed every equivalent in a record's
comma-separated run as a synonym of every other, so 4,646 base+derived pairs
were filed twice over as mutual synonyms — 9,292 directed relations claiming
'ahu' means the same as 'ahutia'.

Measured on 2026-09-19, after the rebuild:
    ngata synonym      35,868 -> 26,576   (-9,292)
    ngata derived_from      0 ->  4,646
    relation total    180,053 -> 175,407  (-4,646 net; the inverse
                                           direction is not re-filed)
    derivation          6,778 -> 11,424

The seven surviving te_aka rows are deliberate: te_aka states those links
itself through its dictionary-link anchors, so they are the source's
editorial choice rather than an artefact of our loop. Overriding a source is
a different decision from fixing our own bug.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

DERIVED = ("passive", "nominalisation")

# A synonym relation whose two ends are also recorded as a base and its
# derived form — in either direction.
DUPLICATES_A_FORM = (
    "SELECT e.source_id, COUNT(*) FROM relation r "
    "JOIN entry e ON e.id = r.entry_id "
    "WHERE r.rel_type = 'synonym' AND ("
    "  EXISTS (SELECT 1 FROM form f WHERE f.entry_id = r.entry_id "
    "          AND f.form = r.target_headword AND f.form_type IN (?, ?))"
    "  OR EXISTS (SELECT 1 FROM form f WHERE f.entry_id = r.target_entry_id "
    "          AND f.form = e.headword AND f.form_type IN (?, ?))"
    ") GROUP BY 1")


def _open():
    # Read-only: this suite must never alter the working database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class NgataRelations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def _by_type(self, rel_type, source):
        return self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id = r.entry_id "
            "WHERE r.rel_type = ? AND e.source_id = ?", rel_type, source)

    def test_no_ngata_synonym_restates_a_derived_form(self):
        got = dict(self.con.execute(DUPLICATES_A_FORM, DERIVED + DERIVED))
        self.assertEqual(got.get("ngata", 0), 0)

    def test_te_akas_own_links_are_left_alone(self):
        # te_aka asserts these itself; our loop did not invent them. A drop to
        # zero here means someone widened the fix past its warrant.
        got = dict(self.con.execute(DUPLICATES_A_FORM, DERIVED + DERIVED))
        self.assertEqual(got.get("te_aka", 0), 7)

    def test_ngata_still_has_its_genuine_synonyms(self):
        # The run really does hold synonyms too; removing them all would mean
        # the suffix rules were matching words that are not derivations.
        self.assertGreater(self._by_type("synonym", "ngata"), 26000)

    def test_every_ngata_pair_became_a_derived_from(self):
        self.assertEqual(self._by_type("derived_from", "ngata"), 4646)

    def test_williams_keeps_its_own_derived_from_rows(self):
        self.assertEqual(self._by_type("derived_from", "williams"), 1507)

    def test_each_pair_is_filed_once_not_both_ways(self):
        # The inverse row is deliberately not written. Two rows per pair would
        # mean the old bidirectional shape survived under a new rel_type.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM relation a JOIN relation b "
            "  ON a.entry_id = b.target_entry_id "
            " AND b.entry_id = a.target_entry_id "
            "WHERE a.rel_type = 'derived_from' AND b.rel_type = 'derived_from'"),
            0)

    def test_every_ngata_derived_from_resolves_its_base(self):
        # 53_build_word_origin drops any row whose target_entry_id is NULL, so
        # an unresolved one would vanish silently from the derivation table.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM relation r JOIN entry e ON e.id = r.entry_id "
            "WHERE r.rel_type = 'derived_from' AND e.source_id = 'ngata' "
            "  AND r.target_entry_id IS NULL"), 0)

    def test_the_pairs_reached_the_derivation_table(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE evidence LIKE 'ngata%'"),
            4646)

    def test_a_derived_form_is_never_its_own_base(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM relation "
            "WHERE rel_type = 'derived_from' AND entry_id = target_entry_id"), 0)
