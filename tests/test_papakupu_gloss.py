"""Unit tests for scripts/papakupu_gloss.clean_gloss.

A Papakupu ``definition`` glues usage examples (``<Māori>. <English>. [SRC]``)
and editorial ``#[Note ...]`` blocks straight onto the English gloss prose.
``clean_gloss`` must return the gloss only, cutting everything from the first
example / note onward, without truncating legitimate English prose that merely
contains capitalised Māori proper nouns.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "papakupu_gloss", ROOT / "scripts" / "papakupu_gloss.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
clean_gloss = _mod.clean_gloss


class TestCleanGloss(unittest.TestCase):
    def test_strips_examples_leaving_gloss(self):
        d = ("love, pity, compassion, sympathy He mate ano kei roto i te aroha. "
             "There is good and bad in love. [MWA] Te aroha o te hanga o taku kupu. "
             "My words are formed in love. [TWK]")
        self.assertEqual(clean_gloss(d), "love, pity, compassion, sympathy")

    def test_short_all_maori_letter_gloss_survives(self):
        # "to mouth" / "open" / "narrow" are all-Māori-letters; a naïve letter test
        # would swallow them into the following Māori example.
        self.assertEqual(
            clean_gloss("to mouth E kome ana kia whangaitia ano. "
                        "Mouthing for more food. [NGH3]"),
            "to mouth")
        self.assertEqual(
            clean_gloss("open Me koohue ngā pipi kia kowhera. "
                        "Steam the shellfish to open them. [NKU]"),
            "open")
        self.assertEqual(
            clean_gloss("narrow Kuiti rawa tēnā tuuru. That stool is too narrow. [MWA]"),
            "narrow")

    def test_note_block_dropped(self):
        d = ("jurisdiction over part of the sea or a lake. "
             "#[Note from Te Mātāpunenga ©] Mana moana. Authority and jurisdiction "
             "over an area of sea.")
        self.assertEqual(clean_gloss(d), "jurisdiction over part of the sea or a lake")

    def test_trailing_source_and_date_codes_stripped(self):
        self.assertEqual(clean_gloss("dawn [051111]"), "dawn")

    def test_text_mi_backstop_when_heuristic_misses(self):
        # An example whose Māori sentence starts lower-case escapes the capital-run
        # heuristic; the stored text_mi backstop must still remove it.
        d = "to gather kua kohia ngā hua. The fruit has been gathered. [TTU]"
        out = clean_gloss(d, ["kua kohia ngā hua."])
        self.assertNotIn("kua kohia", out)
        self.assertEqual(out, "to gather")

    def test_maori_only_entry_returns_none(self):
        self.assertIsNone(
            clean_gloss("Kookohua mai te tarete nei. **** [TWK]",
                        ["Kookohua mai te tarete nei."]))

    def test_english_note_with_maori_place_names_kept(self):
        # A hapū census note is English prose full of capitalised Māori place names;
        # the trailing "Ngapuhi at Kokohuia in 1918." must NOT be cut as an example.
        d = ("Ngati Kopako This hapū name was recorded for one voter affiliated "
             "with Ngapuhi at Kokohuia in 1918.")
        # the whole English note is kept; only the trailing full stop is tidied off.
        self.assertEqual(clean_gloss(d), d.rstrip("."))

    def test_none_and_empty_input(self):
        self.assertIsNone(clean_gloss(None))
        self.assertIsNone(clean_gloss(""))
        self.assertIsNone(clean_gloss("   "))

    def test_plain_gloss_unchanged(self):
        self.assertEqual(clean_gloss("a kind of tree"), "a kind of tree")


if __name__ == "__main__":
    unittest.main(verbosity=2)
