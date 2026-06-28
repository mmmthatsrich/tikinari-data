"""Tests for williams_xref — the '‖' cross-ref extractor and see_also parser."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from williams_xref import extract_xrefs, parse_see_also_targets


class TestExtractXrefs(unittest.TestCase):

    def test_no_bar_returns_input_unchanged(self):
        d = "1. n. Belly. Nau i matakahi i te takapu nui."
        self.assertEqual(extract_xrefs(d), (d, []))

    def test_none_and_empty(self):
        self.assertEqual(extract_xrefs(None), ("", []))
        self.assertEqual(extract_xrefs(""), ("", []))

    def test_apu_sense_pointer_headword(self):
        # apū sense 2 — the reported bug. "‖ apa (i), 2." is one see_also target,
        # and the inner ", 2." must NOT be read as a new sense.
        d = ("1. v.i. Move or be in a flock or crowd. E apu mai nga tangata i waho nei. "
             "2. n. Company of labourers. E mahi ra te apu. ‖ apa (i), 2.")
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, ("1. v.i. Move or be in a flock or crowd. E apu mai nga "
                                 "tangata i waho nei. 2. n. Company of labourers. "
                                 "E mahi ra te apu."))
        self.assertEqual(refs, [{"type": "see_also", "target": "apa (i), 2"}])

    def test_mid_entry_bar_keeps_following_sense(self):
        # Hapū: ‖ pu belongs to sense 3; sense 4 continues after it.
        d = ("3. n. Section of a large tribe. ki te wai (T. 5). ‖ pu. "
             "4. Species of shark (prized as food).")
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, ("3. n. Section of a large tribe. ki te wai (T. 5). "
                                 "4. Species of shark (prized as food)."))
        self.assertEqual(refs, [{"type": "see_also", "target": "pu"}])

    def test_citation_at_end(self):
        clean, refs = extract_xrefs("Love charm. ‖ Wai 23.")
        self.assertEqual(clean, "Love charm.")
        self.assertEqual(refs, [{"type": "citation", "target": "Wai 23"}])

    def test_citation_with_roman_volume(self):
        d = "Ka matakite hei titiro i tona aitua (T. 175). ‖ J. vii, 120."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, "Ka matakite hei titiro i tona aitua (T. 175).")
        self.assertEqual(refs, [{"type": "citation", "target": "J. vii, 120"}])

    def test_mid_entry_citation_keeps_following_sense(self):
        d = "to call attention. ‖ J. vii, 128. 2. v.i. Make such a call."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, "to call attention. 2. v.i. Make such a call.")
        self.assertEqual(refs, [{"type": "citation", "target": "J. vii, 128"}])

    def test_citation_multiple_pages(self):
        d = "An omen of ill success. ‖ J. vii, 123, 126, 132. ‖ muhore."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, "An omen of ill success.")
        self.assertEqual(refs, [
            {"type": "citation", "target": "J. vii, 123, 126, 132"},
            {"type": "see_also", "target": "muhore"},
        ])

    def test_citation_multiple_sources(self):
        d = "Side of a weaving frame. ‖ J. vii, 129; Tr. xxxi, 627."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, "Side of a weaving frame.")
        self.assertEqual(refs, [{"type": "citation",
                                 "target": "J. vii, 129; Tr. xxxi, 627"}])

    def test_headword_with_following_derived_form(self):
        # Ngita: ‖ kita, ita ends at the first period; the derived form survives.
        d = "Fast, firm, secure. Patua te whao kia ngita. ‖ kita, ita. whakangita, v.t."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean,
                         "Fast, firm, secure. Patua te whao kia ngita. whakangita, v.t.")
        self.assertEqual(refs, [{"type": "see_also", "target": "kita, ita"}])

    def test_internal_sense_pointer_to_same_entry(self):
        d = "Perform ceremonies. ‖ 6, below. 2. Mention the name."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, "Perform ceremonies. 2. Mention the name.")
        self.assertEqual(refs, [{"type": "see_also", "target": "6, below"}])

    def test_bar_inside_parens_left_in_place(self):
        d = "Belly. (For the various senses of this word ‖ J. x, 7, etc.) 2. Bowels."
        clean, refs = extract_xrefs(d)
        self.assertEqual(clean, d)
        self.assertEqual(refs, [])

    def test_stub_entry_becomes_empty_definition(self):
        clean, refs = extract_xrefs("‖ papa (i).")
        self.assertEqual(clean, "")
        self.assertEqual(refs, [{"type": "see_also", "target": "papa (i)"}])

    def test_multiple_headword_targets_kept_as_one(self):
        clean, refs = extract_xrefs("Use charms. ‖ huhu, parahuhu, pauhu.")
        self.assertEqual(clean, "Use charms.")
        self.assertEqual(refs, [{"type": "see_also", "target": "huhu, parahuhu, pauhu"}])

    def test_example_sentence_after_bar_left_inline(self):
        # Dangling '(' = a swallowed example sentence; keep it, emit no ref.
        d = "Anana ‖ ta Tangaroa pai hoki, ano kei te wai e tawheta ana (T. 22). ‖ anā."
        clean, refs = extract_xrefs(d)
        self.assertEqual(refs, [{"type": "see_also", "target": "anā"}])
        self.assertIn("Tangaroa pai hoki", clean)  # example preserved

    def test_editorial_note_after_bar_left_inline(self):
        d = "Sense. ‖ koropatu, which White takes in above sense in W. v, 93."
        clean, refs = extract_xrefs(d)
        self.assertEqual(refs, [])
        self.assertIn("koropatu, which White takes", clean)  # note preserved

    def test_polynesian_cognate_ref_kept(self):
        # Uppercase cognate abbrev (Tahitian) is a legit see_also, not prose.
        clean, refs = extract_xrefs("Cloud. ‖ Tah, ao.")
        self.assertEqual(clean, "Cloud.")
        self.assertEqual(refs, [{"type": "see_also", "target": "Tah, ao"}])


import importlib
import sqlite3

_bu = importlib.import_module("50_build_unified")


class TestResolveWilliamsXrefs(unittest.TestCase):
    """resolve_williams_xrefs() fills relation.target_entry_id for Williams see_also
    rows, against a synthetic in-memory DB (no production data)."""

    def _db(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE entry (
                id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
                headword TEXT, headword_search TEXT);
            CREATE TABLE williams_entries (
                id INTEGER PRIMARY KEY, headword TEXT, headword_search TEXT,
                sense_number TEXT);
            CREATE TABLE relation (
                id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
                target_headword TEXT, target_entry_id INTEGER, note TEXT);
        """)
        # Two williams source rows: homographs of "ahu" (sense i and ii), and "tuaahu".
        ws = [(1, "ahu", "ahu", "i"), (2, "ahu", "ahu", "ii"), (3, "tuaahu", "tuahu", None)]
        con.executemany("INSERT INTO williams_entries VALUES (?,?,?,?)", ws)
        # Mirrored unified entries (source_entry_id = williams_entries.id).
        es = [(10, "williams", "1", "ahu", "ahu"), (11, "williams", "2", "ahu", "ahu"),
              (12, "williams", "3", "tuaahu", "tuahu")]
        con.executemany("INSERT INTO entry VALUES (?,?,?,?,?)", es)
        return con

    def _add(self, con, rel_type, target):
        con.execute("INSERT INTO relation (entry_id, rel_type, target_headword) "
                    "VALUES (?,?,?)", (12, rel_type, target))
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_resolves_simple_headword(self):
        con = self._db()
        rid = self._add(con, "see_also", "tuaahu")
        _bu.resolve_williams_xrefs(con)
        eid = con.execute("SELECT target_entry_id FROM relation WHERE id=?", (rid,)).fetchone()[0]
        self.assertEqual(eid, 12)

    def test_resolves_sense_specific_to_correct_homograph(self):
        con = self._db()
        rid = self._add(con, "see_also", "ahu (ii)")
        _bu.resolve_williams_xrefs(con)
        eid = con.execute("SELECT target_entry_id FROM relation WHERE id=?", (rid,)).fetchone()[0]
        self.assertEqual(eid, 11)   # the (ii) homograph, not (i)

    def test_multi_target_splits_into_rows(self):
        con = self._db()
        self._add(con, "see_also", "ahu (i), tuaahu")
        _bu.resolve_williams_xrefs(con)
        links = sorted(r[0] for r in con.execute(
            "SELECT target_entry_id FROM relation WHERE target_entry_id IS NOT NULL"))
        self.assertEqual(links, [10, 12])   # ahu(i)=10 updated, tuaahu=12 inserted

    def test_cognate_left_unresolved(self):
        con = self._db()
        rid = self._add(con, "see_also", "Tah, ao")
        _bu.resolve_williams_xrefs(con)
        eid = con.execute("SELECT target_entry_id FROM relation WHERE id=?", (rid,)).fetchone()[0]
        self.assertIsNone(eid)

    def test_citation_rows_untouched(self):
        con = self._db()
        rid = self._add(con, "citation", "J. vii, 120")
        _bu.resolve_williams_xrefs(con)
        eid = con.execute("SELECT target_entry_id FROM relation WHERE id=?", (rid,)).fetchone()[0]
        self.assertIsNone(eid)


