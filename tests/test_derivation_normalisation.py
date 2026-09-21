"""The affix is read off the spellings, so the normalisation decides it.

normalise_search_key strips macrons AND collapses doubled vowels. The
collapse is right for Williams, which writes a long vowel as a doubled
letter ('Paaha' is 'pāha'), and wrong wherever a doubled vowel is a morpheme
seam — it turns 'whaka-' into 'whak-' and '-ia' into '-a'.

No single normalisation serves both, so the rule is: try the strict
macron-only fold, and fall back to the collapsing key when it yields
nothing. Measured over all 6,153 rows on this path, 61 change and none
regresses.

See docs/superpowers/specs/2026-09-21-reduplication-design.md §6.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "word_origin",
    Path(__file__).parent.parent / "scripts" / "53_build_word_origin.py")
word_origin = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(word_origin)


class Normalisation(unittest.TestCase):
    """_derivation_shape(child, base) -> (process, affix)."""

    def test_a_seam_is_not_eaten_by_the_prefix(self):
        # 'whaka' + 'aeaea'. Collapsing the seam gives 'whak-', losing the
        # final a of the most productive prefix in the language.
        self.assertEqual(word_origin._derivation_shape("whakaaeaea", "Aeaeā"),
                         ("prefix", "whaka-"))

    def test_a_seam_is_not_eaten_by_the_suffix(self):
        # 'kī' + '-ia'. Collapsing gives '-a', a different suffix, and the
        # per-suffix counts are exactly what this corpus is asked for.
        self.assertEqual(word_origin._derivation_shape("kīia", "kī"),
                         ("suffix", "-ia"))

    def test_a_doubling_across_a_vowel_reads_as_reduplication(self):
        self.assertEqual(word_origin._derivation_shape("awaawa", "Awa"),
                         ("reduplication", None))

    def test_a_plain_doubling_still_reads_as_reduplication(self):
        self.assertEqual(word_origin._derivation_shape("taketake", "take"),
                         ("reduplication", None))

    def test_williams_doubled_vowel_length_still_resolves(self):
        # Williams writes a long vowel doubled: 'Paaha' IS 'pāha'. The strict
        # fold finds nothing here, and the fallback is what keeps the row.
        self.assertEqual(word_origin._derivation_shape("whakapāha", "Paaha"),
                         ("prefix", "whaka-"))

    def test_a_mixed_double_and_macron_base_still_resolves(self):
        self.assertEqual(word_origin._derivation_shape("tiītoretore", "Tītore"),
                         ("suffix", "-tore"))

    def test_a_pair_the_collapse_hid_is_now_seen(self):
        # 'rūnāa' < 'rūnā' folded to the same key and yielded nothing.
        self.assertEqual(word_origin._derivation_shape("rūnāa", "rūnā"),
                         ("suffix", "-a"))

    def test_an_unrelated_pair_still_yields_nothing(self):
        self.assertEqual(word_origin._derivation_shape("kupu", "tangata"),
                         (None, None))


def _db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, headword TEXT,
            loan_marker TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            gloss_en TEXT);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER, note TEXT);
        INSERT INTO entry VALUES (1, 'papakupu', 'ekeeke', NULL),
                                 (2, 'papakupu', 'eke',    NULL),
                                 (3, 'williams', 'hopukia', NULL),
                                 (4, 'williams', 'hopu',    NULL);
        INSERT INTO sense VALUES (10,1,1,NULL),(11,2,1,NULL),
                                 (12,3,1,NULL),(13,4,1,NULL);
        INSERT INTO relation VALUES
            (100, 1, 'derived_from', 'eke',  2, 'reduplication'),
            (101, 3, 'derived_from', 'hopu', 4, NULL);
    """)
    return con


class AssertedProcess(unittest.TestCase):
    def setUp(self):
        self.rows = {r["base_form"]: r
                     for r in word_origin.collect_derivations(_db())}

    def test_the_source_statement_beats_the_spellings(self):
        # describe_derivation reads 'ekeeke' < 'eke' as ('suffix','-ke').
        # papakupu says it is a reduplication, and papakupu is right.
        self.assertEqual(self.rows["eke"]["process"], "reduplication")
        self.assertIsNone(self.rows["eke"]["affix"])

    def test_papakupu_gets_its_own_evidence(self):
        self.assertEqual(self.rows["eke"]["evidence"],
                         "papakupu: stated as a reduplicated form")

    def test_a_stated_reduplication_is_attested_not_segmented(self):
        # The source said so in a sentence, so derived = 0.
        self.assertEqual(
            (self.rows["eke"]["derived"], self.rows["eke"]["confidence"]),
            (0, "certain"))

    def test_a_relation_without_the_marker_still_reads_its_spellings(self):
        self.assertEqual(self.rows["hopu"]["process"], "suffix")
        self.assertEqual(self.rows["hopu"]["evidence"],
                         "williams: printed under this base entry")


if __name__ == "__main__":
    unittest.main()
