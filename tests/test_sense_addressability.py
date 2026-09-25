"""Pointing entry-level references at a sense.

Three tables could name a headword but never a sense: ETY_entry_link, relation,
and cross_source_candidates. Williams says 'see apa (i), sense 2' and POLLEX
says '*afo means fishing-line, which is sense 2', and the schema could express
neither.

Where an entry has exactly ONE sense the target is determined, not judged — 89%
of etymology links and 58% of resolved relations are in that position. This
resolves those and leaves the rest NULL for the audit sweep.

Unit test on the real schema (see core_schema); does not touch the staging DB.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from core_schema import core_db
from utils import resolve_unambiguous_senses


def _db() -> sqlite3.Connection:
    con = core_db()
    # entry 1: one sense (10).  entry 2: two senses (20, 21).  entry 3: none.
    # The NOT NULL columns this test has no opinion about are named with
    # literals rather than threaded through the parameters.
    con.executemany(
        "INSERT INTO entry (id, source_id, headword, headword_sort, "
        "  headword_search) VALUES (?, 'x', '', '', '')",
        [(1,), (2,), (3,)])
    con.executemany("INSERT INTO sense (id, entry_id) VALUES (?,?)",
                    [(10, 1), (20, 2), (21, 2)])
    return con


class ResolveUnambiguousSenses(unittest.TestCase):
    def test_a_link_to_a_single_sense_entry_is_resolved(self):
        con = _db()
        con.execute("INSERT INTO ETY_entry_link (id, cognateset_id, source, entry_id) VALUES (1, 1, 'tregear', 1)")
        resolve_unambiguous_senses(con)
        self.assertEqual(
            con.execute("SELECT sense_id FROM ETY_entry_link WHERE id=1").fetchone()[0],
            10)

    def test_a_link_to_a_multi_sense_entry_is_left_for_the_sweep(self):
        con = _db()
        con.execute("INSERT INTO ETY_entry_link (id, cognateset_id, source, entry_id) VALUES (1, 1, 'tregear', 2)")
        resolve_unambiguous_senses(con)
        self.assertIsNone(
            con.execute("SELECT sense_id FROM ETY_entry_link WHERE id=1").fetchone()[0])

    def test_a_relation_target_with_one_sense_is_resolved(self):
        con = _db()
        con.execute("INSERT INTO relation (id, rel_type, target_headword, entry_id, "
                    "  target_entry_id) "
                    "VALUES (1, 'x', '', 2, 1)")
        resolve_unambiguous_senses(con)
        self.assertEqual(
            con.execute("SELECT target_sense_id FROM relation WHERE id=1").fetchone()[0],
            10)

    def test_a_relation_target_with_two_senses_is_left_null(self):
        con = _db()
        con.execute("INSERT INTO relation (id, rel_type, target_headword, entry_id, "
                    "  target_entry_id) "
                    "VALUES (1, 'x', '', 1, 2)")
        resolve_unambiguous_senses(con)
        self.assertIsNone(
            con.execute("SELECT target_sense_id FROM relation WHERE id=1").fetchone()[0])

    def test_an_unresolved_relation_target_is_skipped(self):
        con = _db()
        con.execute("INSERT INTO relation (id, rel_type, target_headword, entry_id, "
                    "  target_entry_id) "
                    "VALUES (1, 'x', '', 1, NULL)")
        resolve_unambiguous_senses(con)
        self.assertIsNone(
            con.execute("SELECT target_sense_id FROM relation WHERE id=1").fetchone()[0])

    def test_an_entry_with_no_senses_resolves_to_nothing(self):
        con = _db()
        con.execute("INSERT INTO ETY_entry_link (id, cognateset_id, source, entry_id) VALUES (1, 1, 'tregear', 3)")
        resolve_unambiguous_senses(con)
        self.assertIsNone(
            con.execute("SELECT sense_id FROM ETY_entry_link WHERE id=1").fetchone()[0])

    def test_a_sense_already_chosen_is_never_overwritten(self):
        # The sweep's judgement on a multi-sense entry must survive a re-run.
        con = _db()
        con.execute("INSERT INTO ETY_entry_link (id, cognateset_id, source, "
                    "  entry_id, sense_id) "
                    "VALUES (1, 1, 'tregear', 2, 21)")
        resolve_unambiguous_senses(con)
        self.assertEqual(
            con.execute("SELECT sense_id FROM ETY_entry_link WHERE id=1").fetchone()[0],
            21)

    def test_it_reports_what_it_resolved(self):
        con = _db()
        con.execute("INSERT INTO ETY_entry_link (id, cognateset_id, source, entry_id) VALUES (1, 1, 'tregear', 1)")
        con.execute("INSERT INTO relation (id, rel_type, target_headword, entry_id, "
                    "  target_entry_id) "
                    "VALUES (1, 'x', '', 2, 1)")
        counts = resolve_unambiguous_senses(con)
        self.assertEqual(counts, {"ETY_entry_link": 1, "relation": 1})

    def test_running_twice_changes_nothing_the_second_time(self):
        con = _db()
        con.execute("INSERT INTO ETY_entry_link (id, cognateset_id, source, entry_id) VALUES (1, 1, 'tregear', 1)")
        resolve_unambiguous_senses(con)
        self.assertEqual(resolve_unambiguous_senses(con),
                         {"ETY_entry_link": 0, "relation": 0})

    def test_a_missing_table_is_not_an_error(self):
        # 52_build_etymology_unified runs against DBs that may predate relation.
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE entry (id INTEGER PRIMARY KEY);"
                          "CREATE TABLE sense (id INTEGER PRIMARY KEY, entry_id INTEGER);")
        self.assertEqual(resolve_unambiguous_senses(con), {})


if __name__ == "__main__":
    unittest.main()
