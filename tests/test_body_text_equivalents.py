"""A list of equivalents is not a definition, however it is punctuated.

_body_text exists to stop a body that merely restates the lemma reading as
prose. Its docstring is explicit: "Kimikupu Hou bodies are often
`<BR><B>{equivalent}</B><BR><BR>` — stripping leaves the equivalent itself,
which is not a definition and must not read as one."

It compared the stripped body against each lemma INDIVIDUALLY, so a
comma-joined run of several equivalents never matched and survived as
though it were prose. 183 rows kept one — 175 in ngata, 8 in kimikupu_hou —
and they reach about 450 unified senses as a definition:

    Ngahuru mātahi   gloss_en 'April'
                     definition_raw 'Ēperira, Ngahuru mātahi, Paenga whāwhā'

The sources with genuinely definitional bodies are untouched by this:
te_matatiki's 5,097 and tregear's 321 all survive.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from wakareo_records import _body_text


def _rec(headword, equivalents=(), qualifier=None):
    return {"headword": headword, "equivalents": list(equivalents),
            "qualifier": qualifier}


class NotADefinition(unittest.TestCase):
    def test_a_single_equivalent_is_refused(self):
        # The case the function already handled.
        self.assertIsNone(
            _body_text(_rec("Affidavit", ["haurite"]),
                       "<BR><B>haurite</B><BR>"))

    def test_a_joined_run_of_equivalents_is_refused(self):
        self.assertIsNone(
            _body_text(_rec("Accident and emergency", ["hauata", "ohorere"]),
                       "<BR><B>hauata, ohorere</B><BR>"))

    def test_a_three_way_run_is_refused(self):
        self.assertIsNone(
            _body_text(
                _rec("April", ["Ēperira", "Ngahuru mātahi", "Paenga whāwhā"]),
                "<BR><B>Ēperira, Ngahuru mātahi, Paenga whāwhā</B><BR>"))

    def test_a_trailing_comma_does_not_rescue_it(self):
        # ngata's 'Pied tit'. Exact-string matching missed this one.
        self.assertIsNone(
            _body_text(
                _rec("Pied tit", ["kōmiromiro", "North Island kōmiromiro",
                                  "pīrangirangi"]),
                "<BR><B>kōmiromiro, North Island kōmiromiro, pīrangirangi,</B>"))

    def test_a_qualifier_in_front_of_the_run_is_refused(self):
        self.assertIsNone(
            _body_text(_rec("Ball four", ["poiwhā", "hīkoi"], "(take a walk)"),
                       "<BR><B>(take a walk) poiwhā, hīkoi</B><BR>"))

    def test_the_headword_itself_is_still_refused(self):
        self.assertIsNone(
            _body_text(_rec("haurite", ["haurite"]), "<BR><B>haurite</B><BR>"))

    def test_order_does_not_matter(self):
        # The parts are checked as a set, so a reordered run is still a run.
        self.assertIsNone(
            _body_text(_rec("Almond", ["aramona", "amana"]),
                       "<BR><B>amana, aramona</B><BR>"))


class StillADefinition(unittest.TestCase):
    """Real prose must survive. These are the shapes that carry meaning."""

    def test_a_sentence_is_kept(self):
        self.assertEqual(
            _body_text(_rec("whare", ["whare"]),
                       "<B>A building used for meetings.</B>"),
            "A building used for meetings.")

    def test_a_definition_that_merely_mentions_an_equivalent_is_kept(self):
        self.assertEqual(
            _body_text(_rec("Almond", ["aramona"]),
                       "<B>aramona, a nut from a stone fruit</B>"),
            "aramona, a nut from a stone fruit")

    def test_a_run_with_one_non_equivalent_part_is_kept(self):
        # Only ALL parts being lemmas makes it a restatement.
        self.assertEqual(
            _body_text(_rec("Almond", ["aramona", "amana"]),
                       "<B>aramona, amana, a stone fruit</B>"),
            "aramona, amana, a stone fruit")

    def test_a_tregear_style_body_is_kept(self):
        self.assertEqual(
            _body_text(_rec("Ao", []),
                       "<B>Cloud. Cf. aoao, to gather into a heap.</B>"),
            "Cloud. Cf. aoao, to gather into a heap.")

    def test_an_empty_body_is_still_none(self):
        self.assertIsNone(_body_text(_rec("Ao", []), ""))


if __name__ == "__main__":
    unittest.main()
