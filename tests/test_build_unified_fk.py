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
