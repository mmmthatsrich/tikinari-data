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
        -- delete_source_slice clears these two unguarded, so the fixture must
        -- carry them for RebuildSurvival to call the real function.
        CREATE TABLE entry_domain (id INTEGER PRIMARY KEY, entry_id INTEGER,
            domain TEXT, domain_lang TEXT);
        CREATE TABLE form (id INTEGER PRIMARY KEY, entry_id INTEGER,
            form TEXT, form_type TEXT);
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


class Persist(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _build(self, con):
        views = self.mod.load_senses(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key]))
        return self.mod.persist(con, allc)

    def test_it_writes_concepts_members_and_evidence(self):
        con = _fixture_db()
        self._build(con)
        self.assertGreater(con.execute(
            "SELECT COUNT(*) FROM concept").fetchone()[0], 0)
        self.assertEqual(con.execute(
            "SELECT COUNT(*) FROM concept_member").fetchone()[0], 5)

    def test_it_elects_a_headword_some_member_wrote(self):
        con = _fixture_db()
        self._build(con)
        for hw, in con.execute(
                "SELECT headword FROM concept WHERE headword IS NOT NULL"):
            self.assertIn(hw, ("Hiwi", "hiwi"))

    def test_running_twice_does_not_duplicate(self):
        con = _fixture_db()
        self._build(con)
        first = con.execute("SELECT COUNT(*) FROM concept_member").fetchone()[0]
        self._build(con)
        self.assertEqual(con.execute(
            "SELECT COUNT(*) FROM concept_member").fetchone()[0], first)

    def test_a_confirmed_membership_is_never_overwritten(self):
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='confirmed', "
                    "confidence='certain' WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        row = con.execute("SELECT status, confidence FROM concept_member "
                          "WHERE source_id='papakupu'").fetchone()
        self.assertEqual(row, ("confirmed", "certain"))

    def test_a_rejected_membership_is_never_revived(self):
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='rejected' "
                    "WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        self.assertEqual(con.execute(
            "SELECT status FROM concept_member WHERE source_id='papakupu'"
        ).fetchone()[0], "rejected")

    def _reject_papakupu_and_rebuild(self, con):
        self._build(con)
        con.execute("UPDATE concept_member SET status='rejected' "
                    "WHERE source_id='papakupu'")
        con.commit()
        self._build(con)

    def test_a_rejected_member_does_not_keep_its_old_concept_alive(self):
        # A rejected membership says this sense does NOT belong. Counting it
        # as a live member kept the pre-rebuild concept row alive: stale
        # elected forms, a headword_from with no entry behind it, no
        # evidence rows — and it passed the export filter, so it shipped.
        con = _fixture_db()
        self._reject_papakupu_and_rebuild(con)
        stale = con.execute(
            "SELECT c.id FROM concept c WHERE NOT EXISTS ("
            "  SELECT 1 FROM concept_member m WHERE m.concept_id = c.id "
            "   AND m.status <> 'rejected')").fetchall()
        self.assertEqual([], stale)

    def test_a_rejected_member_still_names_the_concept_it_was_kept_out_of(self):
        # The exclusion is only meaningful against a concept that exists.
        # Every rebuild mints new concept ids, so the rejected row is carried
        # onto the rebuilt concept it was excluded from rather than left
        # pointing at the dead one.
        con = _fixture_db()
        self._reject_papakupu_and_rebuild(con)
        cid = con.execute("SELECT concept_id FROM concept_member "
                          "WHERE source_id='papakupu'").fetchone()[0]
        self.assertEqual(1, con.execute(
            "SELECT COUNT(*) FROM concept WHERE id=?", (cid,)).fetchone()[0])
        self.assertEqual(
            {"williams", "te_aka"},
            {r[0] for r in con.execute(
                "SELECT source_id FROM concept_member WHERE concept_id=? "
                "  AND status <> 'rejected'", (cid,))})

    def test_a_confirmed_membership_confirms_the_rebuilt_concept(self):
        # Confirming a member is what makes the sweep able to change what
        # ships; a rebuild that reset the concept to 'proposed' would throw
        # that judgement away on the next run of the chain.
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='confirmed' "
                    "WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        self.assertEqual("confirmed", con.execute(
            "SELECT c.status FROM concept c JOIN concept_member m "
            "  ON m.concept_id = c.id WHERE m.source_id='papakupu'"
        ).fetchone()[0])

    def test_a_concept_with_nothing_judged_stays_proposed(self):
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='confirmed' "
                    "WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        self.assertEqual({"proposed"}, {r[0] for r in con.execute(
            "SELECT DISTINCT c.status FROM concept c JOIN concept_member m "
            "  ON m.concept_id = c.id "
            " WHERE m.source_id='williams' AND m.source_entry_id='1250'")})


