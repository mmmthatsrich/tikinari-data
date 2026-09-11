"""Te Aka `filters` routing: a loan marker is not a semantic domain.

Every one of Te Aka's 18,439 entry_domain rows held 'Historical Loan Word' —
a register/etymology marker occupying the subject-area table, and the single
most common "domain" in the whole database. `entry.loan_marker` exists for
exactly this and was NULL on all 153,543 entries.
"""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

bu = importlib.import_module("50_build_unified")


class SplitFilters(unittest.TestCase):
    def test_the_loan_marker_is_routed_out_of_the_domains(self):
        self.assertEqual(bu.split_filters(["Historical Loan Word"]),
                         ("Historical Loan Word", []))

    def test_a_genuine_subject_filter_stays_a_domain(self):
        # Te Aka ships only the loan filter today; anything else it adds later
        # is a subject area and must not be mislabelled as a loan marker.
        self.assertEqual(bu.split_filters(["Biology"]), (None, ["Biology"]))

    def test_both_kinds_are_separated(self):
        self.assertEqual(bu.split_filters(["Historical Loan Word", "Biology"]),
                         ("Historical Loan Word", ["Biology"]))

    def test_several_loan_markers_are_joined(self):
        self.assertEqual(
            bu.split_filters(["Historical Loan Word", "Modern Loan Word"]),
            ("Historical Loan Word; Modern Loan Word", []))

    def test_non_strings_are_coerced(self):
        self.assertEqual(bu.split_filters([123]), (None, ["123"]))

    def test_nothing(self):
        self.assertEqual(bu.split_filters([]), (None, []))
        self.assertEqual(bu.split_filters(None), (None, []))


if __name__ == "__main__":
    unittest.main()
