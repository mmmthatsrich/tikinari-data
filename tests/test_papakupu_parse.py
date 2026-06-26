"""Tests for the Papakupu o Tai Tokerau PDF extraction."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
JSON_PATH = ROOT / "sources" / "papakupu" / "parsed" / "papakupu_entries.json"


def load_entries():
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestPapakupuParse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.entries = load_entries()
        cls.by_headword = {}
        for e in cls.entries:
            cls.by_headword.setdefault(e["headword"], []).append(e)

    def find(self, hw: str, sense: str | None = None):
        """Return first matching entry, normalising macrons for lookup."""
        def norm(s):
            for a, b in [("ā","a"),("ē","e"),("ī","i"),("ō","o"),("ū","u"),
                         ("Ā","A"),("Ē","E"),("Ī","I"),("Ō","O"),("Ū","U")]:
                s = s.replace(a, b)
            return s.lower()

        hw_norm = norm(hw)
        for e in self.entries:
            if norm(e["headword"].split(",")[0].strip()) == hw_norm:
                if sense is None or e["sense_number"] == sense:
                    return e
        return None

    # ------------------------------------------------------------------ #
    # Count and range
    # ------------------------------------------------------------------ #

    def test_entry_count_in_range(self):
        self.assertGreaterEqual(len(self.entries), 3200,
                                "Too few entries — extraction may be incomplete")
        self.assertLessEqual(len(self.entries), 5000,
                             "Too many entries — false positives likely")

    def test_page_range(self):
        # Website-sourced entries (session 6b) have no pdf_page; range applies to PDF entries only.
        pages = [e["pdf_page"] for e in self.entries if e["pdf_page"] is not None]
        self.assertGreaterEqual(min(pages), 27)
        self.assertLessEqual(max(pages), 610)

    # ------------------------------------------------------------------ #
    # Data integrity
    # ------------------------------------------------------------------ #

    def test_no_empty_headwords(self):
        empty = [e for e in self.entries if not e["headword"]]
        self.assertEqual(empty, [], f"{len(empty)} entries have empty headwords")

    def test_no_empty_definitions(self):
        # The PDF is a working draft; a small number of stub entries have no body text
        empty = [e for e in self.entries if not e.get("definition", "").strip()]
        self.assertLess(len(empty), 30,
                        f"Too many empty definitions ({len(empty)}); check extraction")

    def test_sense_numbers_reasonable(self):
        # Website-sourced entries (session 6b) may have no sense_number.
        bad = [e for e in self.entries
               if e["sense_number"] is not None and int(e["sense_number"]) > 20]
        self.assertEqual(bad, [], f"Unexpected large sense numbers: {[e['sense_number'] for e in bad]}")

    def test_macrons_survive(self):
        """Māori macron characters must appear in the data."""
        all_text = " ".join(e["headword"] for e in self.entries)
        self.assertIn("ā", all_text, "macron ā missing from headwords")
        self.assertIn("ō", all_text, "macron ō missing from headwords")

    def test_variant_forms_are_lists(self):
        for e in self.entries:
            self.assertIsInstance(e["variant_forms"], list,
                                  f"{e['headword']}: variant_forms must be list")

    def test_usage_examples_are_lists(self):
        for e in self.entries:
            self.assertIsInstance(e["usage_examples"], list,
                                  f"{e['headword']}: usage_examples must be list")

    def test_see_also_are_lists(self):
        for e in self.entries:
            self.assertIsInstance(e["see_also"], list,
                                  f"{e['headword']}: see_also must be list")

    # ------------------------------------------------------------------ #
    # Spot-checks
    # ------------------------------------------------------------------ #

    def test_apa_entry(self):
        e = self.find("apa", "1")
        self.assertIsNotNone(e, "apa [1] not found")
        self.assertEqual(e["source_code"], "RK4")
        self.assertEqual(e["part_of_speech"], "Noun")
        self.assertIn("slave", e["definition"])

    def test_aho_entry(self):
        e = self.find("aho", "1")
        self.assertIsNotNone(e, "aho [1] not found")
        self.assertEqual(e["source_code"], "R9")
        self.assertEqual(e["part_of_speech"], "Noun")
        self.assertIn("fishing line", e["definition"])

    def test_apiha_entry(self):
        e = self.find("āpiha", "1")
        self.assertIsNotNone(e, "āpiha [1] not found")
        self.assertIn("aapiha", e["variant_forms"])
        self.assertIn("apiha", e["variant_forms"])
        self.assertEqual(e["source_code"], "RK2")
        self.assertEqual(e["part_of_speech"], "Noun")

    def test_variant_forms_correctly_split(self):
        """Variants like 'aapiha, apiha' must be separate list items, not one string."""
        e = self.find("āpiha", "1")
        self.assertIsNotNone(e)
        self.assertNotIn(",", "".join(e["variant_forms"]),
                         "variant_forms should be split on commas, not joined")

    def test_entries_with_variants_exist(self):
        with_variants = [e for e in self.entries if e["variant_forms"]]
        self.assertGreater(len(with_variants), 400,
                           "Too few entries have variant_forms extracted")

    def test_entries_with_pos_exist(self):
        with_pos = [e for e in self.entries if e["part_of_speech"]]
        self.assertGreater(len(with_pos), 2000,
                           "Too few entries have part_of_speech extracted")

    def test_see_also_no_periods(self):
        """Cross-reference words should not contain periods."""
        bad = [e for e in self.entries
               if any("." in w for w in e["see_also"])]
        self.assertEqual(bad, [],
                         f"{len(bad)} entries have see_also with periods")


if __name__ == "__main__":
    unittest.main(verbosity=2)
