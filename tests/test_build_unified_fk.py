"""delete_source_slice must not trip foreign_keys=ON when external link tables
(pollex_entry_links from 08b, ETY_entry_link from 52) still reference entry.id.

Unit test on a minimal in-memory schema — does not touch the staging DB.
"""

import importlib
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

bu = importlib.import_module("50_build_unified")


def _mini_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("CREATE TABLE entry (id INTEGER PRIMARY KEY, source_id INTEGER)")
    for child in ("example", "entry_domain", "relation", "form", "sense"):
        con.execute(f"CREATE TABLE {child} "
                    "(entry_id INTEGER REFERENCES entry(id))")
    con.execute("CREATE TABLE pollex_entry_links "
                "(entry_id INTEGER REFERENCES entry(id))")
    con.execute("CREATE TABLE ETY_entry_link "
                "(entry_id INTEGER REFERENCES entry(id))")
    con.execute("INSERT INTO entry (id, source_id) VALUES (1, 7)")
    con.execute("INSERT INTO pollex_entry_links (entry_id) VALUES (1)")
    con.execute("INSERT INTO ETY_entry_link (entry_id) VALUES (1)")
    return con


class EntryLinkTableClearing(unittest.TestCase):
    def test_delete_source_slice_blocked_without_clear(self):
        con = _mini_db()
        with self.assertRaises(sqlite3.IntegrityError):
            bu.delete_source_slice(con, 7)

    def test_clear_entry_link_tables_unblocks_delete(self):
        con = _mini_db()
        cleared = bu.clear_entry_link_tables(con)
        self.assertEqual(cleared, 2)
        deleted = bu.delete_source_slice(con, 7)
        self.assertEqual(deleted, 1)
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM entry").fetchone()[0], 0)

    def test_clear_skips_missing_tables(self):
        con = _mini_db()
        con.execute("DROP TABLE pollex_entry_links")
        cleared = bu.clear_entry_link_tables(con)
        self.assertEqual(cleared, 1)


if __name__ == "__main__":
    unittest.main()


class InboundCrossSourceRelationsAreReportedNotJustReleased(unittest.TestCase):
    """Deleting a slice must SAY which sources lost their resolution.

    Relations from other sources point into the slice being deleted — 5,503
    te_matatiki relations resolve to Williams entries — and those foreign keys
    would block the delete, so they are released to NULL. The rows survive;
    only the resolution is lost, and it comes back when those OTHER sources
    are re-unified.

    Nothing about that is visible in the data afterwards. The only signal is
    the message printed here, and it is load-bearing: without reading it, a
    `--source williams` rebuild looks like it succeeded while the derivation
    table quietly halves and te_matatiki's links stop resolving. That happened
    — the message was printed and scrolled past — and the symptom took a full
    eleven-source rebuild to undo instead of the one source it names.

    So this pins the diagnostic itself, not only the release.
    """

    def _db(self):
        con = sqlite3.connect(":memory:")
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("CREATE TABLE entry (id INTEGER PRIMARY KEY, "
                    "source_id TEXT)")
        for child in ("example", "entry_domain", "form", "sense"):
            con.execute(f"CREATE TABLE {child} "
                        "(entry_id INTEGER REFERENCES entry(id))")
        con.execute("CREATE TABLE relation ("
                    " id INTEGER PRIMARY KEY,"
                    " entry_id INTEGER REFERENCES entry(id),"
                    " target_entry_id INTEGER REFERENCES entry(id))")
        con.executemany("INSERT INTO entry (id, source_id) VALUES (?,?)",
                        [(1, "williams"), (2, "te_matatiki"), (3, "te_aka")])
        # Two foreign sources pointing into williams, plus one williams row
        # pointing at itself, which is deleted rather than released.
        con.executemany("INSERT INTO relation (entry_id, target_entry_id) "
                        "VALUES (?,?)", [(2, 1), (2, 1), (3, 1), (1, 1)])
        return con

    def _run(self, con):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bu.delete_source_slice(con, "williams")
        return buf.getvalue()

    def test_it_names_every_source_that_lost_a_target(self):
        out = self._run(self._db())
        self.assertIn("te_matatiki", out)
        self.assertIn("te_aka", out)

    def test_it_counts_what_each_source_lost(self):
        out = self._run(self._db())
        self.assertIn("te_matatiki (2)", out)
        self.assertIn("te_aka (1)", out)

    def test_it_gives_the_command_that_earns_the_targets_back(self):
        out = self._run(self._db())
        self.assertIn("50_build_unified.py --source", out)
        self.assertIn("--source te_matatiki", out)

    def test_the_foreign_rows_survive_with_their_target_released(self):
        con = self._db()
        self._run(con)
        rows = con.execute(
            "SELECT entry_id, target_entry_id FROM relation "
            " ORDER BY entry_id").fetchall()
        # williams' own relation went with the slice; the foreign ones stayed.
        self.assertEqual([(2, None), (2, None), (3, None)], rows)

    def test_a_slice_nothing_points_into_says_nothing(self):
        con = self._db()
        con.execute("DELETE FROM relation")
        con.execute("INSERT INTO relation (entry_id, target_entry_id) "
                    "VALUES (2, NULL)")
        self.assertEqual("", self._run(con).strip())
