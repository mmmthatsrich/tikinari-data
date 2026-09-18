"""The suffix vocabulary and the morphological test, per
docs/superpowers/specs/2026-09-17-suffix-forms-design.md §2.

The vocabulary here was MEASURED, not recalled: it is the complete set of
well-formed suffix types in hepatakakupu's 22,911 raw tokens. An earlier
draft listed sixteen from memory and dropped -ia, which occurs 236 times.
That is why test_the_vocabulary_is_complete exists — it fails if someone
trims the list back to the ones they remember.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import (PASSIVE, NOMINALISATION, classify, compose,
                          derived_pair, fold)


class Vocabulary(unittest.TestCase):
    def test_the_vocabulary_is_complete(self):
        # Measured from 22,911 hepatakakupu tokens. Removing any of these
        # discards real data; -ia alone accounts for 236 occurrences.
        self.assertEqual(len(PASSIVE), 13)
        self.assertEqual(len(NOMINALISATION), 9)
        for suffix in ("-ia", "-kina", "-whina"):
            self.assertIn(suffix, PASSIVE)
        for suffix in ("-kanga", "-inga", "-unga"):
            self.assertIn(suffix, NOMINALISATION)

    def test_no_suffix_is_in_both_classes(self):
        self.assertEqual(set(PASSIVE) & set(NOMINALISATION), set())

    def test_classify_names_the_class(self):
        self.assertEqual(classify("-tia"), "passive")
        self.assertEqual(classify("-tanga"), "nominalisation")

    def test_an_unknown_suffix_is_refused_not_guessed(self):
        # -bga is a typo for -nga in hepatakakupu's own text. Coercing it to
        # its near neighbour would invent data the source never recorded.
        self.assertIsNone(classify("-bga"))
        self.assertIsNone(classify("-pukenga"))

    def test_classify_does_not_fold(self):
        # classify is the public vocabulary predicate, not a fuzzy match. The
        # corpus has 167 instances of '-ā' inside hyphenated compounds
        # ('tū-ā-nuku', 'matemate-ā-one') that are not suffixes; a folding
        # classify would misclassify them wherever it is called. Folding
        # belongs in the readers that call classify, not in classify itself.
        self.assertIsNone(classify("-ā"))


class MorphologicalTest(unittest.TestCase):
    def test_a_plain_pair(self):
        self.assertEqual(derived_pair("tūkino", "tūkinotia"), "-tia")

    def test_macrons_do_not_block_a_match(self):
        # Williams gives the passive of 'Hi' as 'hīa'. Folding is for the
        # comparison only; callers store the original spelling.
        self.assertEqual(derived_pair("Hi", "hīa"), "-a")

    def test_a_synonym_is_not_a_derived_form(self):
        # ngata lists synonyms and derived forms in one comma-separated run.
        # 'pūhui' does not start with 'whakaranu', so it is a synonym.
        self.assertIsNone(derived_pair("whakaranu", "pūhui"))

    def test_a_shared_prefix_is_not_a_suffix(self):
        # 'pōrahurahu' starts with 'pōrahu' but '-rahu' is not a suffix.
        self.assertIsNone(derived_pair("pōrahu", "pōrahurahu"))

    def test_the_word_itself_is_not_its_own_derived_form(self):
        self.assertIsNone(derived_pair("kake", "kake"))

    def test_the_longest_suffix_wins(self):
        # 'whakamātanga' from 'whakamā' is -tanga, not -anga or -nga.
        self.assertEqual(derived_pair("whakamā", "whakamātanga"), "-tanga")
        # 'arohaina' from 'aroha' is -ina, not -na or -a.
        self.assertEqual(derived_pair("aroha", "arohaina"), "-ina")


class Composition(unittest.TestCase):
    def test_compose_joins_base_and_suffix(self):
        self.assertEqual(compose("kake", "-a"), "kakea")
        self.assertEqual(compose("kake", "-nga"), "kakenga")

    def test_compose_keeps_the_macrons_of_the_base(self):
        self.assertEqual(compose("tūkino", "-tia"), "tūkinotia")


class Folding(unittest.TestCase):
    def test_fold_strips_macrons_and_case(self):
        self.assertEqual(fold("Tūkino"), "tukino")


from suffix_forms import (read_bracket_suffixes, read_paren_suffixes,
                          read_tilde_suffixes, strip_suffix_notation)


class ParenNotation(unittest.TestCase):
    """te_aka and kimikupu_hou: '(-tia)' leading a definition or after a
    headword. Verbatim samples from te_aka_entries.senses."""

    def test_one_suffix(self):
        self.assertEqual(
            read_paren_suffixes("(-tia) to do what? treated in what fashion?"),
            ["-tia"])

    def test_several_suffixes(self):
        self.assertEqual(
            read_paren_suffixes("(-a,-ngia,-ria,-tia) to move in a direction"),
            ["-a", "-ngia", "-ria", "-tia"])

    def test_a_suffix_after_a_headword(self):
        self.assertEqual(read_paren_suffixes("āmine (-tia)"), ["-tia"])

    def test_a_definition_with_no_suffix_yields_nothing(self):
        self.assertEqual(read_paren_suffixes("to climb, ascend."), [])

    def test_a_parenthetical_that_is_not_a_suffix_is_ignored(self):
        # kimikupu_hou files chemistry this way: '(-waro)' is a compound
        # component, not a passive ending.
        self.assertEqual(read_paren_suffixes("hauhā (-waro)"), [])

    def test_an_english_gloss_mentioning_pass_is_not_a_suffix(self):
        self.assertEqual(read_paren_suffixes("to pass. (see also)"), [])


class TildeNotation(unittest.TestCase):
    """paekupu and papakupu: '~nga' standing for headword + -nga. Verbatim
    samples from paekupu_entries.headword and papakupu_entries.definition."""

    def test_one_suffix_in_a_headword(self):
        self.assertEqual(read_tilde_suffixes("ahu ~nga"), ["-nga"])

    def test_a_spaced_tilde_still_reads(self):
        # 'āhei ~nga ~ tanga' occurs in paekupu with a space after the tilde.
        self.assertEqual(read_tilde_suffixes("āhei ~nga ~ tanga"),
                         ["-nga", "-tanga"])

    def test_a_comma_run_in_a_definition(self):
        self.assertEqual(read_tilde_suffixes("~tia, ~tanga (1) beget"),
                         ["-tia", "-tanga"])

    def test_a_semicolon_run_in_a_definition(self):
        # papakupu 'eke': '~a, ~ria, ~ngia; ~nga (1) put oneself on something'
        self.assertEqual(read_tilde_suffixes("~a, ~ria, ~ngia; ~nga (1) put"),
                         ["-a", "-ria", "-ngia", "-nga"])

    def test_a_tilde_meaning_reflects_as_is_refused(self):
        # temarareo uses '~' for 'reflects as', followed by a whole word.
        self.assertEqual(read_tilde_suffixes("Proto-Polynesian ~ kainga"), [])

    def test_a_macrond_tilde_token_is_read(self):
        # paekupu headword 'hanga ~ia ~hangā ~nga': the vocabulary only holds
        # ASCII forms, so a macron'd token must be folded before classifying.
        self.assertEqual(read_tilde_suffixes("hanga ~ia ~hangā ~nga"),
                         ["-ia", "-hanga", "-nga"])


class BracketNotation(unittest.TestCase):
    """papakupu headword: 'tāpiri [-tia]'."""

    def test_a_bracketed_suffix(self):
        self.assertEqual(read_bracket_suffixes("tāpiri [-tia]"), ["-tia"])

    def test_a_bracketed_domain_is_not_a_suffix(self):
        # hepatakakupu files semantic domains this way: '[Tāne]'.
        self.assertEqual(read_bracket_suffixes("kake [Tāne]"), [])


class StripNotation(unittest.TestCase):
    """What the importers key on, per spec §5."""

    def test_a_tilde_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("ahu ~nga"), "ahu")

    def test_a_multi_suffix_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("āhei ~nga ~ tanga"), "āhei")

    def test_a_paren_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("āmine (-tia)"), "āmine")

    def test_a_bracket_headword_strips_to_its_base(self):
        self.assertEqual(strip_suffix_notation("tāpiri [-tia]"), "tāpiri")

    def test_a_clean_headword_is_unchanged(self):
        self.assertEqual(strip_suffix_notation("whakarere"), "whakarere")

    def test_a_multi_word_headword_is_unchanged(self):
        # 'tiki ake' is two words, not a word plus a suffix.
        self.assertEqual(strip_suffix_notation("tiki ake"), "tiki ake")

    def test_a_macrond_suffix_is_stripped(self):
        # The tilde loop's classify guard must fold the same way the reader
        # does, or a macron'd suffix is read but never stripped.
        self.assertEqual(strip_suffix_notation("ahu ~hīa"), "ahu")


from suffix_forms import derived_from_list, read_williams_passives


class NgataEquivalentList(unittest.TestCase):
    """ngata_entries.equivalents is a comma-separated run that mixes
    base+derived pairs with plain synonyms. Verbatim samples."""

    def test_a_base_and_its_passive(self):
        # WR-HMN.58, 'Abuse'
        self.assertEqual(derived_from_list(["tūkino", "tūkinotia"]),
                         [("tūkino", "tūkinotia", "-tia")])

    def test_two_pairs_in_one_run(self):
        # WR-HMN.166, 'Adulterate'
        self.assertEqual(
            derived_from_list(["whakaranu", "whakaranua", "tūkino",
                               "tūkinotia"]),
            [("whakaranu", "whakaranua", "-a"),
             ("tūkino", "tūkinotia", "-tia")])

    def test_a_synonym_run_yields_nothing(self):
        # WR-HMN.1845, 'Compound'. pūhui is another word for the same idea.
        self.assertEqual(derived_from_list(["whakaranu", "pūhui"]), [])

    def test_a_reduplication_is_not_a_derived_form(self):
        self.assertEqual(derived_from_list(["pōrahu", "pōrahurahu"]), [])

    def test_a_single_item_run_yields_nothing(self):
        self.assertEqual(derived_from_list(["whakaranu"]), [])


class WilliamsProse(unittest.TestCase):
    """williams_entries.definition marks the passive in running prose."""

    def test_a_marked_passive(self):
        self.assertEqual(
            read_williams_passives("Aroha",
                                   "1. n. Love, yearning. Pass. arohaina."),
            [("Aroha", "arohaina", "-ina")])

    def test_a_lowercase_marker(self):
        self.assertEqual(
            read_williams_passives("Arahi", "; pass. arahina. 1. Lead."),
            [("Arahi", "arahina", "-na")])

    def test_the_base_may_be_any_comma_part_of_the_headword(self):
        # 'Amu, amuamu' — the passive belongs to the second form.
        self.assertEqual(
            read_williams_passives("Amu, amuamu", "Grumble. Pass. amuamutia."),
            [("amuamu", "amuamutia", "-tia")])

    def test_the_english_verb_pass_is_not_a_marker(self):
        # 'Āianei' ends a sentence with 'pass.' and the next word is English.
        # A naive regex accepts 'Be' here; the morphological test rejects it.
        self.assertEqual(
            read_williams_passives("Āianei", "ad. Now, presently, to pass. Be"),
            [])

    def test_a_definition_with_no_marker_yields_nothing(self):
        self.assertEqual(read_williams_passives("Kake", "Ascend, climb."), [])
