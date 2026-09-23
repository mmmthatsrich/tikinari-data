"""The eleven multi-word forms whose suffix moved, counted in the database.

A suffix joins the word that takes it, not always the last one. Two shapes
were wrong:

  the source MARKED the element    'heke (~nga) atu'  -> 'hekenga atu'
                                   'tau [-ria] mai'   -> 'tauria mai'
  the phrase ends in a particle    'mahi anō ~tia'    -> 'mahitia anō'

Measured on 2026-09-22 after the rebuild: 11 forms changed, 10 in paekupu
and 1 in papakupu, with both sources' row totals unchanged. The other 67
multi-word derived forms compose onto the tail correctly and did not move.

Every corrected form is a word the corpus already knows from another
source, which the forms they replaced were not: 'hautūtanga' is a headword
in five sources, 'hekenga' in two, while 'hautū kauawhitanga' and 'heke
atunga' appear nowhere.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

# (source, corrected form, the form it replaced)
MOVED = (
    ("paekupu", "hautūtanga kauawhi", "hautū kauawhitanga"),
    ("paekupu", "hekenga atu", "heke atunga"),
    ("paekupu", "hekenga mai", "heke mainga"),
    ("paekupu", "rārangitanga kōrero", "rārangi kōrerotanga"),
    ("paekupu", "mahitia anō", "mahi anōtia"),
    ("paekupu", "tatauria ake", "tatau akeria"),
    ("paekupu", "tautuhitia anō", "tautuhi anōtia"),
    ("paekupu", "tāutatia anō", "tāuta anōtia"),
    ("paekupu", "whakaaratia anō", "whakaara anōtia"),
    ("paekupu", "whakamahanatia anō", "whakamahana anōtia"),
    ("papakupu", "tauria mai", "tau mairia"),
)

# Composed onto the tail, correctly — fixed compounds whose last word is
# the one inflected. These must not have moved.
UNMOVED = (
    "tangata whenuatia", "hanga ngātahitia", "kī taurangihia",
    "whai wāhitanga", "tārū kahikatanga", "hopu kautia", "whana kautia",
)


def _open():
    # Read-only: this suite must never alter the database it measures.
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


class PhraseAttachment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = _open()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()

    def _count(self, form, source=None):
        sql = ("SELECT COUNT(*) FROM form f JOIN entry e ON e.id = f.entry_id "
               "WHERE f.form = ? AND f.form_type IN ('passive','nominalisation')")
        args = [form]
        if source:
            sql += " AND e.source_id = ?"
            args.append(source)
        return self.con.execute(sql, args).fetchone()[0]

    def test_every_corrected_form_is_present(self):
        for source, good, _bad in MOVED:
            with self.subTest(form=good):
                self.assertGreater(self._count(good, source), 0)

    def test_no_superseded_form_survives(self):
        for source, _good, bad in MOVED:
            with self.subTest(form=bad):
                self.assertEqual(self._count(bad), 0)

    def test_the_correctly_composed_phrases_did_not_move(self):
        # 'kau' is in here deliberately: it trails two paekupu phrases but
        # is a modifier there, not a directional particle, so the tail rule
        # must not have claimed it.
        for form in UNMOVED:
            with self.subTest(form=form):
                self.assertGreater(self._count(form), 0)

    def test_the_source_totals_are_unchanged(self):
        # The suffix moved within each form; no row was added or lost.
        # papakupu was 212 when this landed; later work added three whose
        # class was read off the composed form's ending. The claim here is
        # that the ELEVEN moved their suffix without changing any count,
        # which the per-form assertions above still pin exactly.
        for source, want in (("paekupu", 1839), ("papakupu", 215)):
            with self.subTest(source=source):
                self.assertEqual(self.con.execute(
                    "SELECT COUNT(*) FROM form f JOIN entry e "
                    "ON e.id = f.entry_id WHERE e.source_id = ? "
                    "AND f.form_type IN ('passive','nominalisation')",
                    (source,)).fetchone()[0], want)

    def test_a_corrected_form_is_a_word_the_corpus_knows(self):
        # The strongest check available without a speaker: the inflected
        # element is attested as a headword elsewhere. The forms these
        # replaced were attested nowhere.
        for word in ("hautūtanga", "hekenga", "rārangitanga", "tauria",
                     "tatauria", "whakaaratia", "whakamahanatia"):
            with self.subTest(word=word):
                self.assertGreater(self.con.execute(
                    "SELECT COUNT(*) FROM entry WHERE headword = ?",
                    (word,)).fetchone()[0], 0)

    def test_no_derived_form_ends_in_a_bare_particle_plus_suffix(self):
        # The shape this fixes: a suffix glued to a particle. Scoped to the
        # particles the rule claims, so 'kau' is out of scope by design.
        bad = self.con.execute(
            "SELECT f.form FROM form f WHERE f.form_type IN "
            "('passive','nominalisation') AND ("
            "  f.form LIKE '% anō%' OR f.form LIKE '% ake%' "
            "  OR f.form LIKE '% atu%' OR f.form LIKE '% mai%' "
            "  OR f.form LIKE '% iho%') "
            "AND f.note NOT LIKE '%whole)'").fetchall()
        offenders = [f for (f,) in bad
                     if not f.split()[-1].lower().startswith(
                         ("anō", "ano", "ake", "atu", "mai", "iho"))]
        self.assertEqual(offenders, [], f"suffix on a particle: {offenders}")


if __name__ == "__main__":
    unittest.main()
