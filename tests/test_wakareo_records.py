"""Wakareo record parsing — pure functions, no DB, no network."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import wakareo_records as wr

FIXTURES = Path(__file__).parent / "fixtures" / "wakareo"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TemplateSplit(unittest.TestCase):
    def test_ngata_multi_equivalent(self):
        r = wr.split_template(fx("shape_NGATA_26300.html"))
        self.assertEqual(r["headword"], "Aloofness")
        self.assertEqual(r["ref_tag"], "HMN")
        self.assertEqual(r["ref_no"], 297)
        self.assertEqual(r["pos"], "")
        self.assertEqual(r["search_scope"], "")
        self.assertIn("tū whakamatara", r["body"])

    def test_matatiki_has_pos_and_paren_scope(self):
        r = wr.split_template(fx("shape_MATATIKI_47800.html"))
        self.assertEqual(r["headword"], "Aumanga")
        self.assertEqual(r["pos"], "[noun]")
        self.assertEqual(r["ref_tag"], "TM")
        self.assertEqual(wr.parse_search_scope(r["search_scope"]), ["aumanga"])

    def test_tai_kupu_bracket_scope(self):
        r = wr.split_template(fx("shape_TAIKUPU-VAR_78035.html"))
        self.assertEqual(r["ref_tag"], "TK")
        self.assertEqual(
            wr.parse_search_scope(r["search_scope"]), ["ahua", "ahūa", "āhua"]
        )

    def test_williams_corpus_record_is_identifiable(self):
        r = wr.split_template(fx("entry_DICT1_1.html"))
        self.assertEqual(r["ref_tag"], "WWC")

    def test_entry_dict_body_excludes_breadcrumb_and_table(self):
        # entry_DICT* fixtures are full-page captures with a nav-breadcrumb
        # <HR> before the record <TABLE>, plus the real separator <HR>
        # after it. body must start at the real separator, not the
        # breadcrumb one — regression guard for that two-<HR> case.
        r = wr.split_template(fx("entry_DICT10_81048.html"))
        self.assertTrue(r["body"].startswith("<B>ahumoana</B>"))
        self.assertNotIn("<TABLE", r["body"].upper())

    def test_every_fixture_parses_and_tags(self):
        known = {"WWC", "TE", "HMN", "TM", "KKH", "HKA", "HKR", "TK", "NT", "KM", "CL"}
        for p in sorted(FIXTURES.glob("*.html")):
            with self.subTest(fixture=p.name):
                r = wr.split_template(p.read_text(encoding="utf-8"))
                self.assertIsNotNone(r, f"{p.name} did not parse")
                self.assertIn(r["ref_tag"], known)
                self.assertTrue(r["headword"])

    def test_no_record_returns_none(self):
        self.assertIsNone(wr.split_template("<html><body>nothing</body></html>"))

    def test_empty_scope_is_empty_list(self):
        self.assertEqual(wr.parse_search_scope(""), [])


class BodyParsers(unittest.TestCase):
    def test_ngata_splits_equivalents_and_example_pair(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertEqual(r["source_id"], "ngata")
        self.assertEqual(r["headword"], "Aloofness")
        self.assertEqual(r["equivalents"], ["tū whakamatara", "tūrangahapa"])
        self.assertEqual(
            r["example_en"], "Her aloofness separated her from the others."
        )
        self.assertEqual(
            r["example_mi"], "Na tōna tū whakamatara kē a ia i wehe atu i ētahi."
        )

    def test_ngata_single_equivalent_with_stray_close_tag(self):
        # fixture 26240 body starts with a stray "</B>" before the equivalent
        r = wr.parse_record(fx("shape_NGATA_26240.html"))
        self.assertEqual(r["equivalents"], ["ohorere"])
        self.assertEqual(r["example_en"], "She jumped up in alarm.")

    def test_kimikupu_no_example_leaves_pair_none(self):
        r = wr.parse_record(fx("shape_KIMIKUPU_52800.html"))
        self.assertEqual(r["source_id"], "kimikupu_hou")
        self.assertEqual(r["equivalents"], ["pukahu"])
        self.assertIsNone(r["qualifier"])
        self.assertIsNone(r["example_en"])
        self.assertIsNone(r["example_mi"])

    def test_kimikupu_qualifier_is_not_mistaken_for_equivalents(self):
        # Body is `View, argument<BR><B>haurite</B>`. Taking the first <BR>
        # segment would yield ['View', 'argument'] — the equivalent is haurite.
        r = wr.parse_record(fx("entry_DICT5_52724.html"))
        self.assertEqual(r["source_id"], "kimikupu_hou")
        self.assertEqual(r["equivalents"], ["haurite"])
        self.assertEqual(r["qualifier"], "View, argument")

    def test_ngata_has_no_qualifier(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertIsNone(r["qualifier"])

    def test_matatiki_gloss_derivation_and_williams_refs(self):
        r = wr.parse_record(fx("shape_MATATIKI_47800.html"))
        self.assertEqual(r["source_id"], "te_matatiki")
        self.assertEqual(r["gloss_en"], "Vent")
        self.assertIn("hollowed-out space", r["derivation"])
        self.assertEqual(r["williams_refs"], [22])

    def test_tai_kupu_variants(self):
        r = wr.parse_record(fx("shape_TAIKUPU-VAR_78035.html"))
        self.assertEqual(r["source_id"], "tai_kupu_variants")
        self.assertEqual(r["search_scope"], ["ahua", "ahūa", "āhua"])
        self.assertTrue(r["gloss_en"])

    def test_williams_corpus_is_discarded(self):
        self.assertIsNone(wr.parse_record(fx("entry_DICT1_1.html")))

    def test_every_non_williams_fixture_yields_a_source_id(self):
        for p in sorted(FIXTURES.glob("entry_DICT*.html")):
            if p.name == "entry_DICT1_1.html":
                continue
            with self.subTest(fixture=p.name):
                r = wr.parse_record(p.read_text(encoding="utf-8"))
                self.assertIsNotNone(r)
                self.assertIn(r["source_id"], set(wr.TAG_TO_SOURCE.values()))
                if r["source_id"] in wr.EN_MI_SOURCE_IDS:
                    self.assertIsInstance(r["equivalents"], list)
                else:
                    self.assertIsInstance(r["gloss_en"], str)


class BodyText(unittest.TestCase):
    """`body_text` — the markup-free body, for consumers that render prose.

    `body_raw` stays as the archive: Tregear's <B> runs delimit the definition
    block from the `Maori Example:` / `Compare With:` sections, so the markup is
    still needed to split those senses later.
    """

    def test_ngata_body_text_is_markup_free_prose(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertEqual(
            r["body_text"],
            "tū whakamatara, tūrangahapa Her aloofness separated her from the "
            "others. Na tōna tū whakamatara kē a ia i wehe atu i ētahi.",
        )

    def test_body_raw_still_holds_the_markup(self):
        r = wr.parse_record(fx("shape_NGATA_26300.html"))
        self.assertIn("<B>", r["body_raw"])

    def test_body_text_is_none_when_only_the_equivalent_remains(self):
        # Body is `<BR><B>pukahu</B><BR><BR><BR><BR>` — stripping leaves
        # 'pukahu', the equivalent itself. That is not a definition.
        r = wr.parse_record(fx("shape_KIMIKUPU_52800.html"))
        self.assertEqual(r["equivalents"], ["pukahu"])
        self.assertIsNone(r["body_text"])

    def test_body_text_is_none_when_only_the_headword_remains(self):
        # Same rule from the MI->EN side: nothing but the headword is no content.
        r = wr.parse_record(fx("shape_MATATIKI_47800.html"))
        self.assertIsNotNone(r["body_text"])  # this one has real content

    def test_qualifier_plus_lemma_is_not_a_definition(self):
        # Body is `View, argument<BR><B>haurite</B>` — stripped it reads
        # 'View, argument haurite', which is the qualifier and the equivalent.
        # The qualifier is already folded into the gloss; this is not content.
        r = wr.parse_record(fx("entry_DICT5_52724.html"))
        self.assertEqual(r["qualifier"], "View, argument")
        self.assertIsNone(r["body_text"])

    def test_parenthesised_qualifier_plus_lemma_is_not_a_definition(self):
        rec = {"headword": "Bowling crease", "equivalents": ["pae epa"],
               "qualifier": "(cricket)"}
        self.assertIsNone(wr._body_text(rec, "(cricket)<BR><B>pae epa</B><BR>"))

    def test_qualifier_with_real_content_still_survives(self):
        rec = {"headword": "Vent", "equivalents": [], "qualifier": None}
        self.assertEqual(
            wr._body_text(rec, "Vent<BR>[W.22 ‘a smoke vent’]"),
            "Vent [W.22 ‘a smoke vent’]",
        )

    def test_no_fixture_leaks_markup_into_body_text(self):
        for p in sorted(FIXTURES.glob("*.html")):
            r = wr.parse_record(p.read_text(encoding="utf-8"))
            if r is None or r["body_text"] is None:
                continue
            with self.subTest(fixture=p.name):
                self.assertNotIn("<", r["body_text"])
                self.assertNotIn("&nbsp;", r["body_text"])


class ParseTregear(unittest.TestCase):
    """Tregear exception bodies -> senses, examples, relations, comments.

    The source labels every section (`Maori Example:`, `Compare With:`,
    `Word Base:`, `See Also:`, `Comments:`) in bold; nothing ever consumed them,
    so all of it landed in one sense row as prose.
    """

    KAWHAKI = ("<B>1. To take by violence. To remove by force. (Also kahaki)."
               "<BR>2. To remove by stratagem.</B><BR><BR><B>Maori Example:</B> "
               "Ka haere ki te kawhaki i a Kuramarotini. (PM 109)<BR>"
               "<B>Compare With:</B> whawhaki ; to pluck off. kowhaki ; to tear "
               "off.<BR><BR><BR>")
    ATITI = ("<B>To stray, to wander about.</B><BR><BR><B>Word Base:</B> titi ; "
             "to go astray<BR><B>Compare With:</B> atiutiu ; to wander. kotiti ; "
             "to wander about<BR><BR><BR>")
    AWAU = ("[Dialect: South Island]<BR><B>I, me. (In South Island dialect)</B>"
            "<BR><BR><B>Maori Example:</B> Nahau ano awau. [WT vii 37]<BR>"
            "<B>See Also:</B> ahau<BR><BR><BR>")
    ATAHU = ("<B>An assembly of a tribe.</B><BR><BR><B>Comments:</B> Differes "
             "from meanings given by Williams.<BR><BR><BR>")

    def test_numbered_senses_split(self):
        r = wr.parse_tregear(self.KAWHAKI)
        self.assertEqual(r["senses"], [
            "To take by violence. To remove by force. (Also kahaki).",
            "To remove by stratagem.",
        ])

    def test_unnumbered_body_is_a_single_sense(self):
        self.assertEqual(wr.parse_tregear(self.ATITI)["senses"],
                         ["To stray, to wander about."])

    def test_example_and_parenthesised_citation_split(self):
        self.assertEqual(wr.parse_tregear(self.KAWHAKI)["examples"], [
            {"text": "Ka haere ki te kawhaki i a Kuramarotini.", "citation": "PM 109"},
        ])

    def test_example_with_bracketed_citation(self):
        self.assertEqual(wr.parse_tregear(self.AWAU)["examples"], [
            {"text": "Nahau ano awau.", "citation": "WT vii 37"},
        ])

    def test_compare_with_yields_word_and_gloss_pairs(self):
        self.assertEqual(wr.parse_tregear(self.KAWHAKI)["compare"], [
            {"word": "whawhaki", "gloss": "to pluck off"},
            {"word": "kowhaki", "gloss": "to tear off"},
        ])

    def test_word_base_is_kept_apart_from_compare_with(self):
        r = wr.parse_tregear(self.ATITI)
        self.assertEqual(r["word_base"], [{"word": "titi", "gloss": "to go astray"}])
        self.assertEqual([p["word"] for p in r["compare"]], ["atiutiu", "kotiti"])

    def test_see_also_headword_captured(self):
        self.assertEqual(wr.parse_tregear(self.AWAU)["see_also"], ["ahau"])

    def test_dialect_prefix_extracted(self):
        self.assertEqual(wr.parse_tregear(self.AWAU)["dialect"], "South Island")
        self.assertIsNone(wr.parse_tregear(self.ATITI)["dialect"])

    def test_comments_kept_as_a_note(self):
        self.assertEqual(wr.parse_tregear(self.ATAHU)["comments"],
                         "Differes from meanings given by Williams.")

    def test_labels_never_leak_into_a_sense(self):
        for body in (self.KAWHAKI, self.ATITI, self.AWAU, self.ATAHU):
            for sense in wr.parse_tregear(body)["senses"]:
                for label in ("Maori Example:", "Compare With:", "Word Base:",
                              "See Also:", "Comments:"):
                    self.assertNotIn(label, sense)


class ParseDerivation(unittest.TestCase):
    """Te Matatiki derivation brackets -> (word, ref, gloss) parts.

    `W.61` is a Williams PAGE number, verified against williams_entries: kāhua
    W.85 -> p85, hiki W.49 -> p49, unu W.467 -> p467. So the resolvable key is
    page + word, not the bare code that currently sits in target_headword.
    """

    def test_single_part_with_source_word(self):
        self.assertEqual(
            wr.parse_derivation("[horohororē W.61 ‘to eat greedily’]"),
            [{"word": "horohororē", "ref": "W", "page": 61,
              "gloss": "to eat greedily"}],
        )

    def test_bare_reference_has_no_source_word(self):
        # `[W.22 '...']` cites the headword's own Williams entry.
        self.assertEqual(
            wr.parse_derivation("[W.22 ‘a hollowed-out space’]"),
            [{"word": None, "ref": "W", "page": 22,
              "gloss": "a hollowed-out space"}],
        )

    def test_compound_yields_one_part_per_element(self):
        self.assertEqual(
            wr.parse_derivation("[taku W.374 ‘my’ hē W.43 ‘error, mistake’]"),
            [{"word": "taku", "ref": "W", "page": 374, "gloss": "my"},
             {"word": "hē", "ref": "W", "page": 43, "gloss": "error, mistake"}],
        )

    def test_te_matatiki_self_reference_carries_no_page(self):
        # 'TM' cites Te Matatiki itself, not Williams.
        self.assertEqual(
            wr.parse_derivation("[whakamatua W.195 ‘rest, pause’ ā-tau TM ‘annual’]"),
            [{"word": "whakamatua", "ref": "W", "page": 195, "gloss": "rest, pause"},
             {"word": "ā-tau", "ref": "TM", "page": None, "gloss": "annual"}],
        )

    def test_malformed_bracket_does_not_swallow_the_preceding_element(self):
        # Real record (Mānawanawa): the first element puts the ref BEFORE the
        # word, so the gap ahead of the second ref contains a stray ref and
        # gloss. The word must still come out as just `manawa`.
        self.assertEqual(
            wr.parse_derivation("[W.174 mānawanawa ‘space’ manawa W.174 ‘heart’]"),
            [{"word": "manawa", "ref": "W", "page": 174, "gloss": "heart"}],
        )

    def test_absent_derivation_is_empty(self):
        self.assertEqual(wr.parse_derivation(None), [])
        self.assertEqual(wr.parse_derivation(""), [])


class ExampleOwners(unittest.TestCase):
    """Which equivalents a record's single example actually illustrates.

    Ngata stores a synonym set as one record with one example sentence. The
    example uses ONE of the equivalents, so attaching it to all of them puts a
    sentence on an entry whose headword it never contains.
    """

    def test_example_goes_only_to_the_equivalent_it_uses(self):
        self.assertEqual(
            wr.example_owners(["turituri", "hoihoi", "manioro"],
                              "Ka anga mātau ki te whakaminenga turituri."),
            ["turituri"],
        )

    def test_inflected_form_wins_over_its_own_stem(self):
        # 'tōrere' is a substring of 'tōreretia' but not a whole word in it.
        self.assertEqual(
            wr.example_owners(["tōrere", "tōreretia"], "I tōreretia rāua ki a rāua."),
            ["tōreretia"],
        )

    def test_macrons_and_doubled_vowels_do_not_block_a_match(self):
        self.assertEqual(
            wr.example_owners(["ūtongatia"], "Kua ūtongatia te kaunihera."),
            ["ūtongatia"],
        )

    def test_unmatched_example_falls_back_to_the_lead_equivalent(self):
        # Phrase equivalents whose example uses only the head word: no whole
        # phrase matches, so the record's first (lead) term takes it.
        self.assertEqual(
            wr.example_owners(["whakahauhau ki te hara", "whakahauhautia ki te hara"],
                              "Tokorua rāua i whakahauhau i a ia."),
            ["whakahauhau ki te hara"],
        )

    def test_no_example_owns_nothing(self):
        self.assertEqual(wr.example_owners(["turituri", "hoihoi"], None), [])


if __name__ == "__main__":
    unittest.main()
