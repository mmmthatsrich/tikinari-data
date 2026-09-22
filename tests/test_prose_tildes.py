"""In running prose a tilde means 'or', not a suffix.

papakupu writes its suffix notation into the definition, so the reader
looks there — but the definition is also prose, and papakupu uses '~' in
two other ways inside it:

    (Reduplicated form of puri ~ puru [2])     'puri OR puru'
    tūnga, tūria ~ tūngia, tūranga             'tūria OR tūngia'
    Tuakana / Teina ~ Taina.                   'Teina OR Taina'
    Uri-o-Tai [Personal Noun] Te ~ He hapū     '~' stands in for the headword

Every one of those has a SPACE after the tilde, and every genuine notation
token is tight against it. Measured across papakupu: a spaced tilde yields
0 real suffixes and 5 of these artifacts.

paekupu is NOT tightened. Its notation lives in the headword — a structured
field, not prose — where a space is loose typography rather than a
different meaning: 'āhei ~nga ~ tanga' is just '~tanga' spelled untidily,
and 33 real tokens are written that way.

papakupu also hedges its own entries. 'mānu ~iatia (?)' marks the source's
uncertainty, the same convention te_aka writes as '(-tia?)' and
read_paren_suffixes already refuses.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from suffix_forms import read_tilde_suffixes


class LooseByDefault(unittest.TestCase):
    """paekupu's structured headwords keep tolerating a space."""

    def test_a_tight_token_is_read(self):
        self.assertEqual(read_tilde_suffixes("ahu ~nga"), ["-nga"])

    def test_a_spaced_token_is_still_read(self):
        self.assertEqual(read_tilde_suffixes("āhei ~nga ~ tanga"),
                         ["-nga", "-tanga"])

    def test_the_default_is_unchanged(self):
        # Every existing caller passes no flag and must behave as before.
        self.assertEqual(read_tilde_suffixes("awhi ~hia ~ nga"),
                         ["-hia", "-nga"])


class TightForProse(unittest.TestCase):
    """papakupu's definitions are prose, so a spaced tilde is not notation."""

    def test_a_tight_token_is_still_read(self):
        self.assertEqual(read_tilde_suffixes("~a, ~ria, ~ngia; ~nga wash",
                                             tight=True),
                         ["-a", "-ria", "-ngia", "-nga"])

    def test_an_or_construction_is_refused(self):
        self.assertEqual(
            read_tilde_suffixes("(Reduplicated form of puri ~ puru [2])",
                                tight=True), [])

    def test_an_or_between_two_real_suffix_shapes_is_refused(self):
        # 'tūria ~ tūngia' reads as a choice between two whole forms. The
        # tokens even look suffix-ish, which is why the space has to decide.
        self.assertEqual(
            read_tilde_suffixes("tūnga, tūria ~ tūngia, tūranga stand",
                                tight=True), [])

    def test_a_repetition_mark_is_refused(self):
        self.assertEqual(
            read_tilde_suffixes("Uri-o-Tai [Personal Noun] Te ~ He hapū",
                                tight=True), [])

    def test_a_run_on_entry_inside_the_prose_is_still_read(self):
        # papakupu packs several headwords into one definition field, and
        # those carry real notation. Tightness must not cost them.
        self.assertEqual(
            read_tilde_suffixes("riddle panga, ~a {WMS} throw", tight=True),
            ["-a"])


class SourceHedges(unittest.TestCase):
    """A token the source itself marks uncertain asserts nothing."""

    def test_a_hedged_token_is_refused(self):
        self.assertEqual(
            read_tilde_suffixes("~iatia (?) drift, float", tight=True), [])

    def test_a_hedged_token_among_good_ones_only_costs_itself(self):
        self.assertEqual(
            read_tilde_suffixes("~a, ~tia (?), ~nga wash", tight=True),
            ["-a", "-nga"])

    def test_an_unhedged_token_is_unaffected_by_a_later_question_mark(self):
        # The '(?)' has to follow the token it doubts, not merely appear.
        self.assertEqual(
            read_tilde_suffixes("~tia to do. Origin (?) unclear", tight=True),
            ["-tia"])


if __name__ == "__main__":
    unittest.main()
