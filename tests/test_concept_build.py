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


def _fixture_index(con):
    """A GlossIndex over the fixture's own glosses, as 54 builds one."""
    mod = importlib.import_module("concept_evidence")
    return mod.GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))


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

    def test_a_macron_difference_inside_ngata_is_a_different_lexeme(self):
        """The bug lives at this call site, not inside lexeme_key.

        lexeme_key never normalised macrons away — load_senses handed it
        `headword_search`, the column that already had. So ngata's 'manawa'
        (heart) and 'mānawa' (mangrove) arrived indistinguishable and seeded
        as one lexeme: a wrong merge, inside a single source, invisible to
        every cross-source rule. Testing lexeme_key directly cannot catch
        this — pass it the two spellings and it separates them correctly.
        """
        con = _fixture_db()
        con.executemany(
            "INSERT INTO entry (id, source_id, source_entry_id, headword, "
            "headword_search, part_of_speech, locator) VALUES (?,?,?,?,?,?,?)",
            [(90, "ngata", "WR-90", "manawa", "manawa", None, None),
             (91, "ngata", "WR-91", "mānawa", "manawa", None, None)])
        con.executemany(
            "INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
            "VALUES (?,?,?,?)",
            [(90, 90, 1, "heart"), (91, 91, 1, "mangrove")])
        con.commit()

        views = {v["source_entry_id"]: v
                 for v in self.mod.load_senses(con)["manawa"]}
        self.assertNotEqual(views["WR-90"]["lexeme"], views["WR-91"]["lexeme"],
                            "manawa and mānawa seeded as one lexeme")

    def test_identical_ngata_spellings_still_share_a_lexeme(self):
        # The grouping this seeding exists for must survive: ngata's 14
        # 'hoatu' rows are one word seen from 13 English lemmas.
        con = _fixture_db()
        con.executemany(
            "INSERT INTO entry (id, source_id, source_entry_id, headword, "
            "headword_search, part_of_speech, locator) VALUES (?,?,?,?,?,?,?)",
            [(92, "ngata", "WR-92", "hoatu", "hoatu", None, None),
             (93, "ngata", "WR-93", "hoatu", "hoatu", None, None)])
        con.executemany(
            "INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
            "VALUES (?,?,?,?)",
            [(92, 92, 1, "give"), (93, 93, 1, "hand over")])
        con.commit()

        views = {v["source_entry_id"]: v
                 for v in self.mod.load_senses(con)["hoatu"]}
        self.assertEqual(views["WR-92"]["lexeme"], views["WR-93"]["lexeme"])

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
        con = con or _fixture_db()
        views = self.mod.load_senses(con)
        return self.mod.form_concepts(views["hiwi"], _fixture_index(con))

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
        con = _fixture_db()
        views = self.mod.load_senses(con)["hiwi"]
        concepts = self.mod.form_concepts(views, _fixture_index(con))
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
        for c in self.mod.form_concepts(self.mod.load_senses(con)["hiwi"],
                                         _fixture_index(con)):
            hws = {m["view"]["headword"].lower() for m in c["members"]}
            self.assertFalse({"hiwi", "hīwi"} <= hws, hws)


