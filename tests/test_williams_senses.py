import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from williams_senses import split_senses

PAE = ("1. n. Horizon. Ano ko Kopu ka puta ake i te pae (Tregear's Maori-Polynesian "
       "Comparative Dictionary 99). 2. Region, direction. Kei whea te pae? (Tregear 136). "
       "3. Horizontal ridges of hills. Haere koe (Tregear 95).")

class TestWilliamsSenses(unittest.TestCase):

    def test_pae_three_senses_with_carryover(self):
        s = split_senses(PAE)
        assert [x["sense_number"] for x in s] == [1, 2, 3]
        assert s[0]["part_of_speech"] == "n."
        assert s[1]["part_of_speech"] == "n."   # carry-over
        assert s[2]["part_of_speech"] == "n."   # carry-over
        assert s[0]["gloss_en"].startswith("Horizon")
        assert "Region, direction" in s[1]["gloss_en"]

    def test_vi_then_carryover(self):
        d = "1. v.i. Flow. Tena te wai. 2. Fly. Pekapeka rere. 3. Sail. Rere noa."
        s = split_senses(d)
        assert [x["part_of_speech"] for x in s] == ["v.i.", "v.i.", "v.i."]

    def test_citation_page_number_not_split(self):
        # "99)." then no real sense 2 -> single sense
        d = "n. Horizon. Ano ko Kopu (Tregear's Comparative Dictionary 99)."
        s = split_senses(d)
        assert len(s) == 1
        assert s[0]["sense_number"] == 1
        assert s[0]["part_of_speech"] == "n."

    def test_single_sense_leading_pos(self):
        s = split_senses("v.t. Carry. He mea kawe.")
        assert len(s) == 1
        assert s[0]["part_of_speech"] == "v.t."
        assert s[0]["gloss_en"].startswith("Carry")

    def test_no_pos_is_none(self):
        s = split_senses("Thing of unknown class.")
        assert len(s) == 1
        assert s[0]["part_of_speech"] is None

    def test_definition_raw_preserved(self):
        s = split_senses(PAE)
        assert "Tregear" in s[0]["definition_raw"]  # citations kept in raw

    def test_sense_marker_does_not_eat_the_previous_citation_paren(self):
        # `Mumu`: the separator before '2.' is ') ', and consuming the ')' left
        # sense 1 ending '...(Ngā Mōteatea 124' — 148 senses lost a character
        # this way. The paren closes the citation; it belongs to sense 1.
        s = split_senses(
            "1. Baffling, boisterous wind. Ka riro te mumu, ka riro te awha "
            "(Ngā Mōteatea 124) 2. fig. Valiant warrior.")
        assert len(s) == 2
        assert s[0]["definition_raw"].endswith("(Ngā Mōteatea 124)")
        assert s[1]["definition_raw"] == "fig. Valiant warrior."

    def test_unnumbered_first_sense_still_splits(self):
        # `Toroku` (10508): Williams leaves the FIRST sense unnumbered and
        # starts explicit numbering at 2. Requiring a run from 1 meant the run
        # never started and the whole entry collapsed into one sense.
        s = split_senses("Caterpillar, grub. 2. A fresh-water fish.")
        assert len(s) == 2
        assert s[0]["gloss_en"] == "Caterpillar, grub."
        assert s[0]["sense_number"] == 1
        assert s[1]["gloss_en"] == "A fresh-water fish."
        assert s[1]["sense_number"] == 2

    def test_unnumbered_first_sense_keeps_its_leading_pos(self):
        # `Tohunga-rua` (10295): the implicit sense 1 carries the entry POS,
        # and sense 2 restates its own.
        s = split_senses("v.t. Dole out. Tohungaruatia etahi kapana ma tatou. "
                         "2. n. One who deals.")
        assert len(s) == 2
        assert s[0]["part_of_speech"] == "v.t."
        assert s[0]["gloss_en"].startswith("Dole out.")
        assert s[1]["part_of_speech"] == "n."

    def test_sense_marker_follows_a_question_or_exclamation(self):
        # `Hia` (1090): Maori example sentences end in ? and !, which the
        # separator class [.)] excluded, so the marker after them was invisible.
        s = split_senses("Interrogative numeral. How many? Tokohia ou hoa ? "
                         "Te hia ? which in order? 2. An indefinite number.")
        assert len(s) == 2
        assert s[0]["gloss_en"].endswith("which in order?")
        assert s[1]["gloss_en"] == "An indefinite number."

    def test_lone_stray_number_after_comma_is_not_a_sense_marker(self):
        # `Toro` (10534): 'Variant of toro (i), 1. (Colenso.)' — the '1.' is a
        # sense reference inside a cross-reference, not a sense boundary.
        s = split_senses("Variant of toro (i), 1. (Colenso.).")
        assert len(s) == 1


if __name__ == "__main__":
    unittest.main()