class TestParseSeeAlsoTargets(unittest.TestCase):
    """parse_see_also_targets() turns a raw ‖ target string into (search_key, sense)
    tuples ready for entry-id resolution. Decoration stripped; junk left out."""

    def test_bare_headword(self):
        self.assertEqual(parse_see_also_targets("pakuhā"), [("pakuha", None)])

    def test_sense_pointer_kept_as_roman(self):
        self.assertEqual(parse_see_also_targets("hea (i)"), [("hea", "i")])

    def test_macron_and_double_vowel_collapsed(self):
        # tā -> ta ; mataaho -> mataho ; tuaahu -> tuahu (search-key normalisation)
        self.assertEqual(parse_see_also_targets("tā (iii)"), [("ta", "iii")])

    def test_trailing_number_sense_pointer_dropped(self):
        # "apa (i), 2" -> the ", 2" is a sense-of-apa pointer, not a second target.
        self.assertEqual(parse_see_also_targets("apa (i), 2"), [("apa", "i")])

    def test_multiple_headword_targets_split(self):
        self.assertEqual(parse_see_also_targets("mataaho, tiaho"),
                         [("mataho", None), ("tiaho", None)])

    def test_multiple_targets_with_sense(self):
        self.assertEqual(parse_see_also_targets("ahu (i), tuaahu"),
                         [("ahu", "i"), ("tuahu", None)])

    def test_etc_filler_dropped(self):
        self.assertEqual(parse_see_also_targets("puaha, etc"), [("puaha", None)])

    def test_internal_pointer_unresolved(self):
        # "6, below" is a relative pointer into the same entry — no headword.
        self.assertEqual(parse_see_also_targets("6, below"), [])

    def test_single_uppercase_letter_unresolved(self):
        self.assertEqual(parse_see_also_targets("F"), [])

    def test_cognate_abbrev_lead_unresolved(self):
        # "Tah, ao" = Tahitian cognate. Uppercase source abbrev lead -> skip whole.
        self.assertEqual(parse_see_also_targets("Tah, ao"), [])

    def test_empty_and_none(self):
        self.assertEqual(parse_see_also_targets(""), [])
        self.assertEqual(parse_see_also_targets(None), [])


if __name__ == "__main__":
    unittest.main()
