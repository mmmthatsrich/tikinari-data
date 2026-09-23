"""The nine reduplications papakupu marks with a tilde.

Its notation means "append this to the headword". Usually the token is a
suffix — '~a' on 'uku' gives the passive 'ukua'. Nine times it repeats the
headword instead, and 'ue ~ue' gives 'ueue'.

Stored as forms of the base entry, not derivations, because that is what
the notation names: a form on THIS entry, never a claim about another one.
Six of the nine name words papakupu does not hold as headwords, so a
derivation row could not have been written for them at all.

Measured on 2026-09-23 after the rebuild:

    papakupu form rows          796 -> 805
    form_type='reduplication'     0 ->   9
    papakupu suffix refusals     13 ->   4   (5.78% -> 1.85%)

form_type='reduplication' is NOT a corpus-wide count of reduplication.
derivation.process holds 304, and neither is the whole picture: 871
headwords are a stem written twice, and the reduplication spec's §2 shows
why those cannot be harvested.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

EXPECTED = {
    "ueue": "~ue (papakupu)",
    "raurau": "~rau (papakupu)",
    "rourou": "~rou (papakupu)",
    "uiui": "~ui (papakupu)",
    "uwhiuwhi": "~uwhi (papakupu)",
    "hokohokoa": "~hokoa (papakupu)",
    "rouroua": "~roua (papakupu)",
    "uiuia": "~uia (papakupu)",
    "whakamātautau": "~tau (papakupu)",
}


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class ReduplicationForms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _one(self, sql, *a):
        return self.con.execute(sql, a).fetchone()[0]

    def test_there_are_exactly_nine(self):
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form WHERE form_type = 'reduplication'"), 9)

    def test_every_expected_form_is_present_with_its_note(self):
        for form, note in EXPECTED.items():
            with self.subTest(form=form):
                self.assertEqual(self.con.execute(
                    "SELECT note FROM form WHERE form = ? "
                    "AND form_type = 'reduplication'", (form,)).fetchone(),
                    (note,))

    def test_they_all_come_from_papakupu(self):
        self.assertEqual({r[0] for r in self.con.execute(
            "SELECT DISTINCT e.source_id FROM form f "
            "JOIN entry e ON e.id = f.entry_id "
            "WHERE f.form_type = 'reduplication'")}, {"papakupu"})

    def test_each_one_really_repeats_its_own_headword(self):
        # The warrant, asserted rather than trusted: the stored form must
        # start with the entry's own headword. A row that does not is a
        # composition onto the wrong base.
        bad = [r for r in self.con.execute(
            "SELECT e.headword, f.form FROM form f "
            "JOIN entry e ON e.id = f.entry_id "
            "WHERE f.form_type = 'reduplication'")
            if not r[1].startswith(r[0])]
        self.assertEqual(bad, [], f"not built on their headword: {bad}")

    def test_papakupu_form_rows(self):
        # 796 before the reduplications, 805 after them, 809 once the four
        # residual tokens landed (three by ending, one by ruling).
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'papakupu'"), 809)

    def test_the_suffix_forms_were_not_disturbed(self):
        # The reduplication reader must not have claimed any of the suffix
        # reader's tokens. 212 read from fragments, plus the 3 whose class
        # was read off the composed form's ending.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'papakupu' "
            "  AND f.form_type IN ('passive','nominalisation')"), 215)
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'papakupu' AND f.note LIKE '%(papakupu)'"
            "  AND f.form_type IN ('passive','nominalisation')"), 212)

    def test_no_other_source_grew_a_reduplication_type(self):
        # Only papakupu's tilde notation is read this way; a row from
        # anywhere else means the reader was wired too widely.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE f.form_type = 'reduplication' "
            "  AND e.source_id <> 'papakupu'"), 0)

    def test_the_derivation_table_is_untouched(self):
        # These are forms, not derivations. 304 is the reduplication count
        # there and it must not have moved.
        self.assertEqual(self._one(
            "SELECT COUNT(*) FROM derivation WHERE process = 'reduplication'"),
            304)
        self.assertEqual(self._one("SELECT COUNT(*) FROM derivation"), 11444)


if __name__ == "__main__":
    unittest.main()


class ResidualTokens(unittest.TestCase):
    """The last four tokens: three by rule, one by ruling.

    Measured on 2026-09-23:
        papakupu form rows   805 -> 809
        suffix refusals        4 -> 0
    """

    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _row(self, form):
        return self.con.execute(
            "SELECT f.form_type, f.note FROM form f "
            "JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'papakupu' AND f.form = ?",
            (form,)).fetchone()

    def test_a_class_read_off_the_ending_is_marked_as_such(self):
        for form, want in (("meatingia", ("passive", "-ngia (papakupu, by ending)")),
                           ("meatinga", ("nominalisation", "-inga (papakupu, by ending)")),
                           ("whakamātautauranga",
                            ("nominalisation", "-ranga (papakupu, by ending)"))):
            with self.subTest(form=form):
                self.assertEqual(self._row(form), want)

    def test_the_ruled_variant_says_it_was_ruled(self):
        # 'ukui' is another form of 'uku' — the passives are 'ukua' and
        # 'ukuia'. That is the project owner's judgement, not a rule, and
        # the note must not let it read as a reading.
        self.assertEqual(self._row("ukui"), ("variant", "~i (papakupu, ruled)"))

    def test_a_doubling_is_never_also_filed_by_its_ending(self):
        # 'hokohokoa' ends in '-a'. Both readers would take it, and
        # add_form dedups on (entry, form, TYPE), so it landed twice until
        # the readers were made disjoint.
        for form in ("hokohokoa", "rouroua", "uiuia"):
            with self.subTest(form=form):
                self.assertEqual(self.con.execute(
                    "SELECT COUNT(*) FROM form f "
                    "JOIN entry e ON e.id = f.entry_id "
                    "WHERE e.source_id = 'papakupu' AND f.form = ?",
                    (form,)).fetchone()[0], 1)
                self.assertEqual(self._row(form)[0], "reduplication")

    def test_papakupu_now_has_809_form_rows(self):
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
            "WHERE e.source_id = 'papakupu'").fetchone()[0], 809)