class AllMembersRejected(unittest.TestCase):
    """Rejecting EVERY member of one grouping must not revive the judgements.

    The rebuild re-proposes any membership it does not find already judged, so
    a rejection whose row is lost comes back as a fresh 'proposed' one and the
    sweep session's work is undone in silence. A grouping whittled down to
    nothing is reachable: most concepts are single-member, and a multi-source
    one can lose its members one sweep session at a time.
    """

    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")
        self.con = _fixture_db()

    def _build(self):
        views = self.mod.load_senses(self.con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key]))
        return self.mod.persist(self.con, allc)

    def _members_of(self, concept_id):
        return [tuple(r) for r in self.con.execute(
            "SELECT source_id, source_entry_id, sense_number FROM concept_member"
            "  WHERE concept_id = ? ORDER BY source_id, source_entry_id,"
            "        sense_number", (concept_id,))]

    def _reject(self, key):
        self.con.execute(
            "UPDATE concept_member SET status='rejected' WHERE source_id=? "
            "  AND source_entry_id=? AND sense_number IS ?", key)
        self.con.commit()

    def _confirm(self, key):
        self.con.execute(
            "UPDATE concept_member SET status='confirmed' WHERE source_id=? "
            "  AND source_entry_id=? AND sense_number IS ?", key)
        self.con.commit()

    def _rows(self, keys):
        """{key: [status, ...]} — [] means the row was deleted outright."""
        return {k: [r[0] for r in self.con.execute(
            "SELECT status FROM concept_member WHERE source_id=? AND "
            "  source_entry_id=? AND sense_number IS ?", k)] for k in keys}

    def _concept_of(self, key):
        return self.con.execute(
            "SELECT concept_id FROM concept_member WHERE source_id=? AND "
            "  source_entry_id=? AND sense_number IS ?", key).fetchone()[0]

    def test_a_wholly_rejected_grouping_survives_two_more_rebuilds(self):
        self._build()
        ridge = self._concept_of(("papakupu", "442", 1))
        keys = self._members_of(ridge)
        self.assertEqual(4, len(keys))          # williams x2, te_aka, papakupu
        for key in keys:
            self._reject(key)

        self._build()
        self.assertEqual({k: ["rejected"] for k in keys}, self._rows(keys))
        # The reviewer's reproduction needed a second pass: the first rebuild
        # can leave the rows behind for the orphan sweep to take.
        self._build()
        self.assertEqual({k: ["rejected"] for k in keys}, self._rows(keys))

    def test_rejecting_a_grouping_one_member_at_a_time_across_rebuilds(self):
        self._build()
        ridge = self._concept_of(("papakupu", "442", 1))
        keys = self._members_of(ridge)
        for key in keys:
            self._reject(key)
            self._build()
        self.assertEqual({k: ["rejected"] for k in keys}, self._rows(keys))
        self._build()
        self.assertEqual({k: ["rejected"] for k in keys}, self._rows(keys))

    def test_a_rejected_single_member_concept_survives(self):
        # williams 1250 'jerk a fishing line' is alone on its key, which is
        # the shape most of the corpus's concepts have.
        self._build()
        key = ("williams", "1250", 1)
        self._reject(key)
        self._build()
        self._build()
        self.assertEqual({key: ["rejected"]}, self._rows([key]))

    def test_the_rejection_still_names_a_concept_that_exists(self):
        # A rejection is 'this sense does not belong HERE'. It needs the
        # concept it was excluded from to still be there to mean anything.
        self._build()
        ridge = self._concept_of(("papakupu", "442", 1))
        keys = self._members_of(ridge)
        for key in keys:
            self._reject(key)
        self._build()
        self._build()
        self.assertEqual({k: ["rejected"] for k in keys}, self._rows(keys))
        cids = {self._concept_of(k) for k in keys}
        self.assertEqual(1, len(cids))
        cid = cids.pop()
        self.assertEqual(1, self.con.execute(
            "SELECT COUNT(*) FROM concept WHERE id=?", (cid,)).fetchone()[0])

    def test_an_all_rejected_concept_elects_nothing(self):
        # There are no live views to elect from, and no member may be named
        # as the source of a value it did not supply.
        self._build()
        ridge = self._concept_of(("papakupu", "442", 1))
        for key in self._members_of(ridge):
            self._reject(key)
        self._build()
        cid = self._concept_of(("papakupu", "442", 1))
        self.assertEqual(
            (None, None, None, None, None, None),
            self.con.execute(
                "SELECT headword, headword_from, gloss_en, gloss_en_from, "
                "       gloss_mi, gloss_mi_from FROM concept WHERE id=?",
                (cid,)).fetchone())

    def test_the_other_concept_on_the_key_is_untouched(self):
        self._build()
        ridge = self._concept_of(("papakupu", "442", 1))
        for key in self._members_of(ridge):
            self._reject(key)
        self._build()
        jerk = self._concept_of(("williams", "1250", 1))
        self.assertNotEqual(jerk, self._concept_of(("papakupu", "442", 1)))
        self.assertEqual("Hiwi", self.con.execute(
            "SELECT headword FROM concept WHERE id=?", (jerk,)).fetchone()[0])

    def test_a_grouping_that_leaves_the_corpus_takes_its_rejection_with_it(self):
        # The safety net, exercised: the sense itself is gone from the
        # corpus, so the concept it was excluded from is gone too and the
        # exclusion is moot. Nothing may be left pointing at a dead concept.
        self._build()
        key = ("williams", "1250", 1)
        self._reject(key)
        self._build()
        self.con.execute("DELETE FROM sense WHERE entry_id=2")
        self.con.execute("DELETE FROM entry WHERE id=2")
        self.con.commit()
        self._build()
        self.assertEqual({key: []}, self._rows([key]))
        self.assertEqual([], self.con.execute(
            "SELECT id FROM concept_member WHERE concept_id NOT IN "
            "  (SELECT id FROM concept)").fetchall())

    def test_a_grouping_that_leaves_the_corpus_takes_its_confirmation_with_it(self):
        # The same defect by the other door: the cleanup loop only ever
        # looked at status == 'rejected', so a CONFIRMED row whose grouping
        # has left the corpus survived pointing at a pre-rebuild concept.
        # The orphan sweep judges liveness on any surviving member, so that
        # stale row alone kept a dead concept alive: stale elected headword,
        # a headword_from naming a member that no longer exists, and zero
        # evidence rows.
        self._build()
        key = ("williams", "1250", 1)
        self._confirm(key)
        self._build()
        self.con.execute("DELETE FROM sense WHERE entry_id=2")
        self.con.execute("DELETE FROM entry WHERE id=2")
        self.con.commit()
        self._build()
        self.assertEqual({key: []}, self._rows([key]))
        self.assertEqual([], self.con.execute(
            "SELECT id FROM concept_member WHERE concept_id NOT IN "
            "  (SELECT id FROM concept)").fetchall())
        # The acceptance invariant (test_concept_acceptance.py:91),
        # reproduced here so the zombie is caught in this fixture rather
        # than only in the whole-DB acceptance suite.
        self.assertEqual(0, self.con.execute(
            "SELECT COUNT(*) FROM concept c WHERE c.headword IS NOT NULL AND "
            " NOT EXISTS (SELECT 1 FROM concept_member cm "
            "   JOIN entry e ON e.source_id=cm.source_id "
            "    AND e.source_entry_id=cm.source_entry_id "
            "  WHERE cm.concept_id=c.id AND e.headword=c.headword)"
        ).fetchone()[0])
        self.assertEqual([], self.con.execute(
            "SELECT id FROM concept_member_evidence WHERE member_id NOT IN "
            "  (SELECT id FROM concept_member)").fetchall())


