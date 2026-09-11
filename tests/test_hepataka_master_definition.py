"""He Pātaka Kupu names the entry that holds a sense's master definition (D35).

Each sense div can carry:

    <a class="master_definition" href="/word/1226">
        <i class="ficon-glyph-leaf"></i> hurori <sup></sup> (1)
    </a>

That says: the authoritative definition of THIS sense lives at word 1226,
sense 1. `turori` sense 1 carries exactly that, and its definition text is
byte-identical to `hurori` sense 1's, because it is the same definition.

14,379 such links exist across 8,836 of the 14,996 saved pages, and the parser
captured none of them. The `<sup>` is the target's homograph index, which the
word id already settles; the trailing `(N)` is the target's SENSE, which
nothing else in the corpus supplies.

The synonyms field carries the same `(N)` pointer and the parser strips it,
so a synonym that names one sense of a multi-sense word arrives naming none.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib
parse_page = importlib.import_module("05_hepataka_parse").parse_page


def _page(inner: str, div_id: str = "303") -> bytes:
    # The real pages declare charset=UTF-8; without it lxml decodes as latin-1
    # and the macrons arrive as mojibake.
    return f"""<html><head><meta charset="UTF-8"></head><body>
      <div class="center clearfix" id="{div_id}">
        <h2 class="title">turori</h2>
        <strong class="def num">1.</strong>
        <span class="description">Ka tatutatu ngā waewae.</span>
        {inner}
      </div></body></html>""".encode("utf-8")


class MasterDefinition(unittest.TestCase):
    def test_the_master_word_and_sense_are_captured(self):
        rec = parse_page(_page(
            '<a class="master_definition" href="/word/1226">'
            '<i class="ficon-glyph-leaf"></i> hurori <sup></sup> (1)</a>'), 9889)[0]
        self.assertEqual(rec["master_word_id"], 1226)
        self.assertEqual(rec["master_sense"], 1)

    def test_a_homograph_index_in_sup_is_not_the_sense(self):
        # 'māhanga 2 (1)' — sup 2 is the homograph, (1) is the sense. Two links
        # to the same word id differ only in the parenthesis.
        rec = parse_page(_page(
            '<a class="master_definition" href="/word/4836">'
            ' māhanga <sup>2</sup> (1)</a>'), 10003)[0]
        self.assertEqual(rec["master_word_id"], 4836)
        self.assertEqual(rec["master_sense"], 1)

    def test_a_link_with_no_sense_marker_still_records_the_word(self):
        rec = parse_page(_page(
            '<a class="master_definition" href="/word/757"> hei <sup>3</sup></a>'), 11)[0]
        self.assertEqual(rec["master_word_id"], 757)
        self.assertIsNone(rec["master_sense"])

    def test_a_sense_with_no_master_link_records_nothing(self):
        rec = parse_page(_page(""), 9889)[0]
        self.assertIsNone(rec["master_word_id"])
        self.assertIsNone(rec["master_sense"])

    def test_the_master_link_is_not_mistaken_for_a_synonym(self):
        rec = parse_page(_page(
            '<a class="master_definition" href="/word/1226"> hurori <sup></sup> (1)</a>'),
            9889)[0]
        self.assertEqual(rec["synonyms"], [])


class SynonymSensePointers(unittest.TestCase):
    def test_a_synonym_keeps_the_sense_it_names(self):
        rec = parse_page(_page(
            '<span class="synonyms">{hikoki (2), kōkeke}</span>'), 9889)[0]
        self.assertEqual(rec["synonyms"], ["hikoki", "kōkeke"])
        self.assertEqual(rec["synonym_senses"], [2, None])

    def test_a_synonym_with_no_pointer_names_no_sense(self):
        rec = parse_page(_page(
            '<span class="synonyms">{hirori, wherori}</span>'), 9889)[0]
        self.assertEqual(rec["synonyms"], ["hirori", "wherori"])
        self.assertEqual(rec["synonym_senses"], [None, None])

    def test_the_two_lists_stay_the_same_length(self):
        rec = parse_page(_page(
            '<span class="synonyms">{a (1), b, c (3)}</span>'), 9889)[0]
        self.assertEqual(len(rec["synonyms"]), len(rec["synonym_senses"]))


if __name__ == "__main__":
    unittest.main()
