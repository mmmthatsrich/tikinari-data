"""Resolving within-source relation targets.

14,853 relations name a headword that exists in their own source and were never
resolved: hepatakakupu's synonyms had no resolution pass at all, though Te Aka's
synonyms and Williams's see_also each have one.

Only 5,197 of those are unambiguous. The other 9,656 name a headword carried by
two or more entries in the same source — hepatakakupu splits senses across
entries, so 'ahu' is several rows — and picking one would be a guess dressed as
a fact. Those stay NULL and become the sweep's.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

from utils import resolve_within_source_relations


def _db() -> sqlite3.Connection:
    con = core_db()
    con.executemany("INSERT INTO entry (id, source_id, headword, headword_sort, headword_search)VALUES (?,?,?, '', '')", [
        (1, "hepatakakupu", "ahuahu"),
        (2, "hepatakakupu", "harahara"),     # unique target
        (3, "hepatakakupu", "ahu"),          # ambiguous: two entries share it
        (4, "hepatakakupu", "ahu"),
        (5, "te_aka", "harahara"),           # same word, different source
    ])
    con.commit()
    return con


def _rel(con, target, entry_id=1, rel_id=1):
    con.execute("INSERT INTO relation (id, entry_id, rel_type, target_headword) "
                "VALUES (?,?,'synonym',?)", (rel_id, entry_id, target))
    con.commit()


def _target(con, rel_id=1):
    return con.execute("SELECT target_entry_id FROM relation WHERE id=?",
                       (rel_id,)).fetchone()[0]


class ResolveWithinSource(unittest.TestCase):
    def test_a_unique_target_in_the_same_source_resolves(self):
        con = _db()
        _rel(con, "harahara")
        self.assertEqual(resolve_within_source_relations(con), 1)
        self.assertEqual(_target(con), 2)

    def test_an_ambiguous_target_is_left_for_the_sweep(self):
        con = _db()
        _rel(con, "ahu")
        self.assertEqual(resolve_within_source_relations(con), 0)
        self.assertIsNone(_target(con))

    def test_it_never_resolves_across_sources(self):
        # entry 5 is te_aka 'harahara'; a te_aka relation must not pick up the
        # hepatakakupu entry of the same name, or vice versa.
        con = _db()
        con.execute("DELETE FROM entry WHERE id=2")      # drop the hepatakakupu one
        con.commit()
        _rel(con, "harahara")
        self.assertEqual(resolve_within_source_relations(con), 0)
        self.assertIsNone(_target(con))

    def test_an_unknown_target_stays_null(self):
        con = _db()
        _rel(con, "kahoretenei")
        self.assertEqual(resolve_within_source_relations(con), 0)
        self.assertIsNone(_target(con))

    def test_an_existing_target_is_never_overwritten(self):
        con = _db()
        _rel(con, "harahara")
        con.execute("UPDATE relation SET target_entry_id=999 WHERE id=1")
        con.commit()
        self.assertEqual(resolve_within_source_relations(con), 0)
        self.assertEqual(_target(con), 999)

    def test_a_relation_never_points_at_its_own_entry(self):
        # hepatakakupu:1 is 'ahuahu'; a synonym row naming 'ahuahu' on that same
        # entry is a self-reference, not a cross-reference.
        con = _db()
        _rel(con, "ahuahu", entry_id=1)
        self.assertEqual(resolve_within_source_relations(con), 0)
        self.assertIsNone(_target(con))

    def test_running_twice_resolves_nothing_the_second_time(self):
        con = _db()
        _rel(con, "harahara")
        resolve_within_source_relations(con)
        self.assertEqual(resolve_within_source_relations(con), 0)

    def test_a_missing_relation_table_is_not_an_error(self):
        # Deliberately NOT core_db(): the point is a database that LACKS the
        # relation table, and the real schema has one.
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE entry (id INTEGER PRIMARY KEY)")
        self.assertEqual(resolve_within_source_relations(con), 0)


if __name__ == "__main__":
    unittest.main()
