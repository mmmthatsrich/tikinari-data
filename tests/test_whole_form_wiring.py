"""build_paekupu writes the whole form verbatim, never composed.

Drives the real builder against an in-memory database, so no part of the
pipeline runs. Corpus counts live in tests/test_whole_forms_corpus.py.
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
    """)
    return con


class AddWholeForms(unittest.TestCase):
    def setUp(self):
        self.con = _memory_db()
        self.b = build_unified.Builder(self.con, "paekupu", None, {})
        self.eid = self.b.add_entry("hau-3", "hau ~hāua ~tanga", "hau", "hau")

    def _rows(self):
        return self.con.execute(
            "SELECT form, form_type, note FROM form ORDER BY form").fetchall()

    def test_the_form_is_stored_exactly_as_printed(self):
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        self.assertEqual(self._rows(), [("hāua", "passive", "-a (paekupu, whole)")])

    def test_the_note_marks_it_as_printed_not_composed(self):
        # The suffix in the note is our inference from the spelling, not a
        # fragment the source wrote; ', whole' is what records that.
        build_unified._add_whole_forms(
            self.b, self.eid, [("motuhanga", "-hanga", "nominalisation")],
            "paekupu")
        self.assertEqual(self._rows()[0][2], "-hanga (paekupu, whole)")

    def test_the_note_still_matches_the_per_suffix_query_shape(self):
        # tests/test_suffix_extraction.py requires every derived form's note
        # to match '-%(%)%'; the per-suffix counts depend on it.
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM form WHERE note NOT LIKE '-%(%)%'"
        ).fetchone()[0], 0)

    def test_a_multi_word_form_is_not_split(self):
        build_unified._add_whole_forms(
            self.b, self.eid, [("kawea atu", "-a", "passive")], "paekupu")
        self.assertEqual(self._rows()[0][0], "kawea atu")

    def test_nothing_is_composed_onto_the_headword(self):
        # The bug this guards: reusing _add_suffix_forms would store
        # 'hauhāua', a word attested nowhere in the corpus.
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        self.assertNotIn("hauhāua", [r[0] for r in self._rows()])

    def test_an_empty_list_writes_nothing(self):
        build_unified._add_whole_forms(self.b, self.eid, [], "paekupu")
        self.assertEqual(self._rows(), [])

    def test_the_row_counter_counts_rows_that_landed(self):
        before = self.b.derived_forms_written
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        build_unified._add_whole_forms(
            self.b, self.eid, [("hāua", "-a", "passive")], "paekupu")
        # add_form dedupes on (entry, form, type): the second is not a row.
        self.assertEqual(self.b.derived_forms_written - before, 1)


class BuildPaekupuWiring(unittest.TestCase):
    """The reader reaches the builder for a real paekupu headword."""

    def setUp(self):
        self.con = _memory_db()
        self.con.executescript("""
            CREATE TABLE paekupu_entries (
                id INTEGER PRIMARY KEY, slug TEXT, headword TEXT,
                headword_sort TEXT, headword_search TEXT, headword_en TEXT,
                part_of_speech TEXT, definition TEXT, definition_mi TEXT,
                usage_examples TEXT, audio_url TEXT, alternative_words TEXT,
                subject_areas TEXT, subject_area TEXT, subject_area_en TEXT);
            CREATE TABLE sense (
                id INTEGER PRIMARY KEY, entry_id INTEGER, sense_number INTEGER,
                parent_sense_id INTEGER, gloss_en TEXT, gloss_mi TEXT,
                definition_raw TEXT, part_of_speech TEXT,
                part_of_speech_en TEXT, register TEXT, sort_no INTEGER,
                note TEXT);
            CREATE TABLE example (
                id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
                text_mi TEXT, text_en TEXT, source_abbrev TEXT,
                citation TEXT, sort_no INTEGER);
            CREATE TABLE relation (
                id INTEGER PRIMARY KEY, entry_id INTEGER, rel_type TEXT,
                target_headword TEXT, target_entry_id INTEGER,
                target_sense_id INTEGER, note TEXT);
            CREATE TABLE entry_domain (
                id INTEGER PRIMARY KEY, sense_id INTEGER, entry_id INTEGER,
                domain TEXT, domain_lang TEXT);
            INSERT INTO paekupu_entries
                (slug, headword, headword_sort, headword_search, headword_en,
                 part_of_speech, definition, definition_mi, usage_examples,
                 audio_url, alternative_words, subject_areas, subject_area,
                 subject_area_en)
            VALUES ('hau-3', 'hau ~hāua ~tanga', 'hau', 'hau', 'wind',
                    'v', NULL, NULL, '[]', NULL, '[]', '[]', NULL, NULL);
        """)
        self.b = build_unified.Builder(self.con, "paekupu", None, {})
        build_unified.build_paekupu(self.con, self.b)

    def test_both_the_composed_and_the_whole_form_are_written(self):
        # '~tanga' is a recognised fragment and composes to 'hautanga';
        # '~hāua' is the whole irregular form. The entry needs both.
        self.assertEqual(
            self.con.execute("SELECT form, form_type, note FROM form "
                             "ORDER BY form").fetchall(),
            [("hautanga", "nominalisation", "-tanga (paekupu)"),
             ("hāua", "passive", "-a (paekupu, whole)")])

    def test_the_entry_still_keys_on_the_bare_base(self):
        # strip_suffix_notation feeds headword_search; the whole form must
        # not leak into it.
        self.assertEqual(self.con.execute(
            "SELECT headword_search FROM entry").fetchone()[0], "hau")


if __name__ == "__main__":
    unittest.main()
