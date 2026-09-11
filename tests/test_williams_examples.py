"""Williams gloss/example separation — pure string -> (gloss, examples)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from williams_examples import split_gloss_examples


class SplitGlossExamples(unittest.TestCase):
    def test_example_and_citation_separated_from_gloss(self):
        gloss, ex = split_gloss_examples(
            "Throw, cast. Me titere mai kia kai atu au ko te waha (Ngā Mōteatea 19)")
        self.assertEqual(gloss, "Throw, cast.")
        self.assertEqual(ex, [{"text": "Me titere mai kia kai atu au ko te waha",
                               "citation": "Ngā Mōteatea 19"}])

    def test_missing_space_after_the_gloss_period_still_splits(self):
        # `Tinei`: "...extinguish.Ka po, ka tikina..." — no space after the
        # period. A sentence-splitter misses this; orthography does not.
        gloss, ex = split_gloss_examples(
            "Put out, quench, extinguish.Ka po, ka tikina, ka tineia, ka toutoua "
            "nga ahi o te kainga (Tregear 23)")
        self.assertEqual(gloss, "Put out, quench, extinguish.")
        self.assertEqual(len(ex), 1)
        self.assertTrue(ex[0]["text"].startswith("Ka po, ka tikina"))
        self.assertEqual(ex[0]["citation"], "Tregear 23")

    def test_a_gloss_with_no_example_yields_none(self):
        gloss, ex = split_gloss_examples("Myrsine australis, a shrub.")
        self.assertEqual(gloss, "Myrsine australis, a shrub.")
        self.assertEqual(ex, [])

    def test_latin_binomial_is_not_mistaken_for_maori(self):
        # 'Myrsine australis' carries y and s — English-only letters.
        gloss, ex = split_gloss_examples("Apteryx of various species; wingless birds.")
        self.assertEqual(ex, [])
        self.assertIn("Apteryx", gloss)

    def test_english_text_after_an_example_stays_in_the_gloss(self):
        # `Kaihua (i)`: an example sits between two English passages; the
        # trailing English is a sub-entry note, not part of the example.
        gloss, ex = split_gloss_examples(
            "Trees on which birds are speared (not snared or trapped). "
            "To kaihua kai Manuruhi ra. Tao kaihua, a long spear, nearly 30 ft. "
            "in length, for spearing birds.")
        self.assertEqual(ex, [{"text": "To kaihua kai Manuruhi ra.", "citation": None}])
        self.assertIn("Trees on which birds are speared", gloss)
        self.assertIn("a long spear", gloss)
        self.assertNotIn("Manuruhi", gloss)

    def test_two_examples_are_kept_apart(self):
        gloss, ex = split_gloss_examples(
            "Pass out of sight. Te tira o Hika whakanumi atu ana (Ngā Mōteatea 15). "
            "Ka whakanumi atu ia ki te wao (Tregear 57)")
        self.assertEqual(gloss, "Pass out of sight.")
        self.assertEqual([e["citation"] for e in ex],
                         ["Ngā Mōteatea 15", "Tregear 57"])

    def test_a_short_maori_phrase_is_not_an_example(self):
        # Two Māori words inside an English gloss must not become an example.
        gloss, ex = split_gloss_examples("A variety of kumara ahuahu.")
        self.assertEqual(ex, [])

    def test_citation_containing_english_still_terminates_the_run(self):
        # Abbreviations are expanded at import, so '(T. 78)' becomes
        # "(Tregear's Maori-Polynesian Comparative Dictionary 78)". The English
        # in the citation breaks the Māori run before any sentence terminator —
        # the citation itself has to count as the end of the example.
        gloss, ex = split_gloss_examples(
            "Pole, rod, particularly poles used in sacred rites. Ka titiro ki nga "
            "toko o te tuaahu (Tregear's Maori-Polynesian Comparative Dictionary 78)")
        self.assertEqual(gloss, "Pole, rod, particularly poles used in sacred rites.")
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["text"], "Ka titiro ki nga toko o te tuaahu")
        self.assertEqual(ex[0]["citation"],
                         "Tregear's Maori-Polynesian Comparative Dictionary 78")

    def test_removing_an_example_does_not_double_the_gloss_period(self):
        gloss, ex = split_gloss_examples(
            "Cold. He wiri hoki nona i te maeke i te kauanga mai i te po (Tregear 12).")
        self.assertEqual(gloss, "Cold.")
        self.assertEqual(len(ex), 1)

    def test_a_sense_that_is_only_an_example_is_left_intact(self):
        # Extracting here would leave a sense with no gloss at all, which is
        # worse than leaving the text where it is for the audit sweep to judge.
        text = "Ka taumapua nga waka raka."
        gloss, ex = split_gloss_examples(text)
        self.assertEqual(gloss, text)
        self.assertEqual(ex, [])

    def test_separator_left_by_an_excised_example_is_tidied(self):
        # `Kōwhatu`: the gloss ends 'Stone, rock,' — a comma, because the source
        # ran straight on into the example. Lifting the example out used to
        # leave 'Stone, rock,.'. The dangling separator goes and the sentence's
        # own stop, which sat after the citation, comes back to it. Nothing is
        # invented: that stop is in the source.
        gloss, ex = split_gloss_examples(
            "Stone, rock, Ka whakapupuni ia ki nga tauwharewharenga kowhatu "
            "o te waiariki (Tregear 133).")
        self.assertEqual(gloss, "Stone, rock.")
        self.assertEqual(len(ex), 1)

    def test_a_citation_whose_first_word_scans_as_maori_still_ends_the_run(self):
        # '(Korero', '(Ngā', '(Māori' are all orthographically Māori, so the run
        # swallowed the opening bracket and then broke on the English word after
        # it — leaving no citation for the terminator check to find. 1,050
        # senses kept their example inside the gloss this way.
        gloss, ex = split_gloss_examples(
            "Luck, success. Homai he tina; homai he marie; homai he angitu ki "
            "tenei ko (Korero oral narrative texts).")
        self.assertEqual(gloss, "Luck, success.")
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["text"],
                         "Homai he tina; homai he marie; homai he angitu ki tenei ko")
        self.assertEqual(ex[0]["citation"], "Korero oral narrative texts")

    def test_a_fully_maori_citation_is_separated_too(self):
        gloss, ex = split_gloss_examples(
            "Heaped up. He mea ahu nga onepu e nga ringaringa o te tohunga "
            "(Ngā Mōteatea lxxxiii).")
        self.assertEqual(gloss, "Heaped up.")
        self.assertEqual(ex[0]["citation"], "Ngā Mōteatea lxxxiii")

    def test_empty_input(self):
        self.assertEqual(split_gloss_examples(""), ("", []))
        self.assertEqual(split_gloss_examples(None), ("", []))


if __name__ == "__main__":
    unittest.main()
