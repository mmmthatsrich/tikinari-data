"""The rubric document and the code must not drift apart.

The rubric is the standard the sweep judges by, and every finding is stamped
with its version so a change can be turned into a targeted re-sweep. If the
document says one thing and the code accepts another, the stamp stops meaning
anything and the corpus quietly ends up judged by two different standards.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from sweep_findings import KINDS
from sweep_rubric import (RUBRIC_PATH, VERSION, documented_kinds,
                          documented_version, read_rubric)


class RubricDocument(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read_rubric()

    def test_the_rubric_exists(self):
        self.assertTrue(RUBRIC_PATH.exists(), f"missing {RUBRIC_PATH}")

    def test_the_document_declares_the_code_version(self):
        self.assertEqual(documented_version(self.text), VERSION)

    def test_every_finding_kind_the_code_accepts_is_documented(self):
        missing = KINDS - documented_kinds(self.text)
        self.assertEqual(missing, set(),
                         f"finding kinds with no rubric section: {sorted(missing)}")

    def test_the_document_defines_no_kind_the_code_would_reject(self):
        extra = documented_kinds(self.text) - KINDS
        self.assertEqual(extra, set(),
                         f"documented kinds the code refuses: {sorted(extra)}")

    def test_the_hard_rules_are_stated(self):
        # These are the constraints that make autonomous writing safe; a rubric
        # that loses them is not this rubric.
        for rule in ("Never invent lexicographic content",
                     "Never rewrite a source's own voice",
                     "Never address `entry.id`",
                     "Never merge entries across sources"):
            self.assertIn(rule, self.text, f"hard rule missing: {rule}")

    def test_the_known_correct_patterns_are_listed(self):
        # Flagging these is noise, and noise is what makes a log unreadable.
        for pattern in ("monolingual Māori", "per-word tooltips",
                        "Homograph numerals", "Latin binomials"):
            self.assertIn(pattern, self.text)

    def test_calibration_is_specified_before_the_full_sweep(self):
        self.assertIn("calibration slice", self.text)
        self.assertIn("500", self.text)


if __name__ == "__main__":
    unittest.main()
