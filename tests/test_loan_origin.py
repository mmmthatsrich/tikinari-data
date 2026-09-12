"""Reading a loan's source language where a source states it (D38).

LOAN_ORIGIN_DESIGN §1: the corpus records that 22,832 entries are borrowed and
almost never from what. Two sources do say:

  paekupu   entry.loan_marker 'he kupu mino (reo Wīwī)'   — names the language
  papakupu  sense.gloss_en    'Eng. shirt'                — names it and the word

These are the only places in 153,543 entries where a borrowing's origin
language is stated as data, so both are parsed exactly and neither is guessed
at. A bare 'He kupu mino.' says the word is borrowed and nothing more, which is
a loan_origin row with no language rather than no row at all.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from loan_origin import parse_loan_marker, parse_papakupu_loan_gloss


class ParseLoanMarker(unittest.TestCase):
    def test_a_marker_naming_the_language(self):
        self.assertEqual(parse_loan_marker("he kupu mino (reo Wīwī)"),
                         {"source_lang": "reo Wīwī", "source_word": None,
                          "attested": True})

    def test_the_other_languages_paekupu_names(self):
        for raw, lang in (("he kupu mino (reo Hapanihi)", "reo Hapanihi"),
                          ("He kupu mino (reo Itāriana)", "reo Itāriana"),
                          ("he kupu mino (reo Hīperu)", "reo Hīperu")):
            self.assertEqual(parse_loan_marker(raw)["source_lang"], lang, raw)

    def test_a_bare_marker_states_borrowing_without_a_language(self):
        self.assertEqual(parse_loan_marker("He kupu mino."),
                         {"source_lang": None, "source_word": None,
                          "attested": True})

    def test_a_parenthesis_without_reo_is_the_source_WORD_not_a_language(self):
        # 'he kupu mino (hammer)' names what the word was borrowed FROM. The
        # language is unstated and stays unstated.
        self.assertEqual(parse_loan_marker("he kupu mino (hammer)"),
                         {"source_lang": None, "source_word": "hammer",
                          "attested": True})

    def test_html_residue_is_not_part_of_the_marker(self):
        # 'He kupu mino.&nbsp' survives in two paekupu rows.
        self.assertEqual(parse_loan_marker("He kupu mino.&nbsp"),
                         {"source_lang": None, "source_word": None,
                          "attested": True})

    def test_te_akas_marker_states_borrowing_without_a_language(self):
        self.assertEqual(parse_loan_marker("Historical Loan Word"),
                         {"source_lang": None, "source_word": None,
                          "attested": True})

    def test_something_that_is_not_a_loan_marker(self):
        self.assertIsNone(parse_loan_marker("Noun"))
        self.assertIsNone(parse_loan_marker(""))
        self.assertIsNone(parse_loan_marker(None))


class ParsePapakupuLoanGloss(unittest.TestCase):
    def test_english_marker_yields_language_and_word(self):
        self.assertEqual(parse_papakupu_loan_gloss("Eng. shirt"),
                         {"source_lang": "English", "source_word": "shirt",
                          "gloss": "shirt"})

    def test_a_leading_pos_token_is_not_the_source_word(self):
        # 'Eng. n cheque' — the 'n' is a part of speech.
        self.assertEqual(parse_papakupu_loan_gloss("Eng. n cheque")["source_word"],
                         "cheque")

    def test_a_multiword_source_word(self):
        self.assertEqual(parse_papakupu_loan_gloss("Eng. motor car")["source_word"],
                         "motor car")

    def test_the_marker_must_lead(self):
        # 'score [n.] cf. Eng.' mentions English without claiming the headword
        # is borrowed from it.
        self.assertIsNone(parse_papakupu_loan_gloss("score, cf. Eng."))

    def test_a_gloss_with_no_marker(self):
        self.assertIsNone(parse_papakupu_loan_gloss("ridge of a hill"))

    def test_empty(self):
        self.assertIsNone(parse_papakupu_loan_gloss(""))
        self.assertIsNone(parse_papakupu_loan_gloss(None))


if __name__ == "__main__":
    unittest.main()
