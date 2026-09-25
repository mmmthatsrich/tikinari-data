"""A landing table has one owner, and the init sequence is one call.

Two drifts, both found building the D46 fixture rather than by anything
failing, which is what makes them worth a test.

**A landing table had two DDLs.** `04_te_aka_import`, `04_paekupu_import` and
`05_hepataka_import` each DROP and CREATE their own table, so theirs is the
shape the pipeline actually runs on — and `00_init_db` carried a second,
stale copy of each. Measured against the live database when this was written:

    te_aka_entries        missing `senses`
    paekupu_entries       missing alternative_words, audio_url, definition_mi,
                          pos_mi, slug, subject_area_en, subject_areas
    hepatakakupu_entries  missing master_sense, master_word_id,
                          semantic_domain, sense_number, suffixes,
                          synonym_senses, synonyms

Nothing failed, because the importer drops and recreates before anything
reads. It bites the moment something trusts `00_init_db` alone — a fixture,
or a fresh database someone builds and then queries before importing. A
fixture built that way gets a table the pipeline has never seen.

**The init sequence was not one call.** `main()` ran five functions in order,
and `sense.note` comes from `migrate_pos_columns` while `sense.part_of_speech`
comes from `migrate_tables`. Calling a subset produced a database that looked
initialised and silently lacked columns, which is exactly what a fixture does
when it guesses.
"""
import importlib
import re
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

init_db = importlib.import_module("00_init_db")

# {landing table: the module that DROPs and CREATEs it}
OWNED = {
    "te_aka_entries": "04_te_aka_import",
    "paekupu_entries": "04_paekupu_import",
    "hepatakakupu_entries": "05_hepataka_import",
}


def _columns(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


class TheInitSequenceIsOneCall(unittest.TestCase):
    def test_initialise_builds_a_complete_database(self):
        con = sqlite3.connect(":memory:")
        init_db.initialise(con)
        # One column from each of the migration steps that main() ran
        # separately, so dropping any of them from initialise() goes red.
        self.assertIn("note", _columns(con, "sense"))            # migrate_pos_columns
        self.assertIn("part_of_speech_en", _columns(con, "entry"))
        self.assertIn("sense_id", _columns(con, "relation"))     # migrate_tables
        self.assertIn("sense_id", _columns(con, "ETY_entry_link"))

    def test_it_is_idempotent(self):
        con = sqlite3.connect(":memory:")
        init_db.initialise(con)
        init_db.initialise(con)
        self.assertIn("note", _columns(con, "sense"))


class ALandingTableHasOneOwner(unittest.TestCase):
    def test_init_does_not_define_a_table_an_importer_owns(self):
        # The drift cannot come back by someone pasting the CREATE into
        # 00_init_db again: its source must not contain one.
        source = Path(init_db.__file__).read_text(encoding="utf-8")
        for table in OWNED:
            with self.subTest(table=table):
                self.assertNotRegex(
                    source, rf"CREATE TABLE (IF NOT EXISTS )?{table}\b",
                    f"{table} is owned by {OWNED[table]}; 00_init_db must not "
                    f"define it too")

    def test_initialise_produces_the_owner_s_shape(self):
        # And the shape a fresh database gets is the owner's, not a copy of
        # it that can drift again.
        con = sqlite3.connect(":memory:")
        init_db.initialise(con)
        for table, module in OWNED.items():
            with self.subTest(table=table):
                owner = importlib.import_module(module)
                want = sqlite3.connect(":memory:")
                want.executescript(owner._CREATE_SQL)
                self.assertEqual(_columns(con, table), _columns(want, table))

    def test_every_owned_table_is_actually_created(self):
        con = sqlite3.connect(":memory:")
        init_db.initialise(con)
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in OWNED:
            self.assertIn(table, names)


class TheOwnedShapeMatchesTheLiveDatabase(unittest.TestCase):
    """The regression this was written for, against the real staging DB."""

    @classmethod
    def setUpClass(cls):
        cls.live = Path(__file__).parent.parent / "data" / "staging_dictionary.db"
        if not cls.live.exists():
            raise unittest.SkipTest("staging database not present")

    def test_a_fresh_database_matches_what_the_pipeline_built(self):
        fresh = sqlite3.connect(":memory:")
        init_db.initialise(fresh)
        live = sqlite3.connect(self.live)
        for table in OWNED:
            with self.subTest(table=table):
                self.assertEqual(set(_columns(fresh, table)),
                                 set(_columns(live, table)))


if __name__ == "__main__":
    unittest.main()
