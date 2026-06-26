#!/usr/bin/env python3
"""Test Williams Dictionary parsing output."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
PARSED_FILE = (
    Path(__file__).parent.parent
    / "sources" / "williams" / "parsed" / "williams_entries.json"
)


class TestWilliamsParse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not PARSED_FILE.exists():
            print("\nParsed JSON not found — running parser...", flush=True)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "01_williams_parse.py")]
            )
            if result.returncode != 0:
                raise RuntimeError("Parser script failed")

        with open(PARSED_FILE, encoding="utf-8") as f:
            cls.entries = json.load(f)

        # Index by lowercase headword for case-insensitive spot-checks
        # (HTML headwords are capitalised: "Aho", "Aroha", etc.)
        cls.by_hw_lower = {}
        for e in cls.entries:
            cls.by_hw_lower.setdefault(e["headword"].lower(), []).append(e)

    # --- count ---

    def test_entry_count(self):
        n = len(self.entries)
        self.assertGreaterEqual(n, 5000, f"Too few entries: {n}")
        self.assertLessEqual(n, 15000, f"Too many entries: {n}")

    # --- data quality ---

    def test_no_empty_definitions(self):
        empty = [e["headword"] for e in self.entries if not e.get("definition", "").strip()]
        self.assertEqual(empty, [], f"Entries with empty definitions: {empty[:5]}")

    def test_all_have_headword(self):
        missing = [i for i, e in enumerate(self.entries) if not e.get("headword", "").strip()]
        self.assertEqual(missing, [], f"Entries with empty headword at indices: {missing[:5]}")

    def test_all_have_source_section(self):
        valid = {"A", "E", "H", "I", "K", "M", "N", "Ng", "O", "P", "R", "T", "U", "W"}
        bad = [e["headword"] for e in self.entries if e.get("source_section") not in valid]
        self.assertEqual(bad, [], f"Invalid source_section: {bad[:5]}")

    def test_usage_examples_are_lists(self):
        bad = [
            e["headword"] for e in self.entries
            if not isinstance(e.get("usage_examples"), list)
        ]
        self.assertEqual(bad, [], f"Non-list usage_examples: {bad[:5]}")

    def test_cross_refs_are_lists(self):
        bad = [
            e["headword"] for e in self.entries
            if not isinstance(e.get("cross_refs"), list)
        ]
        self.assertEqual(bad, [], f"Non-list cross_refs: {bad[:5]}")

    # --- macrons ---

    def test_macrons_survive(self):
        macron_set = set("āēīōūĀĒĪŌŪ")
        has_macrons = any(
            any(c in macron_set for c in e["headword"])
            for e in self.entries
        )
        self.assertTrue(has_macrons, "No macron characters found in any headword")

    def test_macron_count_reasonable(self):
        macron_set = set("āēīōūĀĒĪŌŪ")
        count = sum(
            1 for e in self.entries
            if any(c in macron_set for c in e["headword"])
        )
        self.assertGreater(count, 500, f"Unexpectedly few macron headwords: {count}")

    # --- spot-checks (case-insensitive; 1957 HTML uses title-case headwords) ---

    def test_spot_aho(self):
        self.assertIn("aho", self.by_hw_lower, "Missing headword 'aho/Aho/āho'")
        defs = [e["definition"] for e in self.by_hw_lower["aho"]]
        self.assertTrue(any(d for d in defs), "āho entry has no definition text")

    def test_spot_aroha(self):
        self.assertIn("aroha", self.by_hw_lower, "Missing headword 'aroha'")

    def test_spot_kai(self):
        self.assertIn("kai", self.by_hw_lower, "Missing headword 'kai'")

    def test_spot_tangi(self):
        self.assertIn("tangi", self.by_hw_lower, "Missing headword 'tangi'")

    def test_spot_whare(self):
        self.assertIn("whare", self.by_hw_lower, "Missing headword 'whare'")

    def test_spot_multiple_senses(self):
        # kai has at least 5 Roman-numeral senses in Williams
        kai_entries = self.by_hw_lower.get("kai", [])
        self.assertGreaterEqual(len(kai_entries), 3, "Expected multiple senses for 'kai'")

    # --- coverage across all 14 sections ---

    def test_all_sections_have_entries(self):
        sections_found = {e["source_section"] for e in self.entries}
        expected = {"A", "E", "H", "I", "K", "M", "N", "Ng", "O", "P", "R", "T", "U", "W"}
        missing = expected - sections_found
        self.assertEqual(missing, set(), f"Sections with no entries: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
