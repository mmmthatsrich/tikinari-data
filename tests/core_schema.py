"""The real schema, for tests that need one (D48).

Fixtures used to write their own `CREATE TABLE`s. Measured across `tests/`,
that was 76 hand-rolled core tables in 26 files missing 460 column
declarations between them — `test_concept_build`'s `entry` had 8 of 19
columns, `test_derivation_evidence`'s had 4.

Two things made that a problem. Every schema addition became a multi-file
edit: `relation.sense_id` (D46) broke two tests that had nothing to do with
relations, and `concept_member.confirmed_grouping` (D47) broke a third. And a
fixture could diverge in ways nothing catches — a missing column fails loudly,
but a wrong type or an absent constraint does not, so the test passes against
a table the pipeline has never run on. That is how the D46 fixture was first
written, with a `te_aka_entries` that had no `senses` column.

`00_init_db.initialise()` is what the pipeline runs, so it is what a fixture
should run.

    from core_schema import core_db

    con = core_db()

A hand-rolled table is still right where a test needs a shape the real schema
does NOT have — `test_build_unified_fk.py` builds a deliberately minimal one
to exercise foreign-key behaviour, and the real schema would obscure that, not
help it. Say so in a comment when you do.
"""
import importlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

_init_db = importlib.import_module("00_init_db")

# Built once and cloned per call: initialise() takes ~11ms and a backup ~0.6ms,
# which matters when most of a 1,400-test suite wants a database.
_TEMPLATE = None


def core_db(*, foreign_keys: bool = False) -> sqlite3.Connection:
    """An in-memory database carrying the schema the pipeline builds.

    Foreign keys are OFF by default, which is SQLite's own default and what
    the pipeline's own connections use. Pass `foreign_keys=True` for a test
    that is specifically about referential integrity.
    """
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = sqlite3.connect(":memory:")
        _init_db.initialise(_TEMPLATE)
    con = sqlite3.connect(":memory:")
    _TEMPLATE.backup(con)
    if foreign_keys:
        con.execute("PRAGMA foreign_keys = ON")
    return con
