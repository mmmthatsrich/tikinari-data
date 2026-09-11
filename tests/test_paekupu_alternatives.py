"""Paekupu's `alternative_words` are not alternative spellings.

All 11,875 went into `form` as alt_spelling, which is ~90% of every form row in
the corpus, so the app's "this word has variants" signal was almost entirely
false. The field actually holds two things:

    "ngawhere - break up, crumble"   the coinage's component and its meaning
    "aroaro", "papamua"              other terms for the same concept

The dashed ones are the same shape as Te Matatiki's bracket derivations, already
routed to cross_ref relations with the gloss in the note. The plain ones are
synonyms: `ahanoa` and `tūhanga` list each other and are both glossed 'object
(computing)'.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from paekupu_alternatives import parse_alternative


class ParseAlternative(unittest.TestCase):
    def test_a_dashed_entry_is_a_component_and_its_gloss(self):
        self.assertEqual(
            parse_alternative("ngawhere - break up, crumble"),
            {"target": "ngawhere", "rel_type": "cross_ref",
             "note": "ngawhere - break up, crumble"})

    def test_a_plain_entry_is_a_synonym(self):
        self.assertEqual(parse_alternative("aroaro"),
                         {"target": "aroaro", "rel_type": "synonym", "note": None})

    def test_a_qualifier_is_stripped_from_the_target_but_kept_in_the_note(self):
        # 'hāpara (hāparapara)' — the bracket is a variant of the component, so
        # the target is the bare word and nothing is lost from the record.
        self.assertEqual(
            parse_alternative("hāpara (hāparapara) - surgery, operation"),
            {"target": "hāpara", "rel_type": "cross_ref",
             "note": "hāpara (hāparapara) - surgery, operation"})

    def test_a_loanword_marker_is_treated_the_same_way(self):
        self.assertEqual(
            parse_alternative("Poa (kupu mino) - Boer"),
            {"target": "Poa", "rel_type": "cross_ref",
             "note": "Poa (kupu mino) - Boer"})

    def test_a_multiword_component_keeps_its_words(self):
        self.assertEqual(
            parse_alternative("ā-kākā - in the manner of a parrot"),
            {"target": "ā-kākā", "rel_type": "cross_ref",
             "note": "ā-kākā - in the manner of a parrot"})

    def test_a_multiword_synonym_keeps_its_words(self):
        self.assertEqual(parse_alternative("tūhanga mānu"),
                         {"target": "tūhanga mānu", "rel_type": "synonym",
                          "note": None})

    def test_a_hyphenated_word_is_not_mistaken_for_a_dashed_gloss(self):
        # The separator is ' - ' with spaces; 'ā-tau' and 'ā-kākā' are single
        # words and must not be split on their hyphen.
        self.assertEqual(parse_alternative("ā-tau"),
                         {"target": "ā-tau", "rel_type": "synonym", "note": None})

    def test_only_the_first_separator_splits(self):
        self.assertEqual(
            parse_alternative("wete - to release - set free"),
            {"target": "wete", "rel_type": "cross_ref",
             "note": "wete - to release - set free"})

    def test_nothing(self):
        self.assertIsNone(parse_alternative(""))
        self.assertIsNone(parse_alternative(None))
        self.assertIsNone(parse_alternative("   "))
        self.assertIsNone(parse_alternative(" - just a gloss"))


class LoanAnnotations(unittest.TestCase):
    """'he kupu mino' is 'it is a loan word' — a marker, not a synonym.

    411 of Paekupu's alternative_words are this annotation, sometimes naming the
    source language: (reo Hapanihi) Japanese, (reo Wiwi) French, (reo Itariana)
    Italian, (reo Hiperu) Hebrew. D22 routed them to synonym relations pointing
    at a sentence. They belong in entry.loan_marker, where Te Aka's own loan
    marker lives — which also makes them visible to the D23 etymology filter.
    """

    def test_the_bare_annotation_is_a_loan_marker(self):
        self.assertEqual(parse_alternative("He kupu mino."),
                         {"target": None, "rel_type": "loan_marker",
                          "note": "He kupu mino."})

    def test_case_and_a_missing_stop_do_not_matter(self):
        self.assertEqual(parse_alternative("he kupu mino")["rel_type"],
                         "loan_marker")

    def test_the_source_language_is_kept(self):
        out = parse_alternative("he kupu mino (reo Hapanihi)")
        self.assertEqual(out["rel_type"], "loan_marker")
        self.assertEqual(out["note"], "he kupu mino (reo Hapanihi)")

    def test_an_html_entity_left_by_the_scrape_does_not_defeat_it(self):
        self.assertEqual(parse_alternative("He kupu mino.&nbsp")["rel_type"],
                         "loan_marker")

    def test_an_ordinary_synonym_is_untouched(self):
        self.assertEqual(parse_alternative("aroaro")["rel_type"], "synonym")

    def test_a_dashed_component_is_untouched(self):
        self.assertEqual(parse_alternative("wete - to release")["rel_type"],
                         "cross_ref")



if __name__ == "__main__":
    unittest.main()
