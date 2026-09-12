"""Build `derivation` and `loan_origin` from what the sources already state.

See docs/WORD_FORMATION_DESIGN.md and docs/LOAN_ORIGIN_DESIGN.md. This is step
1 of both: the attested rows only, `derived = 0`. Nothing here infers a
derivation or an origin — every row exists because a source said so and the
reference already resolves to an entry.

Sources, in order of how much each says:

  derivation
    williams      1,507 `derived_from` relations — Williams prints a derivative
                  inside its base entry's paragraph (D36). Affix and process are
                  read off the two spellings, never guessed.
    te_matatiki   entries with two or more resolved component cross-references
                  — 'Ahopae [aho W.3 "line" pae W.244 "horizontal ridges"]'.
                  Order is the order the source printed them.
    paekupu       the same shape in relation.note — 'wete - to release, set free'

  loan_origin
    paekupu       entry.loan_marker, where it names the language ('reo Wīwī')
                  or the source word ('hammer')
    papakupu      senses glossed 'Eng. shirt' — the only source that names the
                  language every time

  A marker that says only 'borrowed' earns no row: entry.loan_marker already
  records that for 22,832 entries, and Te Aka's 18,439 bare markers would
  swamp the table without answering the question it exists for.

A pure DB -> DB projection, like 52: both tables are deleted and rebuilt in
full, so re-running after a `50_build_unified` is always correct and never
doubles rows.

    py scripts/53_build_word_origin.py            # dry run, print counts
    py scripts/53_build_word_origin.py --write
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH, normalise_search_key
from word_formation import (dedupe_components, describe_derivation,
                            parse_component_note)
from loan_origin import parse_loan_marker, parse_papakupu_loan_gloss


def _first_sense(con):
    """{entry_id: sense_id} for the entry's lowest-numbered sense."""
    out = {}
    for eid, sid in con.execute(
            "SELECT entry_id, id FROM sense "
            "ORDER BY entry_id, COALESCE(sense_number, 0), id"):
        out.setdefault(eid, sid)
    return out


def collect_derivations(con):
    rows = []
    first = _first_sense(con)

    # ── Williams: a sub-entry and the base whose paragraph printed it ────────
    for eid, child, base_eid, base_form in con.execute(
            "SELECT r.entry_id, e.headword, r.target_entry_id, r.target_headword "
            "  FROM relation r JOIN entry e ON e.id = r.entry_id "
            " WHERE r.rel_type = 'derived_from' AND r.target_entry_id IS NOT NULL"):
        process, affix = describe_derivation(normalise_search_key(child),
                                             normalise_search_key(base_form))
        rows.append({
            "entry_id": eid, "sense_id": first.get(eid),
            "base_entry_id": base_eid, "base_sense_id": first.get(base_eid),
            "base_form": base_form, "base_gloss": None,
            "position": None, "process": process, "affix": affix,
            "evidence": "williams: printed under this base entry",
            "derived": 0, "confidence": "certain",
        })

    # ── Te Matatiki and Paekupu: components of a coined term, in order ───────
    # Two or more resolved component references is what distinguishes a
    # decomposition from a single 'see also'.
    for source, evidence in (
            ("te_matatiki", "te_matatiki: bracketed source components"),
            ("paekupu", "paekupu: component note")):
        by_entry = {}
        for eid, target_eid, target_hw, note in con.execute(
                "SELECT r.entry_id, r.target_entry_id, r.target_headword, r.note "
                "  FROM relation r JOIN entry e ON e.id = r.entry_id "
                " WHERE e.source_id = ? AND r.rel_type = 'cross_ref' "
                "   AND r.target_entry_id IS NOT NULL ORDER BY r.id", (source,)):
            by_entry.setdefault(eid, []).append((target_eid, target_hw, note))
        for eid, parts in by_entry.items():
            parts = dedupe_components(parts)
            if len(parts) < 2:
                continue                     # one reference is a cross-reference
            for i, (target_eid, target_hw, note) in enumerate(parts, start=1):
                parsed = parse_component_note(note)
                form = (parsed[0] if parsed else None) or target_hw
                gloss = parsed[1] if parsed else None
                rows.append({
                    "entry_id": eid, "sense_id": first.get(eid),
                    "base_entry_id": target_eid,
                    "base_sense_id": first.get(target_eid),
                    "base_form": form, "base_gloss": gloss,
                    "position": i, "process": "compound", "affix": None,
                    "evidence": evidence, "derived": 0, "confidence": "certain",
                })
    return rows


