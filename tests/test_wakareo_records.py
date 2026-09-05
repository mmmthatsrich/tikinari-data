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


if __name__ == "__main__":
    unittest.main()
