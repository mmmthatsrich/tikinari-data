"""Te Māra Reo gloss / definition_raw assembly — pure, no DB."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from temarareo_gloss import (build_raw, clean_definition, dedupe_species,
                             residual_species)


class DedupeSpecies(unittest.TestCase):
    def test_a_repeated_species_is_listed_once(self):
        # `harakeke` lists Astelia banksii three times and Phormium tenax twice.
        self.assertEqual(
            dedupe_species(["Astelia spp.", "Phormium tenax", "Astelia banksii",
                            "Astelia banksii", "Phormium tenax"]),
            ["Astelia spp.", "Phormium tenax", "Astelia banksii"])

    def test_the_variant_carrying_the_alias_is_the_one_kept(self):
        # `kauere`: 'Vitex lucens (a.k.a. pūriri)' says more than 'Vitex lucens'.
        self.assertEqual(
            dedupe_species(["Vitex lucens (a.k.a. pūriri)", "Vitex lucens"]),
            ["Vitex lucens (a.k.a. pūriri)"])

    def test_order_of_first_appearance_is_kept(self):
        self.assertEqual(
            dedupe_species(["Griselinia littoralis", "Meryta sinclairii [puka]",
                            "Griselinia littoralis [kāpuka]"]),
            ["Griselinia littoralis [kāpuka]", "Meryta sinclairii [puka]"])

    def test_distinct_species_are_all_kept(self):
        self.assertEqual(dedupe_species(["Astelia spp.", "Phormium tenax"]),
                         ["Astelia spp.", "Phormium tenax"])


class CleanDefinition(unittest.TestCase):
    def test_a_definition_that_is_only_a_protoform_is_not_a_definition(self):
        # `kauere` and `Pūriri` both carry '*Kauere' — the parser picked up the
        # protoform heading. The species list is the real content.
        self.assertIsNone(clean_definition("*Kauere"))

    def test_a_real_definition_is_untouched(self):
        self.assertEqual(clean_definition("Vitex lucens (Lamiaceae)"),
                         "Vitex lucens (Lamiaceae)")

    def test_a_definition_merely_starting_with_a_protoform_is_kept(self):
        self.assertEqual(clean_definition("*Kauere Vitex lucens"),
                         "*Kauere Vitex lucens")

    def test_blank(self):
        self.assertIsNone(clean_definition(""))
        self.assertIsNone(clean_definition(None))


class ResidualSpecies(unittest.TestCase):
    def test_species_already_named_in_the_definition_are_dropped(self):
        self.assertEqual(
            residual_species("Pteridium esculentum (Dennstaedtiaceae)",
                             ["Pteridium esculentum"]),
            [])

    def test_a_species_not_in_the_definition_is_kept(self):
        self.assertEqual(
            residual_species("Geniostoma ligustrifolium (Loganiaceae)",
                             ["Geniostoma ligustrifolium", "Pomaderris apetala"]),
            ["Pomaderris apetala"])

    def test_the_bracketed_alias_is_ignored_when_matching(self):
        # 'Elaeocarpus dentatus [a.k.a. hīnau]' matches a definition naming only
        # 'Elaeocarpus dentatus'.
        self.assertEqual(
            residual_species("also an alternative name for hīnau, Elaeocarpus dentatus",
                             ["Elaeocarpus dentatus [a.k.a. hīnau]"]),
            [])

    def test_no_definition_keeps_every_species(self):
        self.assertEqual(residual_species(None, ["Astelia spp.", "Phormium tenax"]),
                         ["Astelia spp.", "Phormium tenax"])


class BuildRaw(unittest.TestCase):
    def test_fully_duplicated_species_add_no_bracket(self):
        self.assertEqual(
            build_raw("Pteridium esculentum (Dennstaedtiaceae)", None,
                      ["Pteridium esculentum"]),
            "Pteridium esculentum (Dennstaedtiaceae)")

    def test_only_the_species_the_definition_omits_are_appended(self):
        self.assertEqual(
            build_raw("Arthropodium cirratum (Anthericaceae)", None,
                      ["Arthropodium cirratum", "Tetragonia tetragoniodes"]),
            "Arthropodium cirratum (Anthericaceae) [Tetragonia tetragoniodes]")

    def test_species_only_record_is_bracketed_once_not_twice(self):
        # `nonokia` had definition_raw '[Pomaderris apetala]' where the gloss was
        # already 'Pomaderris apetala' — the bracket wrapped the whole content.
        self.assertEqual(build_raw(None, None, ["Pomaderris apetala"]),
                         "Pomaderris apetala")

    def test_note_is_kept(self):
        self.assertEqual(build_raw("Vitex lucens", "also called pūriri", []),
                         "Vitex lucens also called pūriri")

    def test_species_named_in_the_note_are_not_repeated_either(self):
        # `kauere`: the definition is only a protoform, so the content sits in
        # the note — which already names Vitex lucens.
        self.assertEqual(
            build_raw(None, 'Vitex lucens, "Pūriri" (Lamiaceae)',
                      ["Vitex lucens (a.k.a. pūriri)", "Vitex lucens"]),
            'Vitex lucens, "Pūriri" (Lamiaceae)')

    def test_space_before_a_comma_is_tidied(self):
        # The source writes 'Vitex lucens , "Pūriri"'.
        self.assertEqual(build_raw('Vitex lucens , "Pūriri" (Lamiaceae)', None, []),
                         'Vitex lucens, "Pūriri" (Lamiaceae)')

    def test_nothing_at_all(self):
        self.assertIsNone(build_raw(None, None, []))


if __name__ == "__main__":
    unittest.main()