class ConfidenceIsScoredAgainstFinalMembership(unittest.TestCase):
    """A member's confidence must not depend on the order seeds arrive.

    Found judging the 'ikarangi' cluster: te_aka 'galaxy.' and te_matatiki
    'Galaxy' score coverage 1.00 against each other — unambiguous evidence —
    yet te_aka was tiered uncertain. Seeds are processed sorted, so te_aka
    attached when only paekupu was present, scored weak against paekupu's
    40-word encyclopaedic definition, and never got credit when te_matatiki
    arrived afterwards. Its confidence was frozen against whoever happened to
    be there, not against the concept it ended up in.

    No threshold tuning can fix that: the member was scored against the wrong
    partner.
    """

    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")
        self.ce = importlib.import_module("concept_evidence")

    def _fixture(self):
        con = _fixture_db()
        # Sources are seeded in sorted order, so 'aaa' founds the concept.
        # aaa's gloss is long, so anything matching it scores low coverage;
        # 'wide' is made common so the distinctiveness axis cannot rescue it
        # either. bbb and ccc are terse and identical to each other.
        con.executemany(
            "INSERT INTO entry (id, source_id, source_entry_id, headword, "
            "headword_search, part_of_speech, locator) VALUES (?,?,?,?,?,?,?)",
            [(70, "aaa", "1", "kupu", "kupu", None, None),
             (71, "bbb", "1", "kupu", "kupu", None, None),
             (72, "ccc", "1", "kupu", "kupu", None, None)])
        con.executemany(
            "INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
            "VALUES (?,?,?,?)",
            [(70, 70, 1, "a wide assembly of many distant things gathered "
                         "together across great space and counted slowly"),
             (71, 71, 1, "wide."),
             (72, 72, 1, "Wide")])
        # Make 'wide' common enough that only coverage can rescue a pair.
        con.executemany(
            "INSERT INTO entry (id, source_id, source_entry_id, headword, "
            "headword_search) VALUES (?,?,?,?,?)",
            [(800 + i, "filler", f"f{i}", f"kupu{i}", f"kupu{i}")
             for i in range(30)])
        con.executemany(
            "INSERT INTO sense (id, entry_id, sense_number, gloss_en) "
            "VALUES (?,?,?,?)",
            [(800 + i, 800 + i, 1, "wide open spaces") for i in range(30)])
        con.commit()
        return con

    def test_the_late_arrival_lifts_the_member_that_joined_before_it(self):
        con = self._fixture()
        index = _fixture_index(con)
        concepts = self.mod.form_concepts(
            self.mod.load_senses(con)["kupu"], index)
        big = max(concepts, key=lambda c: len(c["members"]))
        by_src = {m["view"]["source_id"]: m for m in big["members"]}
        self.assertEqual({"aaa", "bbb", "ccc"}, set(by_src),
                         "fixture did not form the three-source concept")
        # bbb and ccc are 'wide.' and 'Wide' — coverage 1.00 between them.
        self.assertEqual("probable", by_src["bbb"]["confidence"],
                         "bbb was scored against aaa alone and never "
                         "re-scored once ccc joined")

    def test_rescoring_never_lowers_a_membership(self):
        """Monotone by design, and the corpus insisted on it.

        A founding seed carries no evidence — nothing was there to compare it
        to — so scoring it against the members that later joined demoted it,
        and min() over members sank the whole concept. Measured: allowing
        re-scoring to lower took the app from 90,187 concepts to 74,409, a
        17.5% fall, for memberships nobody had judged wrong. Members joining
        adds evidence; it cannot unmake the evidence that justified an
        attachment in the first place.
        """
        con = self._fixture()
        index = _fixture_index(con)
        concepts = self.mod.form_concepts(
            self.mod.load_senses(con)["kupu"], index)
        big = max(concepts, key=lambda c: len(c["members"]))
        by_src = {m["view"]["source_id"]: m for m in big["members"]}
        # aaa founds the concept and its long gloss matches nothing well.
        self.assertEqual("certain", by_src["aaa"]["confidence"],
                         "the founding seed was demoted by re-scoring")

    def test_every_member_is_scored_against_every_other_source(self):
        con = self._fixture()
        index = _fixture_index(con)
        concepts = self.mod.form_concepts(
            self.mod.load_senses(con)["kupu"], index)
        big = max(concepts, key=lambda c: len(c["members"]))
        for m in big["members"]:
            others = {o["view"]["source_id"] for o in big["members"]
                      if o["view"]["source_id"] != m["view"]["source_id"]}
            got = {d for e in m["evidence"] for d in [e["detail"]]}
            self.assertTrue(
                got, f"{m['view']['source_id']} carries no evidence at all "
                     f"despite sharing a concept with {sorted(others)}")


