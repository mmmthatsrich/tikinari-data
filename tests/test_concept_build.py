"""Concept layer build tests."""
import importlib
import re
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

SCHEMA_SRC = Path(__file__).parent.parent / "scripts" / "00_init_db.py"


def concept_ddl() -> str:
    """The concept DDL block, lifted from 00_init_db so tests build the real thing."""
    text = SCHEMA_SRC.read_text(encoding="utf-8")
    m = re.search(r"(CREATE TABLE IF NOT EXISTS concept \(.*?"
                  r"idx_concept_member_lookup[^;]*;)", text, re.S)
    assert m, "concept DDL not found in 00_init_db.py"
    return m.group(1)


class Schema(unittest.TestCase):
    def test_the_three_tables_exist(self):
        con = sqlite3.connect(":memory:")
        con.executescript(concept_ddl())
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(
            names & {"concept", "concept_member", "concept_member_evidence"},
            {"concept", "concept_member", "concept_member_evidence"})

    def test_a_member_is_unique_per_concept_and_address(self):
        con = sqlite3.connect(":memory:")
        con.executescript(concept_ddl())
        con.execute("INSERT INTO concept (id, status, confidence) "
                    "VALUES (1,'proposed','probable')")
        row = ("INSERT INTO concept_member (concept_id, source_id, "
               "source_entry_id, sense_number, status, confidence) "
               "VALUES (1,'williams','1251',1,'proposed','certain')")
        con.execute(row)
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(row)


