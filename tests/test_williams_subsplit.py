#!/usr/bin/env python3
"""Unit tests for the mid-paragraph Williams sub-headword split (post-S65 residue)."""
import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from lxml import html as lhtml

wparse = importlib.import_module("01_williams_parse")


def _p(html):
    """First <p> element of an HTML fragment."""
    return lhtml.fromstring(f"<div>{html}</div>").find("p")


class TestPlainSubhead(unittest.TestCase):
    def test_plain_paragraph_subhead(self):          # bucket C — Rai/rainga
        m = wparse.PLAIN_SUBHEAD_RE.match("rainga, n. Undulation.")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "rainga")

    def test_plain_requires_pos(self):
        self.assertIsNone(wparse.PLAIN_SUBHEAD_RE.match("rainga te mea nui."))

    def test_plain_rejects_capitalised(self):
        self.assertIsNone(wparse.PLAIN_SUBHEAD_RE.match("Ka kite, n. nope."))


class TestPosNumInBold(unittest.TestCase):
    def test_pos_and_sense_number_in_bold(self):     # bucket D — māwhitiwhiti
        p = _p('<p> <b>māwhitiwhiti, n. 1</b>. <i>Grasshopper</i>.</p>')
        got = wparse._sub_headword(p)
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "māwhitiwhiti")

    def test_existing_pos_in_bold_still_works(self):  # S65 case must not regress
        p = _p('<p> <b>whawhango, a</b>. <i>Somewhat hoarse</i>.</p>')
        self.assertEqual(wparse._sub_headword(p)[0], "whawhango")


if __name__ == "__main__":
    unittest.main(verbosity=2)
