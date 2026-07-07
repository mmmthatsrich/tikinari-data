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

    def test_identity_is_not_kinship(self):
        # 'nawai' (Ta. dialect-cognate citation) vs 'Nāwai' (the parent
        # headword): normalise_search_key() maps both to the same key, so
        # the old 'a in b or b in a' test trivially passed on identity alone.
        # A citation restating the parent's own headword is not a
        # derivative and must not split off into its own entry.
        self.assertFalse(wparse._related("nawai", "Nāwai"))

    def test_whaka_stripped_identity_still_passes(self):
        # Must NOT regress: whakawari/Wari become equal only AFTER
        # whaka-stripping, and that must still count as kinship.
        self.assertTrue(wparse._related("whakawari", "Wari"))


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

    def test_pm_branch_pos_embedded_in_bold(self):     # Henumi / whakahenumi
        # Bold carries the sub-headword AND its POS fused together
        # ('<b>whakahenumi, v.t</b>.'), matched via SUBHEAD_POS_RE (the
        # 'pm' branch), after a sentence-final prefix, with a
        # kinship-passing parent.
        p = _p('<p>Kua henumi nga uwhi ki raro ki te whenua. '
               '<b>whakahenumi, v.t</b>. <i>Cause to disappear</i>, etc.</p>')
        frags = wparse._split_midparagraph(p, "Henumi")
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[1]["headword"], "whakahenumi")
        self.assertTrue(frags[1]["head_tail"].lstrip().startswith(", v.t")
                        or frags[1]["head_tail"].lstrip().startswith("v.t"))

    def test_nawai_citation_not_split(self):
        # Reproduces sources/williams/raw/section_N.html around line 1145:
        # a Taranaki dialect-cognate citation '‖ Ta. nawai, v., hold out,
        # last.' inside the paragraph belonging to parent headword 'Nāwai'.
        # normalise_search_key('nawai') == normalise_search_key('Nāwai'), so
        # this must NOT be treated as a derivative sub-headword split.
        p = _p('<p>Nawai i po, i po, a, ka marama (T. 16). '
               '‖ Ta. <b>nawai</b>, v., <i>hold out, last</i>.</p>')
        frags = wparse._split_midparagraph(p, "Nāwai")
        self.assertEqual(len(frags), 1)
        self.assertIsNone(frags[0]["headword"])
        self.assertIn("nawai, v., hold out, last", frags[0]["text"])

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

    def test_mawhitiwhiti_pos_and_sense_number_not_leaked(self):  # bucket D
        # Reproduces sources/williams/raw/section_M.html: 'Mawhiti' governs a
        # bucket-D subx sub-headword whose bold run fuses the sub-headword,
        # its POS, AND the first sense number together:
        # '<b>māwhitiwhiti, n. 1</b>. <i>Grasshopper</i>.' Neither the POS
        # nor the '1' may leak into the gloss; the multi-sense structure of
        # the second paragraph ('2. A marine crustacean...') is preserved.
        div_html = ('<div class="section"><p class="hang">'
                    '<span class="foreign bold" lang="mi">Mawhiti</span>. '
                    '<b>1</b>. v.i. <i>Leap, skip</i>.</p>'
                    '<p><b>māwhitiwhiti, n. 1</b>. <i>Grasshopper</i>.</p>'
                    '<p><b>2</b>. A marine crustacean. = '
                    '<b>mawhiti, 4</b>.</p></div>')
        es = self._entries(div_html)
        sub = next(e for e in es if e["headword"] == "māwhitiwhiti")
        self.assertEqual(sub["kind"], "subx")
        self.assertEqual(sub["part_of_speech"], "n.")
        self.assertEqual(sub["sense_number"], "1")
        self.assertTrue(sub["definition"].startswith("Grasshopper"), sub["definition"])
        self.assertIn("2. A marine crustacean", sub["definition"])


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
