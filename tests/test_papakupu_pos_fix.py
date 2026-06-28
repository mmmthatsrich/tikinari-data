"""Regression tests for scripts/11_papakupu_pos_fix.py (`fix_pos`).

`11_papakupu_pos_fix.py` reconstructs the session-38 inline-POS extraction so a
Papakupu re-import can re-apply it deterministically. These tests pin the two
marker styles, the deliberate exclusions, and the documented whitespace
behaviour (the function strips only the ends — it does NOT reflow internal
whitespace; the 19 session-38 rows that differ do so only by collapsed embedded
newlines, which is cosmetic and intentionally not reproduced).

A final, optional corpus guard re-runs the full nfix -> varstrip diff when the
session-38 DB backups are present locally (they are gitignored, so the test
skips on a clean checkout) and asserts every remaining divergence is
whitespace-only.
"""
import importlib.util
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location(
    "papakupu_pos_fix", ROOT / "scripts" / "11_papakupu_pos_fix.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
fix_pos = _mod.fix_pos


class TestBracketTokens(unittest.TestCase):
    def test_noun_bracket_stripped(self):
        self.assertEqual(fix_pos("score [n.]"), ("score", "Noun"))

    def test_verb_word_bracket(self):
        self.assertEqual(fix_pos("Make to float [verb]"), ("Make to float", "Verb"))

    def test_vt_keeps_following_domain_tag(self):
        self.assertEqual(fix_pos("copy [v.t.] [document etc]"),
                         ("copy [document etc]", "Verb (transitive)"))

    def test_adj_maps_to_stative(self):
        self.assertEqual(fix_pos("confidential [adj.]"), ("confidential", "Stative"))

    def test_adv_maps_to_universal(self):
        self.assertEqual(fix_pos("directly [adv.]"), ("directly", "Universal"))

    def test_malformed_noun_phrase_brace(self):
        self.assertEqual(fix_pos("{Noun phrase] welcome"), ("welcome", "Noun phrase"))


class TestBareLeadingAbbrev(unittest.TestCase):
    def test_universal_u(self):
        self.assertEqual(fix_pos("u. count things"), ("count things", "Universal"))

    def test_vt_lead(self):
        self.assertEqual(fix_pos("v.t. to slice"), ("to slice", "Verb (transitive)"))

    def test_vi_lead(self):
        self.assertEqual(fix_pos("v.i. ebb"), ("ebb", "Verb (intransitive)"))

    def test_n_lead(self):
        self.assertEqual(fix_pos("n. tail"), ("tail", "Noun"))

    def test_v_lead(self):
        self.assertEqual(fix_pos("v. catch"), ("catch", "Verb"))

    def test_adj_lead(self):
        self.assertEqual(fix_pos("adj guiltless"), ("guiltless", "Stative"))

    def test_multi_abbrev_lead_is_universal(self):
        self.assertEqual(fix_pos("adj., v.i. drowned"), ("drowned", "Universal"))
        self.assertEqual(fix_pos("n., v.t. welcome"), ("welcome", "Universal"))


class TestExclusions(unittest.TestCase):
    def test_pron_not_touched(self):
        # 'pron' is intentionally excluded from BRACKET_POS (session 38 left
        # pronoun entries alone).
        self.assertEqual(fix_pos("they [pron]"), ("they [pron]", None))

    def test_domain_tag_kept_no_pos(self):
        self.assertEqual(fix_pos("a serve [tennis]"), ("a serve [tennis]", None))

    def test_skip_prefixes_untouched(self):
        for pref in _mod.SKIP_PREFIXES:
            with self.subTest(pref=pref):
                self.assertEqual(fix_pos(pref + " trailing"), (pref + " trailing", None))

    def test_no_marker_returns_none(self):
        self.assertEqual(fix_pos("plain definition text"), ("plain definition text", None))


class TestWhitespaceBehaviour(unittest.TestCase):
    """Documented decision: fix_pos strips only the ends; internal whitespace
    runs are preserved (NOT reflowed to match session-38's incidental collapse)."""

    def test_internal_newlines_preserved(self):
        nd, pos = fix_pos("v.t. to hang\n\n\nfrom a beam")
        self.assertEqual(pos, "Verb (transitive)")
        self.assertEqual(nd, "to hang\n\n\nfrom a beam")

    def test_ends_are_stripped(self):
        self.assertEqual(fix_pos("n.  tail  "), ("tail", "Noun"))


# --- optional corpus guard: only runs if the session-38 backups are present ---
_NFIX = ROOT / "data" / "maori_dict.db.bak-20260621-140814-nfix"
_VARSTRIP = ROOT / "data" / "maori_dict.db.bak-20260621-143139-varstrip"


@unittest.skipUnless(_NFIX.exists() and _VARSTRIP.exists(),
                     "session-38 DB backups not present (gitignored)")
class TestCorpusGroundTruth(unittest.TestCase):
    def test_reconstruction_matches_session38_modulo_whitespace(self):
        before = sqlite3.connect(_NFIX)
        after = sqlite3.connect(_VARSTRIP)
        brow = {i: d for i, d in before.execute(
            "SELECT id, definition FROM papakupu_entries WHERE part_of_speech IS NULL")}
        arow = {i: (d, p) for i, d, p in after.execute(
            "SELECT id, definition, part_of_speech FROM papakupu_entries")}

        def squash(s):
            return " ".join((s or "").split())

        pos_mismatch = []
        missed = []
        nonws_def = []
        for i, d in brow.items():
            if not d:
                continue
            nd, pos = fix_pos(d)
            gt_def, gt_pos = arow.get(i, (None, None))
            if pos is None:
                # script left it NULL; ground truth must agree (def unchanged, pos NULL)
                if gt_pos is not None or squash(gt_def) != squash(d):
                    missed.append(i)
                continue
            if pos != gt_pos:
                pos_mismatch.append(i)
            elif squash(nd) != squash(gt_def):
                nonws_def.append(i)

        self.assertEqual(missed, [], f"rows session-38 fixed that script misses: {missed}")
        self.assertEqual(pos_mismatch, [], f"POS-value disagreements: {pos_mismatch}")
        self.assertEqual(nonws_def, [],
                         f"non-whitespace definition divergences: {nonws_def}")


if __name__ == "__main__":
    unittest.main()