def collect_loan_origins(con):
    rows = []
    first = _first_sense(con)

    for eid, source_id, marker in con.execute(
            "SELECT id, source_id, loan_marker FROM entry "
            " WHERE loan_marker IS NOT NULL"):
        parsed = parse_loan_marker(marker)
        if not parsed:
            continue
        # A row carrying neither a language nor a source word says only
        # 'borrowed', which entry.loan_marker already says. Te Aka's 18,439
        # bare markers would swamp the table twenty to one and answer nothing.
        # This table is for the ORIGIN; the fact of borrowing stays on entry.
        if not (parsed["source_lang"] or parsed["source_word"]):
            continue
        rows.append({
            "entry_id": eid, "sense_id": None,
            "source_lang": parsed["source_lang"],
            "source_word": parsed["source_word"], "source_gloss": None,
            "via_lang": None,
            "evidence": f"{source_id}: entry loan marker {marker!r}",
            "derived": 0,
            "confidence": "certain" if parsed["source_lang"] else "probable",
        })

    # Papakupu is the only source that names the language every time.
    for sid, eid, gloss in con.execute(
            "SELECT s.id, s.entry_id, s.gloss_en FROM sense s "
            "  JOIN entry e ON e.id = s.entry_id "
            " WHERE e.source_id = 'papakupu' AND s.gloss_en LIKE 'Eng.%'"):
        parsed = parse_papakupu_loan_gloss(gloss)
        if not parsed:
            continue
        rows.append({
            "entry_id": eid, "sense_id": sid,
            "source_lang": parsed["source_lang"],
            "source_word": parsed["source_word"],
            "source_gloss": parsed["gloss"], "via_lang": None,
            "evidence": "papakupu: gloss opens 'Eng.'",
            "derived": 0, "confidence": "certain",
        })
    return rows


def run(write: bool) -> None:
    con = sqlite3.connect(DB_PATH)
    derivations = collect_derivations(con)
    loans = collect_loan_origins(con)

    def _tally(rows, key):
        seen = {}
        for r in rows:
            seen[r[key]] = seen.get(r[key], 0) + 1
        return sorted(seen.items(), key=lambda x: -x[1])

    print(f"derivation rows: {len(derivations):,}")
    for k, n in _tally(derivations, "evidence"):
        print(f"    {k:52s} {n:6,}")
    print("  by process:", _tally(derivations, "process"))
    print(f"\nloan_origin rows: {len(loans):,}")
    for k, n in _tally(loans, "source_lang"):
        print(f"    source_lang {str(k):32s} {n:6,}")

    if not write:
        print("\n(dry run — pass --write to persist)")
        con.close()
        return

    con.execute("DELETE FROM derivation")
    con.execute("DELETE FROM loan_origin")
    con.executemany(
        "INSERT INTO derivation (entry_id, sense_id, base_entry_id, base_sense_id,"
        " base_form, base_gloss, position, process, affix, evidence, derived,"
        " confidence) VALUES (:entry_id, :sense_id, :base_entry_id, :base_sense_id,"
        " :base_form, :base_gloss, :position, :process, :affix, :evidence,"
        " :derived, :confidence)", derivations)
    con.executemany(
        "INSERT INTO loan_origin (entry_id, sense_id, source_lang, source_word,"
        " source_gloss, via_lang, evidence, derived, confidence)"
        " VALUES (:entry_id, :sense_id, :source_lang, :source_word, :source_gloss,"
        " :via_lang, :evidence, :derived, :confidence)", loans)
    con.commit()
    print(f"\nWrote derivation={len(derivations):,} loan_origin={len(loans):,}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="persist to the DB")
    run(ap.parse_args().write)
