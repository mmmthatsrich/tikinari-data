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


if __name__ == "__main__":
    unittest.main()
