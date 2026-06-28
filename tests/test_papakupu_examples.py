"""Unit tests for bilingual example extraction in scripts/02_papakupu_extract.py.

Papakupu examples follow the shape `<Māori sentence>. <English translation>. [SRC]`.
The old extractor kept only the English half (everything before [SRC]), leaving
`example.text_mi` NULL downstream. `extract_examples` must now return structured
{text_mi, text_en, source_abbrev} dicts, recovering the Māori half — including the
first example, whose Māori run is glued onto the English gloss prose with no period.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "papakupu_extract", ROOT / "scripts" / "02_papakupu_extract.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
extract_examples = _mod.extract_examples
_maori_tail = _mod._maori_tail


class TestMaoriTail(unittest.TestCase):
    def test_pure_maori_unchanged(self):
        self.assertEqual(_maori_tail("Kua pirau te ahi."), "Kua pirau te ahi.")

    def test_trims_leading_english_gloss(self):
        # gloss prose runs straight into the Māori example with no period
        s = 'āe would be translated as "no" in English Ae kua oti tēnā.'
        self.assertEqual(_maori_tail(s), "Ae kua oti tēnā.")

    def test_trims_inline_metadata_and_gloss(self):
        s = "{RH1} [Noun] fire Na wai tēnā ahi i tau?"
        self.assertEqual(_maori_tail(s), "Na wai tēnā ahi i tau?")

    def test_macrons_survive(self):
        # _maori_tail operates within a single sentence; the English word "respect"
        # bounds the Māori run, and the macron in tēnā must be preserved.
        s = "a sign of respect tēnā koutou katoa."
        self.assertEqual(_maori_tail(s), "tēnā koutou katoa.")


class TestExtractExamples(unittest.TestCase):
    def test_returns_dicts(self):
        out = extract_examples(
            "{MI} surfing Kei te papaku ia e aewa haere ana. "
            "He was surfing along in the shallows. [NGH3]")
        self.assertEqual(len(out), 1)
        ex = out[0]
        self.assertEqual(set(ex), {"text_mi", "text_en", "source_abbrev"})
        self.assertEqual(ex["text_mi"], "Kei te papaku ia e aewa haere ana.")
        self.assertEqual(ex["text_en"], "He was surfing along in the shallows.")
        self.assertEqual(ex["source_abbrev"], "NGH3")

    def test_multiple_examples_distinct_sources(self):
        out = extract_examples(
            "{RH1} [Noun] fire Na wai tēnā ahi i tau? Who lit that fire?. [TTU] "
            "Kua pirau te ahi. The fire has gone out. [MWA]")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["text_mi"], "Na wai tēnā ahi i tau?")
        self.assertEqual(out[0]["source_abbrev"], "TTU")
        self.assertEqual(out[1]["text_mi"], "Kua pirau te ahi.")
        self.assertEqual(out[1]["text_en"], "The fire has gone out.")
        self.assertEqual(out[1]["source_abbrev"], "MWA")

    def test_first_example_recovered_from_gloss(self):
        out = extract_examples(
            '[Adverb]: yes, in the sense of agreement; if negative, āe would be '
            'translated as "no" in English Ae kua oti tēnā. '
            "That's correct it's finished. [TWK]")
        self.assertEqual(out[0]["text_mi"], "Ae kua oti tēnā.")
        self.assertEqual(out[0]["text_en"], "That's correct it's finished.")
        self.assertEqual(out[0]["source_abbrev"], "TWK")

    def test_compound_source_ref(self):
        out = extract_examples(
            "I, me. Aua hoki, e kore ahau e mōhio. I just don't know. [TWK/MHR]")
        self.assertEqual(out[0]["text_mi"], "Aua hoki, e kore ahau e mōhio.")
        self.assertEqual(out[0]["source_abbrev"], "TWK/MHR")

    def test_text_en_has_no_source_bracket(self):
        out = extract_examples(
            "He aha te mea na? What is that thing? [TWK]")
        for ex in out:
            self.assertNotIn("[", ex["text_en"] or "")

    def test_no_examples_when_no_source_ref(self):
        self.assertEqual(extract_examples("{RH1} [Noun] plain gloss with no example."), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
