"""Domain-aware relation resolution (D29).

Paekupu and He Pātaka Kupu both hold several entries under one headword and
tell them apart by subject domain — paekupu because it is a curriculum
glossary where `kawa` is a Science noun ('sour'), a Technology adjective
('sour, bitter') and a Tikanga ā-Iwi noun ('protocol'). A cross-reference
written inside a Technology entry names the Technology term, but the resolver
only ever compared headwords, so all of those stayed unresolved.

The rule is narrow on purpose: domain only ever *chooses between* candidates
the headword match already found, and only when exactly one survives.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

from utils import resolve_relations_by_domain


def _db() -> sqlite3.Connection:
    con = core_db()
    con.executemany(
        "INSERT INTO entry (id, source_id, headword, part_of_speech, headword_sort, headword_search)VALUES (?,?,?,?, '', '')", [
            (1, "paekupu", "hīmoemoe", "Adjective"),   # the referring entry
            (2, "paekupu", "kawa", "Noun"),            # Pūtaiao
            (3, "paekupu", "kawa", "Noun"),            # Hangarau
            (4, "paekupu", "kawa", "Adjective"),       # Hangarau
            (5, "paekupu", "tio", "Noun"),             # Pūtaiao only
            (6, "paekupu", "tio", "Noun"),             # Tikanga ā-Iwi only
            (7, "te_aka", "kawa", "Adjective"),        # another source entirely
        ])
    con.executemany(
        "INSERT INTO entry_domain (entry_id, domain, domain_lang) VALUES (?,?,?)", [
            (1, "Hangarau", "mi"), (1, "Technology", "en"),
            (2, "Pūtaiao", "mi"),
            (3, "Hangarau", "mi"),
            (4, "Hangarau", "mi"),
            (5, "Pūtaiao", "mi"),
            (6, "Tikanga ā-Iwi", "mi"),
            (7, "Hangarau", "mi"),
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


class ResolveByDomain(unittest.TestCase):
    def test_a_shared_domain_picks_the_one_candidate(self):
        # entry 5 and 6 are both 'tio'; only 5 is Pūtaiao. A Pūtaiao entry
        # referring to 'tio' means that one.
        con = _db()
        con.execute("UPDATE entry_domain SET domain='Pūtaiao' "
                    "WHERE entry_id=1 AND domain_lang='mi'")
        con.commit()
        _rel(con, "tio")
        self.assertEqual(resolve_relations_by_domain(con), 1)
        self.assertEqual(_target(con), 5)

    def test_part_of_speech_decides_when_the_domain_leaves_two(self):
        # 'kawa' 3 and 4 are both Hangarau; hīmoemoe is an Adjective, so the
        # Adjective kawa is the referent. This is the real paekupu:hīmoemoe row.
        con = _db()
        _rel(con, "kawa")
        self.assertEqual(resolve_relations_by_domain(con), 1)
        self.assertEqual(_target(con), 4)

    def test_no_shared_domain_leaves_it_for_the_sweep(self):
        con = _db()
        con.execute("UPDATE entry_domain SET domain='Pāngarau' "
                    "WHERE entry_id=1 AND domain_lang='mi'")
        con.commit()
        _rel(con, "kawa")
        self.assertEqual(resolve_relations_by_domain(con), 0)
        self.assertIsNone(_target(con))

    def test_two_candidates_alike_in_domain_and_pos_stay_unresolved(self):
        con = _db()
        con.execute("UPDATE entry SET part_of_speech='Adjective' WHERE id=3")
        con.commit()
        _rel(con, "kawa")
        self.assertEqual(resolve_relations_by_domain(con), 0)
        self.assertIsNone(_target(con))

    def test_it_never_crosses_a_source_boundary(self):
        # entry 7 is te_aka 'kawa' in Hangarau. Drop the paekupu Hangarau
        # candidates and the relation must NOT reach across to it.
        con = _db()
        con.execute("DELETE FROM entry WHERE id IN (3,4)")
        con.commit()
        _rel(con, "kawa")
        self.assertEqual(resolve_relations_by_domain(con), 0)
        self.assertIsNone(_target(con))

    def test_it_never_points_an_entry_at_itself(self):
        # Entry 1 refers to its own headword. Entries 8 and 9 share it and the
        # domain; part of speech picks 8. Entry 1 must never be its own target,
        # even though it matches the headword, the domain and the POS best.
        con = _db()
        con.executemany(
            "INSERT INTO entry (id, source_id, headword, headword_sort, "
            "  headword_search, part_of_speech) "
            "VALUES (?,'paekupu','hīmoemoe','','',?)",
            [(8, "Adjective"), (9, "Noun")])
        con.executemany(
            "INSERT INTO entry_domain (entry_id, domain, domain_lang) "
            "VALUES (?,'Hangarau','mi')", [(8,), (9,)])
        con.commit()
        _rel(con, "hīmoemoe")
        self.assertEqual(resolve_relations_by_domain(con), 1)
        self.assertEqual(_target(con), 8)

    def test_an_existing_target_is_never_overwritten(self):
        con = _db()
        _rel(con, "kawa")
        con.execute("UPDATE relation SET target_entry_id=2 WHERE id=1")
        con.commit()
        self.assertEqual(resolve_relations_by_domain(con), 0)
        self.assertEqual(_target(con), 2)

    def test_it_is_a_no_op_without_an_entry_domain_table(self):
        con = _db()
        con.execute("DROP TABLE entry_domain")
        con.commit()
        _rel(con, "kawa")
        self.assertEqual(resolve_relations_by_domain(con), 0)


if __name__ == "__main__":
    unittest.main()
