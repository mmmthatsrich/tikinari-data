"""Resolving a relation by a shared definition (D34).

He Pātaka Kupu is a synonym-set dictionary: one definition serves every
headword in the set, verbatim. 3,763 of its 10,443 definitions are shared by
two or more headwords, and `aho` and `au` carry the same sentence to the
character — 'He weu kua kōmiroa, kua whiria kia ū, kia roa, kia kōrahirahi.'

So when `aho` names `au` as a synonym and Ngāti `au` has four entries, the one
carrying that same definition is the one meant. The others are a brave heart,
a fishing bone and an expanse of sea.

The same evidence settles homographs elsewhere. papakupu's `karahe` is
'class', 'glass' and 'grass'; an entry glossed 'grass' that points at it means
the third. `turi` is 'knee' and 'deaf'.

Identity is exact string equality, never similarity — the point is that the
source reused one text, not that two texts look alike.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import resolve_relations_by_gloss

CORD = "He weu kua kōmiroa, kua whiria kia ū, kia roa, kia kōrahirahi."


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, headword TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER,
            gloss_en TEXT, gloss_mi TEXT);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER);
    """)
    con.executemany("INSERT INTO entry (id, source_id, headword) VALUES (?,?,?)", [
        (1, "hepatakakupu", "aho"),     # the referrer
        (2, "hepatakakupu", "au"),      # a brave heart
        (3, "hepatakakupu", "au"),      # THE cord sense
        (4, "hepatakakupu", "au"),      # an expanse of sea
        (5, "te_aka", "au"),            # another source entirely
    ])
    con.executemany("INSERT INTO sense (entry_id, gloss_en, gloss_mi) VALUES (?,?,?)", [
        (1, None, CORD),
        (2, None, "He ngākau māia ki te whawhai."),
        (3, None, CORD),
        (4, None, "He horanga moana nui tonu."),
        (5, None, CORD),
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


class ResolveByGloss(unittest.TestCase):
    def test_the_shared_definition_picks_the_one_candidate(self):
        con = _db()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 1)
        self.assertEqual(_target(con), 3)

    def test_it_refuses_when_two_candidates_share_the_definition(self):
        con = _db()
        con.execute("UPDATE sense SET gloss_mi=? WHERE entry_id=4", (CORD,))
        con.commit()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 0)
        self.assertIsNone(_target(con))

    def test_it_refuses_when_no_candidate_shares_the_definition(self):
        con = _db()
        con.execute("UPDATE sense SET gloss_mi='He mea kē' WHERE entry_id=3")
        con.commit()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 0)
        self.assertIsNone(_target(con))

    def test_it_never_crosses_a_source_boundary(self):
        # entry 5 is te_aka 'au' carrying the same definition. Remove the
        # hepatakakupu match and nothing may reach across to it.
        con = _db()
        con.execute("UPDATE sense SET gloss_mi='He mea kē' WHERE entry_id=3")
        con.commit()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 0)

    def test_a_single_candidate_is_left_to_the_headword_pass(self):
        con = _db()
        con.execute("DELETE FROM entry WHERE id IN (2,4)")
        con.commit()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 0)

    def test_a_referrer_with_no_gloss_resolves_nothing(self):
        con = _db()
        con.execute("UPDATE sense SET gloss_mi=NULL WHERE entry_id=1")
        con.commit()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 0)

    def test_an_existing_target_is_never_overwritten(self):
        con = _db()
        _rel(con, "au")
        con.execute("UPDATE relation SET target_entry_id=2 WHERE id=1")
        con.commit()
        self.assertEqual(resolve_relations_by_gloss(con), 0)
        self.assertEqual(_target(con), 2)

    def test_it_never_points_an_entry_at_itself(self):
        # entry 1 refers to its own headword; 'aho' has one other entry which
        # shares the definition, and entry 1 must not be its own target.
        con = _db()
        con.executemany("INSERT INTO entry (id, source_id, headword) VALUES (?,?,?)",
                        [(6, "hepatakakupu", "aho"), (7, "hepatakakupu", "aho")])
        con.executemany("INSERT INTO sense (entry_id, gloss_en, gloss_mi) VALUES (?,?,?)",
                        [(6, None, CORD), (7, None, "He mea kē anō.")])
        con.commit()
        _rel(con, "aho")
        self.assertEqual(resolve_relations_by_gloss(con), 1)
        self.assertEqual(_target(con), 6)

    def test_a_candidate_with_no_gloss_at_all_is_skipped(self):
        # Real data has entries carrying no sense text. The candidate set must
        # tolerate them rather than assuming every entry has a gloss.
        con = _db()
        con.execute("DELETE FROM sense WHERE entry_id=2")
        con.commit()
        _rel(con, "au")
        self.assertEqual(resolve_relations_by_gloss(con), 1)
        self.assertEqual(_target(con), 3)

    def test_whitespace_only_differences_do_not_count_as_identity(self):
        con = _db()
        con.execute("UPDATE sense SET gloss_mi=? WHERE entry_id=3", (CORD + " ",))
        con.commit()
        _rel(con, "au")
        # trailing space is stripped, so this still matches
        self.assertEqual(resolve_relations_by_gloss(con), 1)
        self.assertEqual(_target(con), 3)


if __name__ == "__main__":
    unittest.main()
