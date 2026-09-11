"""Te Aka bilingual example splitting — pure strings, no DOM, no DB.

Te Aka publishes both halves of every usage example:

    <em>Ka piki haere ... ki te ahuone (Te Ara 2015).</em> / Māori knowledge of
    horticulture developed.

The parser took only the <em> content, so all 45,939 example rows carried
text_mi and nothing else. The translations were in the cached pages the whole
time — 99% of example paragraphs have one.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib

from te_aka_examples import split_example

bu = importlib.import_module("50_build_unified")


class SplitExample(unittest.TestCase):
    def test_the_translation_after_the_slash_is_captured(self):
        para = ("Ka piki haere ngā mōhiotanga o te Māori ki te ahuone (Te Ara "
                "2015).  / Māori knowledge of horticulture developed.")
        em = "Ka piki haere ngā mōhiotanga o te Māori ki te ahuone (Te Ara 2015)."
        self.assertEqual(
            split_example(para, em),
            {"mi": em, "en": "Māori knowledge of horticulture developed."})

    def test_an_absent_translation_gives_none_not_empty(self):
        em = "Kei te pai."
        self.assertEqual(split_example("Kei te pai. /          ", em),
                         {"mi": em, "en": None})

    def test_no_separator_at_all(self):
        em = "Kei te pai."
        self.assertEqual(split_example("Kei te pai.", em), {"mi": em, "en": None})

    def test_a_slash_inside_the_maori_is_not_the_separator(self):
        # Citations carry dates: '(Te Wananga 16/11/1878:576)'. The split must
        # happen after the <em>, never at the first slash in the sentence.
        em = "I hāwhetia te whenua (Te Wananga 16/11/1878:576)."
        para = em + " / The land was halved."
        self.assertEqual(split_example(para, em),
                         {"mi": em, "en": "The land was halved."})

    def test_an_ellipsis_pair_is_kept_intact(self):
        em = "… me tōna teina, a Pirinihe Ārihi…"
        self.assertEqual(
            split_example(em + " / … and her sister, Princess Alice…", em),
            {"mi": em, "en": "… and her sister, Princess Alice…"})

    def test_whitespace_is_collapsed_on_both_halves(self):
        em = "Kei  te   pai."
        out = split_example("Kei  te   pai.  /   All   good.", em)
        self.assertEqual(out, {"mi": "Kei te pai.", "en": "All good."})

    def test_empty_input(self):
        self.assertIsNone(split_example("", ""))
        self.assertIsNone(split_example(None, None))


class SplitCitation(unittest.TestCase):
    """Te Aka closes a cited sentence AFTER the bracket: '... (Te Ara 2015).'

    split_cite anchored the citation to end-of-string, so a trailing stop meant
    no match: 23,183 citations stayed inside text_mi.
    """

    def test_citation_before_a_sentence_stop_is_extracted(self):
        text, cite = bu.split_cite(
            "Ka piki haere ngā mōhiotanga o te Māori ki te ahuone (Te Ara 2015).")
        self.assertEqual(cite, "Te Ara 2015")
        self.assertEqual(
            text, "Ka piki haere ngā mōhiotanga o te Māori ki te ahuone.")

    def test_citation_at_the_very_end_still_works(self):
        text, cite = bu.split_cite("Kei te pai (Te Ara 2015)")
        self.assertEqual(cite, "Te Ara 2015")
        self.assertEqual(text, "Kei te pai")

    def test_the_sentence_stop_is_returned_to_the_sentence(self):
        # The full stop belongs to the Māori sentence, not to the citation.
        text, _ = bu.split_cite("Kua tae mai ia (Te Wananga 16/11/1878:576).")
        self.assertTrue(text.endswith("ia."))

    def test_a_parenthetical_without_a_digit_is_not_a_citation(self):
        text, cite = bu.split_cite("He tangata pai ia (he pono).")
        self.assertIsNone(cite)
        self.assertEqual(text, "He tangata pai ia (he pono).")

    def test_no_parenthetical_at_all(self):
        text, cite = bu.split_cite("Kei te pai.")
        self.assertIsNone(cite)
        self.assertEqual(text, "Kei te pai.")


if __name__ == "__main__":
    unittest.main()