def _fixture_db():
    """A miniature corpus: the hiwi cluster's shape, in three sources."""
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (id INTEGER PRIMARY KEY, source_id TEXT,
            source_entry_id TEXT, headword TEXT, headword_search TEXT,
            part_of_speech TEXT, part_of_speech_en TEXT, locator TEXT);
        CREATE TABLE sense (id INTEGER PRIMARY KEY, entry_id INTEGER,
            sense_number INTEGER, gloss_en TEXT, gloss_mi TEXT,
            part_of_speech TEXT, part_of_speech_en TEXT);
        CREATE TABLE example (id INTEGER PRIMARY KEY, entry_id INTEGER,
            sense_id INTEGER, text_mi TEXT, citation TEXT);
        CREATE TABLE relation (id INTEGER PRIMARY KEY, entry_id INTEGER,
            rel_type TEXT, target_entry_id INTEGER);
        CREATE TABLE ETY_entry_link (id INTEGER PRIMARY KEY, entry_id INTEGER,
            cognateset_id INTEGER, sense_id INTEGER);
    """)
    con.executescript(concept_ddl())
    con.executemany(
        "INSERT INTO entry (id, source_id, source_entry_id, headword, "
        "headword_search, part_of_speech, locator) VALUES (?,?,?,?,?,?,?)", [
            (1, "williams", "1251", "Hiwi", "hiwi", None, None),
            (2, "williams", "1250", "Hiwi", "hiwi", None, None),
            # Real te_aka rows carry a 'word_id=N' locator too, the same shape
            # He Pātaka Kupu uses — this must not be treated as a grouping key
            # for te_aka; only lexeme_key's source gate prevents that.
            (3, "te_aka", "1284", "hiwi", "hiwi", "noun", "word_id=1284"),
            (4, "papakupu", "442", "hiwi", "hiwi", "Noun", None),
        ])
    con.executemany(
        "INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
        "VALUES (?,?,?,?)", [
            (10, 1, 1, "Ridge of a hill."),
            (11, 1, 2, "Line of descent."),
            (12, 2, 1, "Jerk a fishing line so as to hook the fish."),
            (13, 3, 1, "ridge (of a hill)."),
            (14, 4, 1, "ridge of a hill"),
        ])
    con.commit()
    return con


class LoadSenses(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def test_senses_are_grouped_by_headword_key(self):
        views = self.mod.load_senses(_fixture_db())
        self.assertEqual(set(views), {"hiwi"})
        self.assertEqual(len(views["hiwi"]), 5)

    def test_a_view_carries_its_stable_address(self):
        views = self.mod.load_senses(_fixture_db())
        keys = {v["member_key"] for v in views["hiwi"]}
        self.assertIn(("williams", "1251", 1), keys)

    def test_williams_senses_of_one_entry_share_a_lexeme(self):
        views = {v["member_key"]: v for v in
                 self.mod.load_senses(_fixture_db())["hiwi"]}
        self.assertEqual(views[("williams", "1251", 1)]["lexeme"],
                         views[("williams", "1251", 2)]["lexeme"])

    def test_williams_separate_entries_do_not(self):
        views = {v["member_key"]: v for v in
                 self.mod.load_senses(_fixture_db())["hiwi"]}
        self.assertNotEqual(views[("williams", "1251", 1)]["lexeme"],
                            views[("williams", "1250", 1)]["lexeme"])

    def test_a_te_aka_word_id_locator_does_not_group_like_hepatakakupu(self):
        # Real te_aka rows carry 'word_id=N' too; only hepatakakupu may group by
        # it. Without the source gate in lexeme_key, te_aka would group wrongly.
        views = {v["member_key"]: v for v in
                 self.mod.load_senses(_fixture_db())["hiwi"]}
        te_aka = views[("te_aka", "1284", 1)]
        self.assertEqual(te_aka["lexeme"][1], "entry")

    def test_the_canonical_part_of_speech_wins_over_the_raw_one(self):
        # Raw POS is not comparable across sources: te_matatiki brackets its
        # ('[adjective]'), hepatakakupu writes Maori abbreviations
        # ('ahua, ing, mahp'). A downstream block rule compares these across
        # sources, so the canonical form is the only usable one.
        con = _fixture_db()
        con.execute("UPDATE entry SET part_of_speech='[adjective]', "
                    " part_of_speech_en='Modifier' WHERE id=3")
        con.commit()
        views = {v["member_key"]: v for v in self.mod.load_senses(con)["hiwi"]}
        self.assertEqual(views[("te_aka", "1284", 1)]["pos"], "Modifier")

    def test_a_sense_level_canonical_outranks_the_entry_level_one(self):
        con = _fixture_db()
        con.execute("UPDATE entry SET part_of_speech_en='Noun' WHERE id=3")
        con.execute("UPDATE sense SET part_of_speech_en='Modifier' WHERE id=13")
        con.commit()
        views = {v["member_key"]: v for v in self.mod.load_senses(con)["hiwi"]}
        self.assertEqual(views[("te_aka", "1284", 1)]["pos"], "Modifier")


class FormConcepts(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _concepts(self, con=None):
        views = self.mod.load_senses(con or _fixture_db())
        return self.mod.form_concepts(views["hiwi"])

    def test_williams_two_entries_never_share_a_concept(self):
        # Williams files 1250 and 1251 apart: that IS Williams saying these
        # are different words, and nothing may override it here.
        for c in self._concepts():
            entries = {m["view"]["source_entry_id"] for m in c["members"]
                       if m["view"]["source_id"] == "williams"}
            self.assertLessEqual(len(entries), 1, entries)

    def test_the_ridge_sources_come_together(self):
        concepts = self._concepts()
        ridge = [c for c in concepts
                 if any(m["view"]["member_key"] == ("williams", "1251", 1)
                        for m in c["members"])]
        self.assertEqual(len(ridge), 1)
        sources = {m["view"]["source_id"] for m in ridge[0]["members"]}
        self.assertEqual(sources, {"williams", "te_aka", "papakupu"})

    def test_the_jerk_sense_stays_on_its_own(self):
        concepts = self._concepts()
        jerk = [c for c in concepts
                if any(m["view"]["member_key"] == ("williams", "1250", 1)
                       for m in c["members"])]
        self.assertEqual(len(jerk), 1)
        self.assertEqual(len(jerk[0]["members"]), 1)

    def test_every_sense_lands_in_exactly_one_concept(self):
        views = self.mod.load_senses(_fixture_db())["hiwi"]
        concepts = self.mod.form_concepts(views)
        placed = [m["view"]["member_key"] for c in concepts for m in c["members"]]
        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(set(placed), {v["member_key"] for v in views})

    def test_a_membership_records_its_evidence(self):
        concepts = self._concepts()
        attached = [m for c in concepts for m in c["members"]
                    if m["view"]["source_id"] != "williams" and m["evidence"]]
        self.assertTrue(attached)
        self.assertIn("kind", attached[0]["evidence"][0])

    def test_attachment_is_not_transitive(self):
        # A and C are blocked from each other; B is compatible with both.
        # B may join one of them, but that must never place A with C.
        con = _fixture_db()
        con.execute("INSERT INTO entry (id, source_id, source_entry_id, headword,"
                    " headword_search, part_of_speech) VALUES"
                    " (5,'taikupu','t1','hīwi','hiwi',NULL)")
        con.execute("INSERT INTO sense (id, entry_id, sense_number, gloss_en)"
                    " VALUES (15,5,1,'ridge of a hill')")
        con.commit()
        for c in self.mod.form_concepts(self.mod.load_senses(con)["hiwi"]):
            hws = {m["view"]["headword"].lower() for m in c["members"]}
            self.assertFalse({"hiwi", "hīwi"} <= hws, hws)


if __name__ == "__main__":
    unittest.main()
