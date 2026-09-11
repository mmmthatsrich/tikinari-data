"""Williams see_also must not guess between homographs (D32).

`Hoatu` carries the cross-reference `‖ ho`. Williams has two entries on that
key:

    williams:1255  'Hō'   Put out the lips, pout / Droop / Shout
    williams:1256  'Ho'   A verb used only in the compound forms, hoake,
                          hoatu, homai, q.v

1256 is the base of hoatu and the source says so outright. The resolver took
`cands[0]` and linked to 1255, then overwrote the target spelling with 'Hō'.

Two rules fix it. Williams lower-cases a cross-reference target but keeps its
macrons, so an exact spelling match is decisive: `ho` means `Ho`, not `Hō`.
Where spelling still leaves several, the link is not made — the same policy
resolve_within_source_relations states, that choosing one would be a guess
dressed as a fact.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from williams_xref import parse_see_also_targets, see_also_spellings, pick_target


class SeeAlsoSpellings(unittest.TestCase):
    def test_it_keeps_the_target_as_written(self):
        self.assertEqual(see_also_spellings("māhaki"),
                         [("mahaki", None, "māhaki")])

    def test_it_keeps_the_roman_sense_and_the_spelling(self):
        self.assertEqual(see_also_spellings("hea (i)"), [("hea", "i", "hea")])

    def test_it_splits_multiple_targets_keeping_each_spelling(self):
        self.assertEqual(see_also_spellings("mataaho, tiaho"),
                         [("mataho", None, "mataaho"), ("tiaho", None, "tiaho")])

    def test_parse_see_also_targets_still_returns_pairs(self):
        # The existing two-field contract is unchanged.
        self.assertEqual(parse_see_also_targets("apa (i), 2"), [("apa", "i")])
        self.assertEqual(parse_see_also_targets("Tah, ao"), [])


class PickTarget(unittest.TestCase):
    # (entry_id, roman_sense, display_headword)
    HO = [(1255, None, "Hō"), (1256, None, "Ho")]

    def test_a_single_candidate_is_taken(self):
        self.assertEqual(pick_target([(7, None, "Pakuhā")], None, "pakuhā"),
                         (7, "Pakuhā"))

    def test_the_roman_sense_wins_when_it_matches(self):
        cands = [(1, "i", "Apa"), (2, "ii", "Apa")]
        self.assertEqual(pick_target(cands, "ii", "apa"), (2, "Apa"))

    def test_an_exact_spelling_decides_between_homographs(self):
        # The real hoatu -> ho case.
        self.assertEqual(pick_target(self.HO, None, "ho"), (1256, "Ho"))

    def test_the_macronised_target_picks_the_macronised_entry(self):
        self.assertEqual(pick_target(self.HO, None, "hō"), (1255, "Hō"))

    def test_it_refuses_to_guess_when_spelling_does_not_decide(self):
        cands = [(1, None, "Ana"), (2, None, "Ana"), (3, None, "Āna")]
        self.assertIsNone(pick_target(cands, None, "ana"))

    def test_no_candidates_is_no_match(self):
        self.assertIsNone(pick_target([], None, "kahore"))

    def test_case_is_ignored_but_macrons_are_not(self):
        cands = [(1, None, "Kāhu"), (2, None, "Kahu")]
        self.assertEqual(pick_target(cands, None, "kahu"), (2, "Kahu"))


if __name__ == "__main__":
    unittest.main()
