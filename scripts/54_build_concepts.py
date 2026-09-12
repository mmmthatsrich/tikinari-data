"""Build the concept layer: one word, as eleven dictionaries record it.

See docs/superpowers/specs/2026-09-12-concept-layer-design.md.

Single-source lexemes seed the concepts; cross-source witnesses attach one at
a time on direct evidence to the concept, never transitively. Membership is
keyed on (source_id, source_entry_id, sense_number) so it survives a rebuild,
and rows a human or the sweep has judged are never overwritten.

    py scripts/54_build_concepts.py            # dry run, print counts
    py scripts/54_build_concepts.py --write
"""
import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH
from concept_evidence import SEED_CONFIDENCE, blocks, confidence_for, lexeme_key, positive_evidence


def _norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def load_senses(con, keys=None):
    """{headword_search: [sense-view, ...]} — the universe to be grouped."""
    where, params = "", []
    if keys:
        where = " AND e.headword_search IN (%s)" % ",".join("?" * len(keys))
        params = list(keys)

    examples = defaultdict(set)
    citations = defaultdict(set)
    for sid, text_mi, cit in con.execute(
            "SELECT sense_id, text_mi, citation FROM example"):
        if sid is None:
            continue
        if text_mi and len(text_mi) > 25:
            examples[sid].add(_norm(text_mi))
        if cit:
            citations[sid].add(_norm(cit))

    cognates = defaultdict(set)
    for eid, cs in con.execute(
            "SELECT entry_id, cognateset_id FROM ETY_entry_link"):
        cognates[eid].add(cs)

    cites = defaultdict(set)
    for eid, target in con.execute(
            "SELECT entry_id, target_entry_id FROM relation "
            " WHERE target_entry_id IS NOT NULL"):
        cites[eid].add(target)

    out = defaultdict(list)
    sql = ("SELECT e.id, e.source_id, e.source_entry_id, e.headword, "
           "       e.headword_search, e.locator, e.part_of_speech, "
           "       e.part_of_speech_en, "
           "       s.id, s.sense_number, s.gloss_en, s.gloss_mi, "
           "       s.part_of_speech, s.part_of_speech_en "
           "  FROM sense s JOIN entry e ON e.id = s.entry_id "
           " WHERE e.headword_search IS NOT NULL" + where)
    for (eid, src, seid, hw, hse, locator, epos, epos_en,
         sid, sn, gen, gmi, spos, spos_en) in con.execute(sql, params):
        # Raw part_of_speech is not comparable across sources: hepatakakupu
        # writes Māori abbreviations ('āhua, ing, mahp'), te_matatiki brackets
        # its ('[adjective]'), and te_aka/papakupu differ only in case. The
        # canonical part_of_speech_en columns are the only form the
        # cross-source `blocks()` rule can safely compare, so prefer them.
        pos = spos_en or epos_en or spos or epos
        out[hse].append({
            "member_key": (src, str(seid), sn),
            "source_id": src,
            "entry_id": eid,
            "sense_id": sid,
            "source_entry_id": str(seid),
            "sense_number": sn,
            "headword": hw,
            "headword_search": hse,
            "pos": pos,
            "gloss_en": gen,
            "gloss_mi": gmi,
            "lexeme": lexeme_key(src, seid, hse, locator),
            "cognate_sets": frozenset(cognates.get(eid, ())),
            "examples": frozenset(examples.get(sid, ())),
            "citations": frozenset(citations.get(sid, ())),
            "cites": frozenset(cites.get(eid, ())),
        })
    return dict(out)


def _seed_groups(views):
    """Single-source lexemes, in a stable order — the concepts' starting points.

    Each source groups its own senses into words and that grouping is STATED,
    not inferred, which is why these are trusted where cross-source attachment
    is not.
    """
    groups = defaultdict(list)
    for v in views:
        groups[v["lexeme"]].append(v)
    return [groups[k] for k in sorted(groups, key=lambda k: (str(k),))]


def form_concepts(views):
    """Group one headword key's sense-views into concepts.

    Seeds attach to a concept only on positive evidence linking them to it, and
    only when no block holds against ANY existing member. That second clause is
    the anti-chaining rule: if two words are separated by their own source's
    numbering, no third source compatible with each can later join them.
    """
    concepts = []
    for seed in _seed_groups(views):
        placed = False
        for concept in concepts:
            existing = [m["view"] for m in concept["members"]]

            # A block against any current member rules the whole concept out.
            if any(blocks(s, e) for s in seed for e in existing):
                continue

            evidence = []
            for s in seed:
                for e in existing:
                    found = positive_evidence(s, e)
                    if found:
                        evidence.extend(found)
            if not evidence:
                continue

            seed_conf = min(
                (SEED_CONFIDENCE.get(s["source_id"], "certain") for s in seed),
                key=("uncertain", "probable", "certain").index)
            conf = confidence_for(evidence, [])
            conf = min((conf, seed_conf),
                       key=("uncertain", "probable", "certain").index)
            for s in seed:
                concept["members"].append(
                    {"view": s, "evidence": evidence, "confidence": conf})
            placed = True
            break

        if not placed:
            conf = min(
                (SEED_CONFIDENCE.get(s["source_id"], "certain") for s in seed),
                key=("uncertain", "probable", "certain").index)
            concepts.append({"members": [{"view": s, "evidence": [],
                                          "confidence": conf} for s in seed]})

    for c in concepts:
        c["confidence"] = min((m["confidence"] for m in c["members"]),
                              key=("uncertain", "probable", "certain").index)
    return concepts