class Persist(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("54_build_concepts")

    def _build(self, con):
        views = self.mod.load_senses(con)
        index = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], index))
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
        """The JUDGEMENT survives a rebuild. Confidence deliberately does not.

        This test used to assert the confidence column survived too, by
        setting it to 'certain' by hand — a value no build produces for
        papakupu, whose seed confidence is 'probable' — and checking the
        artificial value came back. That pinned the bug rather than the
        contract: status is the human's and must never be touched, while
        confidence is derived from evidence rows that this same rebuild
        rewrites, so freezing it left a scalar agreeing with neither the
        current evidence nor any preserved history. See the sibling
        test_a_judged_membership_still_gets_a_fresh_confidence.
        """
        con = _fixture_db()
        self._build(con)
        con.execute("UPDATE concept_member SET status='confirmed' "
                    "WHERE source_id='papakupu'")
        con.commit()
        self._build(con)
        status = con.execute("SELECT status FROM concept_member "
                             "WHERE source_id='papakupu'").fetchone()[0]
        self.assertEqual("confirmed", status)

    def test_a_judged_membership_still_gets_a_fresh_confidence(self):
        """status is the human's; confidence is the machine's.

        persist() refreshes a judged member's evidence rows but used to leave
        its confidence column alone, so a row judged under one rule kept that
        rule's confidence for ever while its own evidence said otherwise.
        That matters most where it is least visible: the re-tuning mechanism
        in the gloss-evidence spec §6 fits thresholds by pairing a judgement
        with its measurements, and the judged rows ARE the labels.
        """
        con = _fixture_db()
        views = self.mod.load_senses(con)
        idx = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], idx))
        self.mod.persist(con, allc)

        key = ("williams", "1251", 1)
        con.execute(
            "UPDATE concept_member SET status='confirmed', "
            "  confidence='uncertain' WHERE source_id=? AND "
            "  source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        allc = []
        for key2 in sorted(views):
            allc.extend(self.mod.form_concepts(views[key2], idx))
        self.mod.persist(con, allc)

        status, conf = con.execute(
            "SELECT status, confidence FROM concept_member WHERE source_id=? "
            "  AND source_entry_id=? AND sense_number IS ?", key).fetchone()
        self.assertEqual("confirmed", status, "the judgement was lost")
        self.assertNotEqual("uncertain", conf,
                            "confidence was left at the value it was judged "
                            "with instead of being re-derived")

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

    def test_it_stores_both_gloss_measurements(self):
        # Stored so a later re-tune is a re-tier, not a recomputation of the
        # whole corpus. See the spec, §6.
        con = _fixture_db()
        views = self.mod.load_senses(con)
        idx = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], idx))
        self.mod.persist(con, allc)
        rows = con.execute(
            "SELECT coverage, distinctiveness FROM concept_member_evidence "
            " WHERE kind LIKE 'gloss_overlap%'").fetchall()
        self.assertTrue(rows, "no gloss evidence in the fixture")
        for coverage, distinct in rows:
            self.assertIsNotNone(coverage)
            self.assertIsNotNone(distinct)
            self.assertGreaterEqual(coverage, 0.0)
            self.assertLessEqual(coverage, 1.0)

    def test_a_non_gloss_kind_stores_no_measurements(self):
        con = _fixture_db()
        # The fixture alone yields only gloss_overlap evidence, so this test
        # needs a non-gloss row to have anything to assert against. Give the
        # williams (sense 10) and te_aka (sense 13) "ridge" senses — already
        # in the same concept via gloss_overlap — an identical example
        # sentence, which yields a shared_example row. Inserted on this
        # test's own connection only, so no other test's fixture or expected
        # counts move.
        example = "Kei te hiwi ia e noho ana i te taha o te awa nui atu."
        con.executemany(
            "INSERT INTO example (entry_id, sense_id, text_mi) "
            " VALUES (?, ?, ?)", [(1, 10, example), (3, 13, example)])
        con.commit()
        views = self.mod.load_senses(con)
        idx = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], idx))
        self.mod.persist(con, allc)
        rows = con.execute(
            "SELECT coverage, distinctiveness FROM concept_member_evidence "
            " WHERE kind NOT LIKE 'gloss_overlap%'").fetchall()
        self.assertTrue(rows, "no non-gloss evidence in the fixture")
        for coverage, distinct in rows:
            self.assertIsNone(coverage)
            self.assertIsNone(distinct)


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
        index = _fixture_index(self.con)
        allc = []
        for key in sorted(views):
            allc.extend(self.mod.form_concepts(views[key], index))
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
        # The acceptance invariant (test_concept_acceptance.py),
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

    # -- the premature-54 window: delete_source_slice() has run, the source's
    # re-import has not, and 54 runs anyway (an interrupted import, or
    # 59_rebuild_derived.py landing between the two). --------------------

    def _run_54(self, con, mod):
        views = mod.load_senses(con)
        index = _fixture_index(con)
        allc = []
        for key in sorted(views):
            allc.extend(mod.form_concepts(views[key], index))
        return mod.persist(con, allc)

    def test_the_window_preserves_a_confirmation(self):
        # A source with zero entries is not evidence its senses left the
        # corpus -- it is evidence this build ran mid-rebuild. The
        # confirmation must survive a 54 run in that window.
        bu = importlib.import_module("50_build_unified")
        mod = importlib.import_module("54_build_concepts")
        con = _fixture_db()
        self._run_54(con, mod)
        key = ("williams", "1251", 1)
        con.execute(
            "UPDATE concept_member SET status='confirmed' WHERE source_id=? "
            " AND source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        bu.delete_source_slice(con, "williams")
        con.commit()

        self._run_54(con, mod)          # the premature 54

        row = con.execute(
            "SELECT status FROM concept_member WHERE source_id=? AND "
            " source_entry_id=? AND sense_number IS ?", key).fetchone()
        self.assertEqual(("confirmed",), row)

    def test_the_window_preserves_a_rejection(self):
        # Same shape, a rejected row. This one fails against the code that
        # predates this guard AND against the code 9553fae shipped: the
        # cleanup loop has never checked whether a judged key's source was
        # still live, only whether this build re-proposed the address.
        bu = importlib.import_module("50_build_unified")
        mod = importlib.import_module("54_build_concepts")
        con = _fixture_db()
        self._run_54(con, mod)
        key = ("williams", "1251", 1)
        con.execute(
            "UPDATE concept_member SET status='rejected' WHERE source_id=? "
            " AND source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        bu.delete_source_slice(con, "williams")
        con.commit()

        self._run_54(con, mod)          # the premature 54

        row = con.execute(
            "SELECT status FROM concept_member WHERE source_id=? AND "
            " source_entry_id=? AND sense_number IS ?", key).fetchone()
        self.assertEqual(("rejected",), row)

    def test_reimport_reresolves_the_preserved_judgement(self):
        # After the window closes and the source's rows come back, the
        # judgement must re-resolve onto a real concept with its entry_id/
        # sense_id cache pointed at the restored rows, not left NULL.
        bu = importlib.import_module("50_build_unified")
        mod = importlib.import_module("54_build_concepts")
        con = _fixture_db()
        self._run_54(con, mod)
        key = ("williams", "1251", 1)
        con.execute(
            "UPDATE concept_member SET status='confirmed' WHERE source_id=? "
            " AND source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        # Snapshot williams' rows before the delete so they can be restored
        # -- this stands in for the source's re-import.
        entry_rows = con.execute(
            "SELECT id, source_id, source_entry_id, headword, "
            " headword_search, part_of_speech, part_of_speech_en, locator "
            " FROM entry WHERE source_id='williams'").fetchall()
        sense_rows = con.execute(
            "SELECT id, entry_id, sense_number, gloss_en, gloss_mi, "
            " part_of_speech, part_of_speech_en FROM sense WHERE entry_id IN "
            " (SELECT id FROM entry WHERE source_id='williams')").fetchall()

        bu.delete_source_slice(con, "williams")
        con.commit()
        self._run_54(con, mod)          # the premature 54

        con.executemany(
            "INSERT INTO entry (id, source_id, source_entry_id, headword, "
            " headword_search, part_of_speech, part_of_speech_en, locator) "
            " VALUES (?,?,?,?,?,?,?,?)", entry_rows)
        con.executemany(
            "INSERT INTO sense (id, entry_id, sense_number, gloss_en, "
            " gloss_mi, part_of_speech, part_of_speech_en) "
            " VALUES (?,?,?,?,?,?,?)", sense_rows)
        con.commit()

        self._run_54(con, mod)          # the re-import's rebuild

        concept_id, status, entry_id, sense_id = con.execute(
            "SELECT concept_id, status, entry_id, sense_id FROM "
            " concept_member WHERE source_id=? AND source_entry_id=? "
            " AND sense_number IS ?", key).fetchone()
        self.assertEqual("confirmed", status)
        self.assertIsNotNone(entry_id)
        self.assertIsNotNone(sense_id)
        self.assertEqual(1, con.execute(
            "SELECT COUNT(*) FROM concept WHERE id=?",
            (concept_id,)).fetchone()[0])

    def test_a_source_with_entries_but_no_senses_keeps_its_judged_row(self):
        # E1 — a source builder that emits entries but drops every sense.
        # load_senses() JOINs sense to entry, so a senseless source proposes
        # nothing at all this build; its entry rows are still there, and a
        # guard keyed on "does entry have rows for this source" reads that as
        # live and destroys the judgement anyway.
        mod = importlib.import_module("54_build_concepts")
        con = _fixture_db()
        self._run_54(con, mod)
        key = ("papakupu", "442", 1)
        con.execute(
            "UPDATE concept_member SET status='confirmed' WHERE source_id=? "
            " AND source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        con.execute(
            "DELETE FROM sense WHERE entry_id IN "
            " (SELECT id FROM entry WHERE source_id='papakupu')")
        con.commit()

        self._run_54(con, mod)

        row = con.execute(
            "SELECT status FROM concept_member WHERE source_id=? AND "
            " source_entry_id=? AND sense_number IS ?", key).fetchone()
        self.assertEqual(("confirmed",), row)

    def test_a_source_with_entries_but_null_headword_search_keeps_its_judged_row(self):
        # E2 — a source builder that stops populating headword_search.
        # Entries and senses both still exist, but load_senses()'s query
        # requires headword_search IS NOT NULL, so this source proposes
        # nothing either -- same failure mode as E1, a different column.
        # This is the brief's own named trigger: "a source builder that
        # emits nothing" is reachable through this door.
        mod = importlib.import_module("54_build_concepts")
        con = _fixture_db()
        self._run_54(con, mod)
        key = ("papakupu", "442", 1)
        con.execute(
            "UPDATE concept_member SET status='confirmed' WHERE source_id=? "
            " AND source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        con.execute(
            "UPDATE entry SET headword_search=NULL WHERE source_id='papakupu'")
        con.commit()

        self._run_54(con, mod)

        row = con.execute(
            "SELECT status FROM concept_member WHERE source_id=? AND "
            " source_entry_id=? AND sense_number IS ?", key).fetchone()
        self.assertEqual(("confirmed",), row)

    def test_a_permanently_retired_source_keeps_its_judged_row_forever(self):
        # RECORDED TRADE, not a bug -- see the comment above the discard
        # loop in persist(). 54 cannot tell "this build proposed nothing for
        # this source because the import is mid-flight", "...because its
        # builder emitted no usable senses", and "...because the source is
        # gone for good" apart: all three look identical at build time. The
        # guard that saves the first two therefore also protects a genuine
        # permanent retirement, and this is the cost: a retired source's
        # judged row, and the concept it keeps alive, now survive every
        # rebuild for as long as the source stays absent. Undoing this needs
        # a deliberate cleanup pass; nothing in 54 can decide it on its own.
        bu = importlib.import_module("50_build_unified")
        mod = importlib.import_module("54_build_concepts")
        con = _fixture_db()
        self._run_54(con, mod)
        key = ("williams", "1251", 1)
        con.execute(
            "UPDATE concept_member SET status='confirmed' WHERE source_id=? "
            " AND source_entry_id=? AND sense_number IS ?", key)
        con.commit()

        bu.delete_source_slice(con, "williams")
        con.commit()

        self._run_54(con, mod)
        self._run_54(con, mod)          # a second rebuild; still never re-imported

        concept_id, status = con.execute(
            "SELECT concept_id, status FROM concept_member WHERE "
            " source_id=? AND source_entry_id=? AND sense_number IS ?",
            key).fetchone()
        self.assertEqual("confirmed", status)
        self.assertEqual(1, con.execute(
            "SELECT COUNT(*) FROM concept WHERE id=?",
            (concept_id,)).fetchone()[0])

        # The trade, pinned properly: it is not enough that the row and its
        # concept survive -- a half-fix that nulled the carcass's elected
        # forms would still pass the two assertions above. The recorded cost
        # (see the comment above the discard loop in persist()) is that the
        # carcass keeps its STALE elected headword and ships through
        # filter_concepts() alongside the live concept for the same word.
        self.assertIsNotNone(con.execute(
            "SELECT headword FROM concept WHERE id=?",
            (concept_id,)).fetchone()[0])
        # ... which is exactly what trips the acceptance invariant at
        # tests/test_concept_acceptance.py
        # (test_an_elected_headword_was_written_by_a_member), reproduced here
        # fixture-scoped the way
        # test_a_grouping_that_leaves_the_corpus_takes_its_confirmation_with_it
        # already does. This assertion is the recorded cost, not desired
        # behaviour: that acceptance test going red against the real DB is
        # the signal the deliberate cleanup pass is due.
        self.assertGreater(con.execute(
            "SELECT COUNT(*) FROM concept c WHERE c.headword IS NOT NULL AND "
            " NOT EXISTS (SELECT 1 FROM concept_member cm "
            "   JOIN entry e ON e.source_id=cm.source_id "
            "    AND e.source_entry_id=cm.source_entry_id "
            "  WHERE cm.concept_id=c.id AND e.headword=c.headword)"
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