class RebuildSurvival(unittest.TestCase):
    """A membership is a judgement; a rebuild must not destroy it.

    derivation and loan_origin are pure projections and are deleted wholesale.
    concept_member is not: it holds what the sweep decided, and entry.id is
    only a cache of where that sense currently lives.
    """

    def test_the_slice_delete_nulls_the_cache_not_the_membership(self):
        # Calls the real delete_source_slice. Copying its UPDATE into the test
        # would only prove SQLite works: the guard could be deleted from
        # 50_build_unified and this would still pass.
        bu = importlib.import_module("50_build_unified")
        con = _fixture_db()
        con.execute("INSERT INTO concept (id, status, confidence) "
                    "VALUES (1,'proposed','probable')")
        con.execute("INSERT INTO concept_member (concept_id, source_id, "
                    " source_entry_id, sense_number, entry_id, sense_id, "
                    " status, confidence) "
                    " VALUES (1,'williams','1251',1,1,10,'confirmed','certain')")
        con.commit()

        deleted = bu.delete_source_slice(con, "williams")
        con.commit()

        self.assertEqual(deleted, 2)                      # both williams entries
        self.assertEqual(0, con.execute(
            "SELECT COUNT(*) FROM entry WHERE source_id='williams'").fetchone()[0])
        row = con.execute("SELECT status, entry_id, sense_id FROM concept_member "
                          "WHERE source_id='williams'").fetchone()
        self.assertEqual(row, ("confirmed", None, None))

    def test_the_slice_delete_leaves_another_sources_cache_alone(self):
        # Only the rebuilt source's cache is released; te_aka's stays resolved.
        bu = importlib.import_module("50_build_unified")
        con = _fixture_db()
        con.execute("INSERT INTO concept (id, status, confidence) "
                    "VALUES (1,'proposed','probable')")
        con.executemany(
            "INSERT INTO concept_member (concept_id, source_id, "
            " source_entry_id, sense_number, entry_id, sense_id, "
            " status, confidence) VALUES (1,?,?,?,?,?,'proposed','probable')",
            [("williams", "1251", 1, 1, 10), ("te_aka", "1284", 1, 3, 13)])
        con.commit()

        bu.delete_source_slice(con, "williams")
        con.commit()

        self.assertEqual((3, 13), con.execute(
            "SELECT entry_id, sense_id FROM concept_member "
            " WHERE source_id='te_aka'").fetchone())


if __name__ == "__main__":
    unittest.main()
