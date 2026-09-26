"""Examples must not be inserted twice, or hung on the wrong sense.

`williams:1006503#1` carried the same sentence twice AND carried sense 3's
example. Cause: build_williams adds the examples split out of each sense's own
text, and then adds the parser's entry-level usage_examples onto the first
sense as well — so anything the parser also found landed twice, on whichever
sense happened to be first.

195 rows corpus-wide (91 williams, 104 elsewhere). Small, but introduced by the
D2 extraction overlapping the parser's own, and the wrong-sense half is worse
than the duplicate half: a reader cannot tell it is misplaced.
"""
import importlib
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from core_schema import core_db
sys.stdout.reconfigure(encoding="utf-8")

bu = importlib.import_module("50_build_unified")


def _builder():
    con = core_db()
    b = bu.Builder(con, "williams", None, {})
    eid = b.add_entry("1006503", "ahuahu", "ahuahu", "ahuahu")
    return con, b, eid


class ExampleDedupe(unittest.TestCase):
    def test_the_same_example_is_not_stored_twice_on_a_sense(self):
        con, b, eid = _builder()
        sid = b.add_sense(eid, 1, "Heap up.", None, "Heap up.")
        b.add_example(sid, eid, "He mea ahuahu nga puke.", None, None, None, 0)
        b.add_example(sid, eid, "He mea ahuahu nga puke.", None, None, None, 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM example").fetchone()[0], 1)

    def test_the_same_sentence_on_a_different_sense_is_kept(self):
        # Distinct senses may legitimately be illustrated by the same sentence;
        # only a repeat within one sense is a duplicate.
        con, b, eid = _builder()
        s1 = b.add_sense(eid, 1, "Heap up.", None, "Heap up.")
        s2 = b.add_sense(eid, 2, "Earth up crops.", None, "Earth up crops.")
        b.add_example(s1, eid, "He mea ahuahu nga puke.", None, None, None, 0)
        b.add_example(s2, eid, "He mea ahuahu nga puke.", None, None, None, 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM example").fetchone()[0], 2)

    def test_a_differing_translation_makes_it_a_different_example(self):
        con, b, eid = _builder()
        sid = b.add_sense(eid, 1, "Heap up.", None, "Heap up.")
        b.add_example(sid, eid, "Kia ahuahu.", "Heap it up.", None, None, 0)
        b.add_example(sid, eid, "Kia ahuahu.", "Pile it up.", None, None, 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM example").fetchone()[0], 2)

    def test_the_counter_reflects_what_was_actually_inserted(self):
        con, b, eid = _builder()
        sid = b.add_sense(eid, 1, "Heap up.", None, "Heap up.")
        b.add_example(sid, eid, "He mea ahuahu nga puke.", None, None, None, 0)
        b.add_example(sid, eid, "He mea ahuahu nga puke.", None, None, None, 1)
        self.assertEqual(b.counts["example"], 1)

    def test_dedupe_is_per_entry_not_global(self):
        con, b, _ = _builder()
        e1 = b.add_entry("1006601", "ahuahu", "ahuahu", "ahuahu")
        e2 = b.add_entry("1006701", "ahuahu", "ahuahu", "ahuahu")
        s1 = b.add_sense(e1, 1, "Tend.", None, "Tend.")
        s2 = b.add_sense(e2, 1, "Be diminished.", None, "Be diminished.")
        b.add_example(s1, e1, "Kaore rawa kia ahuahu.", None, None, None, 0)
        b.add_example(s2, e2, "Kaore rawa kia ahuahu.", None, None, None, 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM example").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
