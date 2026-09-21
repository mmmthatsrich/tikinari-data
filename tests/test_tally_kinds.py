"""The refusal report counts four different things, and says which.

Spec §6 sets a tripwire: refusals above 1% of tokens mean a real suffix has
fallen outside the 23-word vocabulary — the mechanism that would have caught
'-hina' sooner. One counter was carrying four structurally different events,
so the tripwire fired on four of six sources and in none of them meant what
it says. Measured before this change:

    te_aka        6,408 seen      2 refused   0.03%   suffix tokens
    paekupu       1,806 seen     16 refused   0.89%   tokens it WROTE
    williams         36 seen      1 refused   2.78%   a 36-token sample
    papakupu        231 seen     19 refused   8.23%   reduplications
    ngata        ~4,780 tested ~134 rejected  2.80%   PAIR TESTS, not tokens
    hepatakakupu      4 bases     4 refused 100.00%   headwords with parens

Only the first kind answers the question the tripwire asks.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import Tally


class Kinds(unittest.TestCase):
    def setUp(self):
        self.t = Tally()

    def test_a_kept_token_counts_against_its_own_kind(self):
        self.t.keep()
        self.t.keep(kind="pair")
        self.assertEqual(self.t.seen_of("suffix"), 1)
        self.assertEqual(self.t.seen_of("pair"), 1)

    def test_suffix_is_the_default_kind(self):
        # Every existing reader call site passes no kind and means 'suffix'.
        self.t.refuse("-bga")
        self.assertEqual(self.t.refused_of("suffix"), ["-bga"])

    def test_a_refusal_is_filed_under_its_kind_only(self):
        self.t.refuse("-bga")
        self.t.refuse("-wheke", kind="pair")
        self.t.refuse("hohou (i te) rongo", kind="base")
        self.assertEqual(self.t.refused_of("suffix"), ["-bga"])
        self.assertEqual(self.t.refused_of("pair"), ["-wheke"])
        self.assertEqual(self.t.refused_of("base"), ["hohou (i te) rongo"])

    def test_the_rate_is_per_kind(self):
        for _ in range(99):
            self.t.keep()
        self.t.refuse("-bga")
        self.t.refuse("-wheke", kind="pair")
        self.assertAlmostEqual(self.t.refusal_rate("suffix"), 0.01)
        self.assertEqual(self.t.refusal_rate("pair"), 1.0)

    def test_a_kind_never_used_has_no_rate(self):
        self.assertIsNone(self.t.refusal_rate("pair"))

    def test_the_kinds_that_occurred_are_reportable_in_a_stable_order(self):
        self.t.refuse("hohou (i te) rongo", kind="base")
        self.t.keep(kind="pair")
        self.t.keep()
        self.assertEqual(self.t.kinds(), ["suffix", "pair", "base"])


class Reclassify(unittest.TestCase):
    """paekupu refuses a token as a suffix, then writes it as a whole form.

    'hau ~hāua' — read_tilde_suffixes refuses '-hāua' because it is not in
    the vocabulary, and read_whole_forms then writes 'hāua' verbatim. Left
    alone that reports 16 refusals for 16 rows that exist, and it was the
    whole of paekupu's 0.89% against a 1% tripwire.
    """

    def setUp(self):
        self.t = Tally()
        self.t.refuse("-hāua")

    def test_a_reclassified_token_leaves_the_suffix_refusals(self):
        self.t.reclassify("-hāua", "whole")
        self.assertEqual(self.t.refused_of("suffix"), [])

    def test_it_arrives_in_its_new_kind(self):
        self.t.reclassify("-hāua", "whole")
        self.assertEqual(self.t.seen_of("whole"), 1)
        self.assertEqual(self.t.refused_of("whole"), [])

    def test_the_suffix_rate_drops_to_zero(self):
        # paekupu's real shape: many good tokens, plus the handful that get
        # written whole. 0.89% against a 1% tripwire becomes 0.00%.
        for _ in range(99):
            self.t.keep()
        self.assertAlmostEqual(self.t.refusal_rate("suffix"), 0.01)
        self.t.reclassify("-hāua", "whole")
        self.assertEqual(self.t.refusal_rate("suffix"), 0.0)

    def test_moving_the_only_token_leaves_no_rate_rather_than_zero(self):
        # 0/0 is undefined, and printing '0.00%' for a kind with nothing in
        # it would read as a clean bill instead of an empty one.
        self.t.reclassify("-hāua", "whole")
        self.assertIsNone(self.t.refusal_rate("suffix"))

    def test_it_does_not_double_count_the_token_as_seen(self):
        # The reason read_whole_forms originally took no tally at all. A
        # move must not also add.
        self.t.reclassify("-hāua", "whole")
        self.assertEqual(self.t.seen_of("suffix"), 0)
        self.assertEqual(self.t.seen_of("whole"), 1)

    def test_reclassifying_a_token_never_refused_is_a_no_op(self):
        # Defensive: a whole form whose token the reader did not refuse
        # must not invent a count.
        self.t.reclassify("-neverseen", "whole")
        self.assertEqual(self.t.seen_of("whole"), 0)
        self.assertEqual(self.t.refused_of("suffix"), ["-hāua"])

    def test_only_one_instance_moves_per_call(self):
        self.t.refuse("-hāua")
        self.t.reclassify("-hāua", "whole")
        self.assertEqual(self.t.refused_of("suffix"), ["-hāua"])
        self.assertEqual(self.t.seen_of("whole"), 1)


class BackwardCompatible(unittest.TestCase):
    """The old attributes still read as the totals across every kind."""

    def test_seen_totals_every_kind(self):
        t = Tally()
        t.keep()
        t.keep(kind="pair")
        t.refuse("hohou (i te) rongo", kind="base")
        self.assertEqual(t.seen, 3)

    def test_refused_totals_every_kind(self):
        t = Tally()
        t.refuse("-bga")
        t.refuse("-wheke", kind="pair")
        self.assertEqual(sorted(t.refused), ["-bga", "-wheke"])


if __name__ == "__main__":
    unittest.main()


class Report(unittest.TestCase):
    """format_suffix_report renders one line per kind that occurred."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_unified",
            Path(__file__).parent.parent / "scripts" / "50_build_unified.py")
        cls.bu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bu)

    def test_a_clean_source_reports_rows_and_one_kind(self):
        t = Tally()
        for _ in range(100):
            t.keep()
        self.assertEqual(
            self.bu.format_suffix_report("te_aka", 120, t),
            ["  [te_aka] suffix-forms: 120 rows written",
             "      suffix     100 tokens"])

    def test_a_vocabulary_problem_is_flagged(self):
        t = Tally()
        for _ in range(98):
            t.keep()
        t.refuse("-bga")
        t.refuse("-pukenga")
        lines = self.bu.format_suffix_report("hepatakakupu", 90, t)
        self.assertIn("2.00%", lines[1])
        self.assertIn("OVER 1%", lines[1])

    def test_a_pair_rejection_is_never_flagged(self):
        # ngata sits at 2.8% and is not a vocabulary problem: the
        # discriminator is declining compounds, which is its job.
        t = Tally()
        for _ in range(97):
            t.keep(kind="pair")
        for tok in ("-wheke", "-rahu", "-ki"):
            t.refuse(tok, kind="pair")
        lines = self.bu.format_suffix_report("ngata", 4646, t)
        self.assertIn("rejected", lines[1])
        self.assertNotIn("OVER 1%", " ".join(lines))

    def test_kinds_that_did_not_occur_are_not_printed(self):
        t = Tally()
        t.keep()
        lines = self.bu.format_suffix_report("kimikupu_hou", 18, t)
        self.assertEqual(len(lines), 2)
        self.assertNotIn("pair", " ".join(lines))

    def test_a_reclassified_whole_form_reports_as_written_not_refused(self):
        # paekupu's real shape, in miniature.
        t = Tally()
        for _ in range(50):
            t.keep()
        t.refuse("-hāua")
        t.reclassify("-hāua", "whole")
        lines = self.bu.format_suffix_report("paekupu", 60, t)
        joined = " ".join(lines)
        self.assertNotIn("refused", joined)
        self.assertIn("whole", joined)
        self.assertIn("1 whole forms", joined)
