"""Williams headword-attached parentheticals.

`Tūāahu (less correctly tūāhu), n. A sacred place...` — the parser stripped the
headword then ran `lstrip(",.() ")`, which ate the OPENING bracket and left the
closing one stranded at the front of the definition:

    'less correctly tūāhu), n. A sacred place...'

44 senses were mangled this way. The source has 2,427 such parentheticals but
2,402 are homograph numerals — (i), (ii), (iii) — which ROMAN_RE already handles;
only the 25 non-numeral ones broke.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from williams_headword import parse_headword_note


class ParseHeadwordNote(unittest.TestCase):
    def test_a_plural_form_is_recovered(self):
        # 'wāhine' is the plural of 'wahine' — a real lexical fact that was
        # sitting mangled at the front of a definition.
        self.assertEqual(parse_headword_note("pl. wāhine"),
                         {"plural": ["wāhine"], "register": None, "note": None})

    def test_a_hedged_plural_keeps_its_hedge_as_a_note(self):
        self.assertEqual(parse_headword_note("pl. sometimes kikino"),
                         {"plural": ["kikino"], "register": None,
                          "note": "pl. sometimes kikino"})

    def test_a_register_marker_is_recognised(self):
        self.assertEqual(parse_headword_note("poetical"),
                         {"plural": [], "register": "poetical", "note": None})

    def test_a_variant_spelling_note_is_kept_as_a_note(self):
        self.assertEqual(
            parse_headword_note("less correctly tūāhu"),
            {"plural": [], "register": None, "note": "less correctly tūāhu"})

    def test_a_dialect_abbreviation_is_kept_as_a_note(self):
        self.assertEqual(parse_headword_note("Tahu."),
                         {"plural": [], "register": None, "note": "Tahu."})

    def test_a_multiword_variant_note_survives_intact(self):
        self.assertEqual(
            parse_headword_note("formerly written e ngari"),
            {"plural": [], "register": None, "note": "formerly written e ngari"})

    def test_nothing(self):
        self.assertEqual(parse_headword_note(""),
                         {"plural": [], "register": None, "note": None})
        self.assertEqual(parse_headword_note(None),
                         {"plural": [], "register": None, "note": None})


if __name__ == "__main__":
    unittest.main()
