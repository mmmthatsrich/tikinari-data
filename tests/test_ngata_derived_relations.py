"""A base and its own passive are not synonyms.

ngata prints every Māori equivalent of an English lemma in one
comma-separated run, and _wakareo_en_mi used to cross-file that whole run
as mutual synonyms. But the same function already knows which of those
siblings are derivations — it calls suffix_forms.derived_from_list three
lines earlier and writes the pairs as form rows. The run
'ahu, ahutia, ahuna' is one word and two of its passives, not three
synonyms.

These drive the builder against an in-memory database, so no part of the
real pipeline runs. Corpus-wide counts live in
tests/test_ngata_relation_counts.py, which needs a built database.
"""
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

_SPEC = importlib.util.spec_from_file_location(
    "build_unified",
    Path(__file__).parent.parent / "scripts" / "50_build_unified.py")
build_unified = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_unified)


def _memory_db():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE entry (
            id INTEGER PRIMARY KEY, source_id TEXT, source_entry_id TEXT,
            headword TEXT, headword_sort TEXT, headword_search TEXT,
            homonym_no INTEGER, headword_en TEXT, part_of_speech TEXT,
            loan_marker TEXT, dialect TEXT, audio_url TEXT, locator TEXT,
            content_hash TEXT, first_seen TEXT, created_at TEXT,
            last_updated TEXT);
        CREATE TABLE form (
            id INTEGER PRIMARY KEY, entry_id INTEGER, form TEXT,
            form_search TEXT, form_type TEXT, note TEXT);
        CREATE TABLE sense (
            id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
            parent_sense_id INTEGER, gloss_en TEXT, gloss_mi TEXT,
            definition_raw TEXT, part_of_speech TEXT, part_of_speech_en TEXT,
            register TEXT, sort_no INTEGER, note TEXT);
        CREATE TABLE example (
            id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
            text_mi TEXT, text_en TEXT, source_abbrev TEXT, citation TEXT,
            sort_no INTEGER);
        CREATE TABLE relation (
            id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
            target_headword TEXT, target_entry_id INTEGER,
            target_sense_id INTEGER, note TEXT);
        CREATE TABLE ngata_entries (
            id INTEGER PRIMARY KEY, source_entry_id TEXT, wakareo_id TEXT,
            headword TEXT, part_of_speech TEXT, search_scope TEXT,
            equivalents TEXT, qualifier TEXT, example_en TEXT,
            example_mi TEXT, body_text TEXT, body_raw TEXT);
    """)
    return con


class NgataRun(unittest.TestCase):
    """One ngata record, driven through the real builder."""

    def _build(self, equivalents):
        import json
        self.con = _memory_db()
        self.con.execute(
            "INSERT INTO ngata_entries (source_entry_id, wakareo_id, headword, "
            "part_of_speech, search_scope, equivalents, qualifier, example_en, "
            "example_mi, body_text, body_raw) "
            "VALUES ('WR-X.1', '99', 'tend', 'v', '[]', ?, NULL, NULL, NULL, "
            "        NULL, NULL)",
            (json.dumps(equivalents),))
        self.b = build_unified.Builder(self.con, "ngata", None, {})
        build_unified._wakareo_en_mi(self.con, self.b, "ngata_entries")

    def _relations(self):
        return self.con.execute(
            "SELECT e.headword, r.rel_type, r.target_headword "
            "FROM relation r JOIN entry e ON e.id = r.entry_id "
            "ORDER BY e.headword, r.target_headword").fetchall()

    def test_a_passive_is_filed_as_derived_from_its_base(self):
        self._build(["ahu", "ahutia"])
        self.assertEqual(self._relations(),
                         [("ahutia", "derived_from", "ahu")])

    def test_the_base_gets_no_inverse_relation(self):
        # derivation is queryable from either end via base_entry_id, so the
        # inverse row would only duplicate it — and there is no rel_type that
        # says 'has derived form' without inventing one.
        self._build(["ahu", "ahutia"])
        self.assertEqual(
            [r for r in self._relations() if r[0] == "ahu"], [])

    def test_a_genuine_synonym_pair_is_untouched(self):
        # 'whakaranu' and 'pūhui' share no suffix relationship; the run is
        # doing exactly what a synonym run should.
        self._build(["whakaranu", "pūhui"])
        self.assertEqual(self._relations(),
                         [("pūhui", "synonym", "whakaranu"),
                          ("whakaranu", "synonym", "pūhui")])

    def test_a_mixed_run_splits_both_ways(self):
        # The real shape: two words, one of them with a passive. The passive
        # points at its base; the two distinct words stay mutual synonyms.
        self._build(["ahu", "ahutia", "pūhui"])
        self.assertEqual(self._relations(), [
            ("ahu", "synonym", "pūhui"),
            ("ahutia", "derived_from", "ahu"),
            ("ahutia", "synonym", "pūhui"),
            ("pūhui", "synonym", "ahu"),
            ("pūhui", "synonym", "ahutia"),
        ])

    def test_the_derived_relation_resolves_its_target_entry(self):
        # 53_build_word_origin only reads derived_from rows whose
        # target_entry_id is set; an unresolved one would be silently dropped.
        self._build(["ahu", "ahutia"])
        row = self.con.execute(
            "SELECT r.target_entry_id, e.id FROM relation r, entry e "
            "WHERE r.rel_type = 'derived_from' AND e.headword = 'ahu'"
        ).fetchone()
        self.assertIsNotNone(row[0])
        self.assertEqual(row[0], row[1])

    def test_the_form_row_still_records_the_pair_on_the_base(self):
        # The relation change must not cost the form row the app displays.
        self._build(["ahu", "ahutia"])
        self.assertEqual(
            self.con.execute(
                "SELECT f.form, f.form_type, f.note FROM form f "
                "JOIN entry e ON e.id = f.entry_id WHERE e.headword = 'ahu'"
            ).fetchall(),
            [("ahutia", "passive", "-tia (ngata)")])
