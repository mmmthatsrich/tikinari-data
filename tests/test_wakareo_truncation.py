"""Wakareo's `equivalents` field is capped at 50 characters (D31).

Ngata records the Māori equivalents of an English lemma as one delimited run:

    <B>ahu, ahuna, whāngai, whāngaitia, atawhai, atawhait</B>

That string is exactly 50 characters, and `atawhait` is `atawhaitia` with the
tail cut off. The cap is provable rather than inferred: no equivalents list in
the source exceeds 50 characters, and 103 of the lists that reach it end in a
consonant — impossible in Māori, where every word ends in a vowel.

The damage is upstream, in `body_raw` itself, so the landing table keeps it.
What the unified core must not do is mint an `entry` whose headword is
`whakah`, because the source never asserted that word — a transport limit did.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from wakareo_records import drop_truncated_tail


class DropTruncatedTail(unittest.TestCase):
    def test_a_capped_list_ending_in_a_consonant_loses_its_tail(self):
        # 50 chars exactly; 'whakah' is the start of a longer word.
        eq = ["whakaemi", "whakaemia", "whakaahu", "whakaahutia", "whakah"]
        self.assertEqual(len(", ".join(eq)), 50)
        self.assertEqual(drop_truncated_tail(eq),
                         ["whakaemi", "whakaemia", "whakaahu", "whakaahutia"])

    def test_a_capped_list_ending_in_a_vowel_is_left_alone(self):
        # Also truncated, but the cut landed on a vowel so the last item may be
        # a whole word. Guessing either way would be inventing.
        eq = ["hoko", "hokona", "tāpae", "tāpaea", "wehe", "wehea", "whakawā"]
        self.assertEqual(drop_truncated_tail(eq), eq)

    def test_a_short_list_ending_in_a_consonant_is_left_alone(self):
        # 'aback' and 'air hostess' are English echoed where Ngata has no Māori
        # equivalent. Nowhere near the cap, so nothing was cut.
        self.assertEqual(drop_truncated_tail(["aback"]), ["aback"])
        self.assertEqual(drop_truncated_tail(["air hostess"]), ["air hostess"])

    def test_a_capped_single_item_becomes_empty(self):
        eq = ["Rā Whakamahara ki nga Hōia o Ahitereiria me Aotear"]
        self.assertEqual(drop_truncated_tail(eq), [])

    def test_a_trailing_affix_hyphen_is_not_truncation(self):
        eq = ["whakaemi", "whakaemia", "whakaahu", "whakaahutia", "whaka-"]
        self.assertEqual(drop_truncated_tail(eq), eq)

    def test_a_macron_vowel_counts_as_a_vowel(self):
        eq = ["whakaemi", "whakaemia", "whakaahu", "whakaahuti", "whakā"]
        self.assertEqual(drop_truncated_tail(eq), eq)

    def test_empty_input(self):
        self.assertEqual(drop_truncated_tail([]), [])
        self.assertEqual(drop_truncated_tail(None), [])


if __name__ == "__main__":
    unittest.main()
