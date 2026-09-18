"""Splitting a He Pātaka Kupu <strong> into its suffixes and its domain.

The parser has always read this element — it regexes the bracket out for
semantic_domain — and has always thrown the suffixes in front of it away.
Every string below is verbatim from sources/hepataka/raw/.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from hepataka_suffixes import split_strong


class SplitStrong(unittest.TestCase):
    def test_five_suffixes_and_a_domain(self):
        # sources/hepataka/raw/100.html
        text = ("\n   -tia -hia -ngia -tanga -nga\n   [Tūmatauenga]      ")
        self.assertEqual(split_strong(text),
                         (["-tia", "-hia", "-ngia", "-tanga", "-nga"],
                          "Tūmatauenga"))

    def test_two_suffixes_and_a_domain(self):
        # sources/hepataka/raw/1993.html — the 'kake' page
        self.assertEqual(split_strong("\n   -a -nga\n   [Tāne]   "),
                         (["-a", "-nga"], "Tāne"))

    def test_a_domain_with_no_suffixes(self):
        # 8,368 pages look like this. It is not an error.
        self.assertEqual(split_strong("\n   \n   [Tangaroa]   "),
                         ([], "Tangaroa"))

    def test_no_bracket_at_all(self):
        self.assertEqual(split_strong("   -tia   "), (["-tia"], None))

    def test_empty_and_none(self):
        self.assertEqual(split_strong(""), ([], None))
        self.assertEqual(split_strong(None), ([], None))

    def test_a_malformed_token_survives_the_split(self):
        # '-bga' is a typo for '-nga' in hepatakakupu's own text. Parse records
        # what the source wrote; the vocabulary filter at unify refuses it and
        # the refusal report counts it. Dropping it here would hide it.
        self.assertEqual(split_strong(" -bga [Tāne] "), (["-bga"], "Tāne"))

    def test_nothing_after_the_bracket_is_taken_as_a_suffix(self):
        # A hyphen inside the domain text must not become a token.
        self.assertEqual(split_strong(" -a [Tāne-nui] "), (["-a"], "Tāne-nui"))

    def test_macrons_are_preserved_in_a_token(self):
        self.assertEqual(split_strong(" -hangā [Tāne] "), (["-hangā"], "Tāne"))
