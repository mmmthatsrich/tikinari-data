"""Wakareo record parsing — pure functions, no DB, no network."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import wakareo_records as wr

FIXTURES = Path(__file__).parent / "fixtures" / "wakareo"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TemplateSplit(unittest.TestCase):
    def test_ngata_multi_equivalent(self):
        r = wr.split_template(fx("shape_NGATA_26300.html"))
        self.assertEqual(r["headword"], "Aloofness")
        self.assertEqual(r["ref_tag"], "HMN")
        self.assertEqual(r["ref_no"], 297)
        self.assertEqual(r["pos"], "")
        self.assertEqual(r["search_scope"], "")
        self.assertIn("tū whakamatara", r["body"])

    def test_matatiki_has_pos_and_paren_scope(self):
        r = wr.split_template(fx("shape_MATATIKI_47800.html"))
        self.assertEqual(r["headword"], "Aumanga")
        self.assertEqual(r["pos"], "[noun]")
        self.assertEqual(r["ref_tag"], "TM")
        self.assertEqual(wr.parse_search_scope(r["search_scope"]), ["aumanga"])

    def test_tai_kupu_bracket_scope(self):
        r = wr.split_template(fx("shape_TAIKUPU-VAR_78035.html"))
        self.assertEqual(r["ref_tag"], "TK")
        self.assertEqual(
            wr.parse_search_scope(r["search_scope"]), ["ahua", "ahūa", "āhua"]
        )

    def test_williams_corpus_record_is_identifiable(self):
        r = wr.split_template(fx("entry_DICT1_1.html"))
        self.assertEqual(r["ref_tag"], "WWC")

    def test_entry_dict_body_excludes_breadcrumb_and_table(self):
        # entry_DICT* fixtures are full-page captures with a nav-breadcrumb
        # <HR> before the record <TABLE>, plus the real separator <HR>
        # after it. body must start at the real separator, not the
        # breadcrumb one — regression guard for that two-<HR> case.
        r = wr.split_template(fx("entry_DICT10_81048.html"))
        self.assertTrue(r["body"].startswith("<B>ahumoana</B>"))
        self.assertNotIn("<TABLE", r["body"].upper())

    def test_every_fixture_parses_and_tags(self):
        known = {"WWC", "TE", "HMN", "TM", "KKH", "HKA", "HKR", "TK", "NT", "KM", "CL"}
        for p in sorted(FIXTURES.glob("*.html")):
            with self.subTest(fixture=p.name):
                r = wr.split_template(p.read_text(encoding="utf-8"))
                self.assertIsNotNone(r, f"{p.name} did not parse")
                self.assertIn(r["ref_tag"], known)
                self.assertTrue(r["headword"])

    def test_no_record_returns_none(self):
        self.assertIsNone(wr.split_template("<html><body>nothing</body></html>"))

    def test_empty_scope_is_empty_list(self):
        self.assertEqual(wr.parse_search_scope(""), [])


class BodyParsers(unittest.TestCase):
    def test_ngata_splits_equivalents_and_example_pair(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertEqual(r["source_id"], "ngata")
        self.assertEqual(r["headword"], "Aloofness")
        self.assertEqual(r["equivalents"], ["tū whakamatara", "tūrangahapa"])
        self.assertEqual(
            r["example_en"], "Her aloofness separated her from the others."
        )
        self.assertEqual(
            r["example_mi"], "Na tōna tū whakamatara kē a ia i wehe atu i ētahi."
        )

    def test_ngata_single_equivalent_with_stray_close_tag(self):
        # fixture 26240 body starts with a stray "</B>" before the equivalent
        r = wr.parse_record(fx("shape_NGATA_26240.html"))
        self.assertEqual(r["equivalents"], ["ohorere"])
        self.assertEqual(r["example_en"], "She jumped up in alarm.")

    def test_kimikupu_no_example_leaves_pair_none(self):
        r = wr.parse_record(fx("shape_KIMIKUPU_52800.html"))
        self.assertEqual(r["source_id"], "kimikupu_hou")
        self.assertEqual(r["equivalents"], ["pukahu"])
        self.assertIsNone(r["qualifier"])
        self.assertIsNone(r["example_en"])
        self.assertIsNone(r["example_mi"])

    def test_kimikupu_qualifier_is_not_mistaken_for_equivalents(self):
        # Body is `View, argument<BR><B>haurite</B>`. Taking the first <BR>
        # segment would yield ['View', 'argument'] — the equivalent is haurite.
        r = wr.parse_record(fx("entry_DICT5_52724.html"))
        self.assertEqual(r["source_id"], "kimikupu_hou")
        self.assertEqual(r["equivalents"], ["haurite"])
        self.assertEqual(r["qualifier"], "View, argument")

    def test_ngata_has_no_qualifier(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertIsNone(r["qualifier"])

    def test_matatiki_gloss_derivation_and_williams_refs(self):
        r = wr.parse_record(fx("shape_MATATIKI_47800.html"))
        self.assertEqual(r["source_id"], "te_matatiki")
        self.assertEqual(r["gloss_en"], "Vent")
        self.assertIn("hollowed-out space", r["derivation"])
        self.assertEqual(r["williams_refs"], [22])

    def test_tai_kupu_variants(self):
        r = wr.parse_record(fx("shape_TAIKUPU-VAR_78035.html"))
        self.assertEqual(r["source_id"], "tai_kupu_variants")
        self.assertEqual(r["search_scope"], ["ahua", "ahūa", "āhua"])
        self.assertTrue(r["gloss_en"])

    def test_williams_corpus_is_discarded(self):
        self.assertIsNone(wr.parse_record(fx("entry_DICT1_1.html")))

    def test_every_non_williams_fixture_yields_a_source_id(self):
        for p in sorted(FIXTURES.glob("entry_DICT*.html")):
            if p.name == "entry_DICT1_1.html":
                continue
            with self.subTest(fixture=p.name):
                r = wr.parse_record(p.read_text(encoding="utf-8"))
                self.assertIsNotNone(r)
                self.assertIn(r["source_id"], set(wr.TAG_TO_SOURCE.values()))
                if r["source_id"] in wr.EN_MI_SOURCE_IDS:
                    self.assertIsInstance(r["equivalents"], list)
                else:
                    self.assertIsInstance(r["gloss_en"], str)


if __name__ == "__main__":
    unittest.main()
