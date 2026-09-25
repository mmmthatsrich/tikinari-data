"""build_papakupu emits a derived_from relation per stated reduplication.

A second pass, because the inverse shape is stated on the BASE's entry while
the relation belongs on the CHILD's, and the child may not exist yet when
the base row is read.

Drives the real builder against an in-memory database. Corpus counts live in
tests/test_reduplication_corpus.py.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "build_unified",
    Path(__file__).parent.parent / "scripts" / "50_build_unified.py")
build_unified = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_unified)


def _db(rows):
    """rows: (id, headword, sense_number, definition)"""
    con = core_db()
    con.executemany(
        "INSERT INTO papakupu_entries (id, headword, headword_sort, "
        "headword_search, part_of_speech, definition, usage_examples, "
        "variant_forms, see_also, source_code, loan_marker, sense_number, "
        "pdf_page) VALUES (?,?,?,?,NULL,?,'[]','[]','[]','X',NULL,?,NULL)",
        [(i, hw, hw, hw.lower(), d, sn) for i, hw, sn, d in rows])
    return con


def _relations(con):
    return con.execute(
        "SELECT e.headword, r.rel_type, r.target_headword, r.note "
        "FROM relation r JOIN entry e ON e.id = r.entry_id "
        "WHERE r.rel_type = 'derived_from' "
        "ORDER BY e.headword, r.target_headword").fetchall()


class ForwardShape(unittest.TestCase):
    def setUp(self):
        self.con = _db([(1, "ekeeke", 1, "movement (Reduplicated form of eke [2])"),
                        (2, "eke", 1, "get on board"),
                        (3, "eke", 2, "mount")])
        b = build_unified.Builder(self.con, "papakupu", None, {})
        build_unified.build_papakupu(self.con, b)

    def test_the_relation_hangs_on_the_reduplication(self):
        self.assertEqual(_relations(self.con),
                         [("ekeeke", "derived_from", "eke", "reduplication")])

    def test_the_stated_sense_picks_the_right_base_entry(self):
        # 'eke [2]' names the second sense, which is a separate papakupu row.
        target = self.con.execute(
            "SELECT target_entry_id FROM relation "
            "WHERE rel_type = 'derived_from'").fetchone()[0]
        self.assertEqual(self.con.execute(
            "SELECT source_entry_id FROM entry WHERE id = ?",
            (target,)).fetchone()[0], "3")


class InverseShape(unittest.TestCase):
    def setUp(self):
        # The base is row 1 and names a child that is only minted at row 2 —
        # the ordering an inline call could not handle.
        self.con = _db([(1, "hoko", 1,
                         "trade. In the reduplicated forms hohoko and "
                         "hokohoko, the focus is on the process."),
                        (2, "hohoko", 1, "trading"),
                        (3, "hokohoko", 1, "bartering")])
        b = build_unified.Builder(self.con, "papakupu", None, {})
        build_unified.build_papakupu(self.con, b)

    def test_both_children_point_back_at_the_base(self):
        self.assertEqual(_relations(self.con), [
            ("hohoko", "derived_from", "hoko", "reduplication"),
            ("hokohoko", "derived_from", "hoko", "reduplication"),
        ])


class Skipped(unittest.TestCase):
    def test_a_statement_about_another_word_writes_nothing(self):
        con = _db([(1, "takapau", 1,
                    "mat. The reduplicated form momoe is inherited from "
                    "a Proto Nuclear Polynesian term."),
                   (2, "momoe", 1, "sleep together")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])

    def test_an_unresolved_end_writes_nothing(self):
        # papakupu names 'take', which it does not hold as an entry. The
        # word exists in 26 other sources, but papakupu names no source, so
        # reaching across would invent a pointer it never made.
        con = _db([(1, "take", 1,
                    "cause. The reduplicated form, taketake, includes "
                    "well-foundedness.")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])

    def test_an_entry_with_no_statement_writes_nothing(self):
        con = _db([(1, "ahu", 1, "tend, foster, fashion")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])


class StatedSenseMustExist(unittest.TestCase):
    """A sense the source names but this extract does not hold is refused.

    resolve() used one fallback for two different situations. When papakupu
    states no sense number it has made no claim, and defaulting to the
    lowest sense is right. When it states '[2]' and no sense 2 exists, the
    same fallback attaches the derivation to a DIFFERENT sense of the right
    word — and 53_build_word_origin then stamps it confidence='certain'.
    That is an assertion nobody made, so the pair is dropped instead, the
    way pick_target already refuses to guess (D32).

    Nothing in the corpus reaches this today; all twelve stated senses
    exist. It is a guard against a refresh, not a fix to live data.
    """

    def test_a_stated_sense_that_exists_is_used(self):
        con = _db([(1, "ekeeke", 1, "movement (Reduplicated form of eke [2])"),
                   (2, "eke", 1, "get on board"),
                   (3, "eke", 2, "mount")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        target = con.execute(
            "SELECT target_entry_id FROM relation "
            "WHERE rel_type = 'derived_from'").fetchone()[0]
        self.assertEqual(con.execute(
            "SELECT source_entry_id FROM entry WHERE id = ?",
            (target,)).fetchone()[0], "3")

    def test_a_stated_sense_that_is_missing_drops_the_pair(self):
        # The source points at eke [2]; this extract holds only sense 1.
        # Attaching to sense 1 would be a claim the source never made.
        con = _db([(1, "ekeeke", 1, "movement (Reduplicated form of eke [2])"),
                   (2, "eke", 1, "get on board")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(_relations(con), [])

    def test_an_unstated_sense_still_falls_back_to_the_first(self):
        # No number means no claim, so the lowest sense is the right
        # default — the same one _first_sense uses elsewhere.
        con = _db([(1, "roroa", 1, "very long (Reduplicated form of roa)"),
                   (2, "roa", 2, "tall"),
                   (3, "roa", 1, "long")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        target = con.execute(
            "SELECT target_entry_id FROM relation "
            "WHERE rel_type = 'derived_from'").fetchone()[0]
        self.assertEqual(con.execute(
            "SELECT source_entry_id FROM entry WHERE id = ?",
            (target,)).fetchone()[0], "3")


class NotDuplicated(unittest.TestCase):
    def test_the_stated_sense_survives_an_inverse_statement_read_first(self):
        # nao's own row is read first and states the pair with no sense
        # number; nanao's row states it as 'nao [2]'. Keeping whichever came
        # first would lose the number and resolve to the wrong base entry.
        con = _db([(1, "nao", 1, "handle. Used in the reduplicated forms "
                                 "nanao, naonao."),
                   (2, "nanao", 1, "grope (Reduplicated form of nao [2])"),
                   (3, "nao", 2, "grasp")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        target = con.execute(
            "SELECT r.target_entry_id FROM relation r "
            "JOIN entry e ON e.id = r.entry_id "
            "WHERE e.headword = 'nanao'").fetchone()[0]
        self.assertEqual(con.execute(
            "SELECT source_entry_id FROM entry WHERE id = ?",
            (target,)).fetchone()[0], "3")

    def test_a_pair_stated_from_both_ends_is_written_once(self):
        con = _db([(1, "nao", 1, "handle. Used in the reduplicated forms "
                                 "nanao, naonao."),
                   (2, "nanao", 1, "grope (Reduplicated form of nao [1])")])
        b = build_unified.Builder(con, "papakupu", None, {})
        build_unified.build_papakupu(con, b)
        self.assertEqual(
            [r for r in _relations(con) if r[0] == "nanao"],
            [("nanao", "derived_from", "nao", "reduplication")])


if __name__ == "__main__":
    unittest.main()
