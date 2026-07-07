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


class TestRelated(unittest.TestCase):
    def test_all_targets_pass(self):
        pairs = [("whakahinuhinu", "Hinu"), ("tohunga", "Tohu"),
                 ("taitaiao", "Taiao"), ("wariwari", "whakawari"),
                 ("tiītoretore", "Tītore"), ("ihonga", "Iho"),
                 ("whakatūpererū", "Tūpererū"),
                 ("ngingita", "Ngita"), ("tāraharaha", "Tarahanga")]
        for cand, parent in pairs:
            self.assertTrue(wparse._related(cand, parent), (cand, parent))

    def test_unrelated_word_fails(self):
        self.assertFalse(wparse._related("kereru", "Hinu"))
        self.assertFalse(wparse._related("titoki", "Topi"))


class TestMidParagraphSplit(unittest.TestCase):
    def test_bucket_a_bold_after_sentence(self):     # Hinu / whakahinuhinu
        p = _p('<p>Ka ki te taha i te hinu ka whaiwaewaetia, ka tataia ki te '
               'huruhuru kereru. <b>whakahinuhinu</b>, a. <i>Glossy</i>.</p>')
        frags = wparse._split_midparagraph(p, "Hinu")
        self.assertEqual(len(frags), 2)
        self.assertIsNone(frags[0]["headword"])
        self.assertTrue(frags[0]["text"].endswith("kereru."))
        self.assertEqual(frags[1]["headword"], "whakahinuhinu")
        self.assertIn("Glossy", frags[1]["text"])
        self.assertTrue(frags[1]["head_tail"].lstrip().startswith(", a.")
                        or frags[1]["head_tail"].lstrip().startswith("a."))

    def test_bucket_b_two_heads_in_one_bold(self):   # Topi / kopi. topitopi
        p = _p('<p class="hang"><span class="foreign bold" lang="mi">Topi'
               '</span>, v.i. <i>Shut</i>, as the mouth or hand. '
               '‖ <b>kopi. topitopi</b>, n. <i>Alectryon excelsum</i>, '
               'a tree. (Tar.) = <b>titoki</b>.</p>')
        frags = wparse._split_midparagraph(p, "Topi")
        self.assertEqual(len(frags), 2)
        self.assertTrue(frags[0]["text"].rstrip().endswith("kopi."))
        self.assertEqual(frags[1]["headword"], "topitopi")
        self.assertIn("Alectryon", frags[1]["text"])

    def test_bold_xref_not_split(self):              # '= <b>titoki</b>.' stays
        p = _p('<p><b>2</b>. A tree. = <b>titoki</b>.</p>')
        self.assertEqual(len(wparse._split_midparagraph(p, "Topi")), 1)

    def test_unrelated_bold_with_pos_not_split(self):
        p = _p('<p>Some sense. <b>kereru</b>, n. a pigeon aside.</p>')
        self.assertEqual(len(wparse._split_midparagraph(p, "Hinu")), 1)

    def test_mid_sentence_bold_not_split(self):      # no sentence-final prefix
        p = _p('<p>In the expression <b>whakapiri wahine</b>, a charm.</p>')
        self.assertEqual(len(wparse._split_midparagraph(p, "Piri")), 1)

    def test_fragment0_equals_text_content_when_no_split(self):
        p = _p('<p> <b>2</b>. <i>Game</i>, preserved in fat. Kei te tahere.</p>')
        frags = wparse._split_midparagraph(p, "Hinu")
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0]["text"], wparse.clean_text(p.text_content()))

    def test_roman_homonym_restart_suppresses_whole_split(self):
        # houhou/whakahouhou (source_entry_id 1146001): a legit kinship-guarded
        # split candidate (whakahinuhinu) is followed, later in the SAME
        # paragraph, by a capitalized roman-numeral homonym restart ('Hou
        # (vi) = hoi, a. Distant.'). Attribution of text after such a restart
        # is unknowable, so the whole paragraph must stay glued: 1 fragment.
        p = _p('<p>Ka ki te taha i te hinu ka whaiwaewaetia. '
               '<b>whakahinuhinu</b>, a. <i>Glossy</i>. '
               'Hou (vi) = hoi, a. <i>Distant</i>. Kaore he wai.</p>')
        frags = wparse._split_midparagraph(p, "Hinu")
        self.assertEqual(len(frags), 1)
        self.assertIsNone(frags[0]["headword"])
        self.assertEqual(frags[0]["text"], wparse.clean_text(p.text_content()))

    def test_citation_form_does_not_suppress_split(self):
        # '(W. v, 57)' is an ordinary citation, not a homonym restart: the
        # paren holds a comma+page-number, and it isn't preceded by a
        # capitalized Māori word. Must not suppress a legitimate split.
        p = _p('<p>Ka ki te taha i te hinu ka whaiwaewaetia, ka tataia ki te '
               'huruhuru kereru. <b>whakahinuhinu</b>, a. <i>Glossy</i> '
               '(W. v, 57).</p>')
        frags = wparse._split_midparagraph(p, "Hinu")
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[1]["headword"], "whakahinuhinu")


class TestParseSectionDivSubx(unittest.TestCase):
    def _entries(self, div_html):
        div = lhtml.fromstring(div_html)
        return wparse.parse_section_div(div, "T", 1)

    def test_hinu_shape_end_to_end(self):
        div_html = ('<div class="section"><p class="hang">'
                    '<span class="foreign bold" lang="mi">Hinu</span>, n. '
                    '<b>1</b>. <i>Oil, fat</i>.</p>'
                    '<p>Ka ki te taha i te hinu. <b>whakahinuhinu</b>, a. '
                    '<i>Glossy</i>.</p></div>')
        es = self._entries(div_html)
        self.assertEqual([e["headword"] for e in es], ["Hinu", "whakahinuhinu"])
        self.assertEqual(es[1]["kind"], "subx")
        self.assertEqual(es[1]["parent_headword"], "Hinu")
        self.assertEqual(es[1]["part_of_speech"], "a.")
        self.assertNotIn("whakahinuhinu", es[0]["definition"])
        self.assertIn("Glossy", es[1]["definition"])

    def test_rai_plain_paragraph_end_to_end(self):   # bucket C
        div_html = ('<div class="section"><p class="hang">'
                    '<span class="foreign bold" lang="mi">Rai</span>, rarai, a. '
                    '<i>Ribbed, furrowed</i>.</p>'
                    '<p>rainga, n. <i>Undulation</i>.</p></div>')
        es = self._entries(div_html)
        self.assertEqual([e["headword"] for e in es], ["Rai", "rainga"])
        self.assertEqual(es[1]["kind"], "subx")
        self.assertEqual(es[1]["part_of_speech"], "n.")


class TestImportBandIds(unittest.TestCase):
    def test_subx_band(self):
        imp = importlib.import_module("01_williams_import")
        base = {"definition": "x", "part_of_speech": "", "usage_examples": [],
                "cross_refs": [], "sense_number": "", "page_number": 1,
                "source_section": "P"}
        entries = [dict(base, headword="Piri",    kind="main"),
                   dict(base, headword="piriahi", kind="sub"),
                   dict(base, headword="pirix",   kind="subx"),
                   dict(base, headword="Pirir",   kind="main"),
                   dict(base, headword="pirisubx", kind="subx")]
        self.assertEqual(imp.assign_ids(entries),
                         [1, 1000101, 1000151, 2, 1000251])


if __name__ == "__main__":
    unittest.main(verbosity=2)
