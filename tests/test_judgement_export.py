"""The human-authored state is the only thing here that cannot be regenerated.

Everything else in the staging database is a projection: delete it and a
script rebuilds it. Sweep judgements are not. They are decisions a person
made one cluster at a time, they live in a gitignored 568 MB database on one
disk, and nothing outside that disk has a copy.

This exports them to a small, deterministic file that git can hold, and
restores them onto a database that has lost them. A dump with no restore
path is not a backup, so both directions are tested.
"""
import importlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

from sweep_findings import FINDING_DDL
from sweep_patch import PATCH_DDL
from sweep_queue import QUEUE_DDL

mod = importlib.import_module("61_export_judgements")


def _db():
    con = core_db()
    for ddl in (QUEUE_DDL, FINDING_DDL, PATCH_DDL):
        con.executescript(ddl)
    con.executemany(
        "INSERT INTO concept_member (concept_id, source_id, source_entry_id,"
        " sense_number, status, confidence) VALUES (?,?,?,?,?,?)",
        [(1, "te_aka", "15301", 1, "confirmed", "certain"),
         (1, "williams", "73", 1, "rejected", "probable"),
         (2, "ngata", "WR-HMN.1#2~1", None, "confirmed", "probable"),
         (3, "paekupu", "ikarangi", None, "proposed", "certain")])
    con.commit()
    return con


class ExportCarriesOnlyWhatCannotBeRegenerated(unittest.TestCase):
    def test_it_exports_judged_memberships(self):
        got = mod.export_judgements(_db())
        addrs = {(j["source_id"], j["source_entry_id"], j["sense_number"])
                 for j in got["judgements"]}
        self.assertEqual(
            {("te_aka", "15301", 1), ("williams", "73", 1),
             ("ngata", "WR-HMN.1#2~1", None)}, addrs)

    def test_it_leaves_proposed_memberships_out(self):
        # 175,083 of 175,101 rows are 'proposed' — machine output, rebuilt by
        # 54_build_concepts on demand. Carrying them would bury the 18 that
        # matter in a file nobody could read.
        got = mod.export_judgements(_db())
        self.assertNotIn("paekupu", {j["source_id"] for j in got["judgements"]})

    def test_it_carries_no_volatile_ids(self):
        # entry_id, sense_id and concept_id are reminted by every rebuild.
        # Exporting them would restore a judgement onto the wrong row.
        for j in mod.export_judgements(_db())["judgements"]:
            self.assertEqual({"source_id", "source_entry_id", "sense_number",
                              "status"}, set(j))

    def test_it_is_deterministic(self):
        # The file lands in git, so two dumps of one database must be byte
        # identical or every commit shows spurious churn.
        a, b = mod.export_judgements(_db()), mod.export_judgements(_db())
        self.assertEqual(json.dumps(a, sort_keys=True),
                         json.dumps(b, sort_keys=True))


class RestorePutsThemBack(unittest.TestCase):
    def test_it_restores_a_lost_judgement(self):
        con = _db()
        payload = mod.export_judgements(con)
        con.execute("UPDATE concept_member SET status='proposed'")
        con.commit()
        mod.restore_judgements(con, payload)
        got = dict(con.execute(
            "SELECT source_id || ':' || source_entry_id, status "
            "  FROM concept_member WHERE status <> 'proposed'").fetchall())
        self.assertEqual({"te_aka:15301": "confirmed",
                          "williams:73": "rejected",
                          "ngata:WR-HMN.1#2~1": "confirmed"}, got)

    def test_it_reports_a_judgement_whose_row_is_gone(self):
        # A restore onto a corpus that no longer holds the sense must say so
        # rather than silently dropping a human decision.
        con = _db()
        payload = mod.export_judgements(con)
        con.execute("DELETE FROM concept_member WHERE source_id='williams'")
        con.commit()
        result = mod.restore_judgements(con, payload)
        self.assertEqual(2, result["restored"])
        self.assertEqual(["williams:73#1"], result["missing"])

    def test_restoring_twice_changes_nothing_the_second_time(self):
        con = _db()
        payload = mod.export_judgements(con)
        con.execute("UPDATE concept_member SET status='proposed'")
        con.commit()
        mod.restore_judgements(con, payload)
        again = mod.restore_judgements(con, payload)
        self.assertEqual(3, again["restored"])
        self.assertEqual([], again["missing"])


if __name__ == "__main__":
    unittest.main()
