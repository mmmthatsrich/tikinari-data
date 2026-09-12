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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")
from utils import DB_PATH
from concept_election import elect_gloss, elect_headword
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


NOW = datetime.now(timezone.utc).isoformat()

_JUDGED = ("confirmed", "rejected")


def _derived_long(con):
    """Member keys whose word is formed on a base carrying a long vowel.

    derivation (D38) is attested word formation, so where it says hōmai is
    hō + mai the macron is settled by morphology rather than by a vote.

    The test fixture (_fixture_db in tests/test_concept_build.py) has no
    derivation table, so this query is guarded the same way utils._has_table
    and 50_build_unified.delete_source_slice guard optional tables. The
    morphology path itself is unit-tested directly in
    tests/test_concept_election.py.
    """
    out = set()
    try:
        rows = con.execute(
            "SELECT e.source_id, e.source_entry_id, d.base_form "
            "  FROM derivation d JOIN entry e ON e.id = d.entry_id")
    except sqlite3.OperationalError:
        return out
    for src, seid, base in rows:
        if any(ch in "āēīōū" for ch in (base or "").lower()):
            out.add((src, str(seid)))
    return out


def persist(con, concepts):
    """Write concepts, preserving anything a human or the sweep has judged —
    except a judgement whose (source_id, source_entry_id, sense_number) this
    build no longer proposes AND whose source this build proposed something
    else for, which is discarded with it. A source this build proposed
    nothing at all for is not evidence its senses left the corpus — it may be
    a source retired for good, an interrupted or half-built import, or a
    source builder that emitted entries but dropped every sense or its
    headword_search — so a judgement on such a source is left alone rather
    than destroyed. The address is the test, not the grouping: a judgement
    follows its sense across a headword edit that moves it to a different
    concept, and is dropped when the sense is renumbered or leaves the corpus
    while its source stays live."""
    judged = {}
    for cid, src, seid, sn, status, conf in con.execute(
            "SELECT concept_id, source_id, source_entry_id, sense_number, "
            "       status, confidence FROM concept_member "
            " WHERE status IN (?,?)", _JUDGED):
        judged[(src, str(seid), sn)] = (cid, status, conf)

    con.execute("DELETE FROM concept_member_evidence")
    con.execute("DELETE FROM concept_member WHERE status NOT IN (?,?)", _JUDGED)

    long_bases = _derived_long(con)
    counts = {"concepts": 0, "members": 0, "kept": 0, "excluded": 0}
    rebuilt = set()

    for concept in concepts:
        members, rejected = [], []
        for m in concept["members"]:
            rebuilt.add(m["view"]["member_key"])
            if judged.get(m["view"]["member_key"],
                          (None, None, None))[1] == "rejected":
                rejected.append(m)
            else:
                members.append(m)

        # A grouping whose every member has been rejected still gets its
        # concept row. It has no live members, elects nothing and ships
        # nothing — but it is the thing those rejections name, and without it
        # they have nowhere to point: the orphan sweep would take the old
        # concept, the rejected rows would go with it, and the next rebuild
        # would re-propose the very senses the sweep ruled out. Reachable:
        # most concepts are single-member, and a multi-source one can be
        # whittled to nothing one sweep session at a time.

        # A confirmed membership confirms its concept, and that must survive
        # the rebuild: inserting the literal 'proposed' here would throw the
        # sweep's judgement away on the next run of the chain, and the export
        # would drop the concept again. Rejecting a member says nothing about
        # the concept — the rest of the grouping may still be right.
        status = "confirmed" if any(
            judged.get(m["view"]["member_key"], (None, None, None))[1]
            == "confirmed" for m in members) else "proposed"

        cur = con.execute(
            "INSERT INTO concept (status, confidence, created_at, last_updated)"
            " VALUES (?, ?, ?, ?)", (status, concept["confidence"], NOW, NOW))
        concept_id = cur.lastrowid
        counts["concepts"] += 1

        member_ids = {}
        for m in members:
            v = m["view"]
            key = v["member_key"]
            if key in judged:
                counts["kept"] += 1
                con.execute(
                    "UPDATE concept_member SET concept_id=?, entry_id=?, "
                    " sense_id=? WHERE source_id=? AND source_entry_id=? "
                    " AND sense_number IS ?",
                    (concept_id, v["entry_id"], v["sense_id"],
                     key[0], key[1], key[2]))
                mid = con.execute(
                    "SELECT id FROM concept_member WHERE source_id=? AND "
                    " source_entry_id=? AND sense_number IS ?", key).fetchone()[0]
            else:
                mid = con.execute(
                    "INSERT INTO concept_member (concept_id, source_id, "
                    " source_entry_id, sense_number, entry_id, sense_id, "
                    " status, confidence, created_at) "
                    " VALUES (?,?,?,?,?,?, 'proposed', ?, ?)",
                    (concept_id, key[0], key[1], key[2], v["entry_id"],
                     v["sense_id"], m["confidence"], NOW)).lastrowid
                counts["members"] += 1
            member_ids[key] = mid
            for e in m["evidence"]:
                con.execute(
                    "INSERT INTO concept_member_evidence (member_id, kind, "
                    " detail, weight) VALUES (?,?,?,?)",
                    (mid, e["kind"], e["detail"], e["weight"]))

        # A rejected member stays attached to the concept it was excluded
        # from — that is what the judgement records — but every rebuild mints
        # new concept ids, so it is carried onto the rebuilt row rather than
        # left pointing at the old one. It is NOT counted as a member: it
        # elects nothing, earns no evidence rows, and does not keep a concept
        # alive (see the orphan sweep below).
        for m in rejected:
            key = m["view"]["member_key"]
            counts["excluded"] += 1
            con.execute(
                "UPDATE concept_member SET concept_id=?, entry_id=?, sense_id=? "
                " WHERE source_id=? AND source_entry_id=? AND sense_number IS ?",
                (concept_id, m["view"]["entry_id"], m["view"]["sense_id"],
                 key[0], key[1], key[2]))

        views = [m["view"] for m in members]
        derived = any((v["source_id"], v["source_entry_id"]) in long_bases
                      for v in views)
        hw, hw_key, _reason = elect_headword(views, derived)
        gen, gen_key = elect_gloss(views, "en")
        gmi, gmi_key = elect_gloss(views, "mi")
        con.execute(
            "UPDATE concept SET headword=?, headword_from=?, gloss_en=?, "
            " gloss_en_from=?, gloss_mi=?, gloss_mi_from=?, last_updated=? "
            " WHERE id=?",
            (hw, member_ids.get(hw_key), gen, member_ids.get(gen_key),
             gmi, member_ids.get(gmi_key), NOW, concept_id))

    # Only now: a judged member still pointed at its OLD concept during the
    # loop above, so its concept could not be dropped before it was moved.
    #
    # Every member of every grouping — live or rejected — has been repointed
    # onto its rebuilt concept, so a judged row still naming an old concept is
    # one this build never proposed: its address has left the corpus. The
    # judgement is moot (a rejection's concept no longer exists; a
    # confirmation has nothing left to confirm) and leaving it would hold the
    # dead concept alive below as a carcass with stale elected forms and a
    # headword_from pointing at a member with no entry behind it — which is
    # how one passed the export filter and shipped, once.
    #
    # A judged key whose source this build proposed NOTHING for is not proof
    # its sense left the corpus. It is proof of one of three things, and they
    # are indistinguishable at 54's runtime: a source retired for good; an
    # interrupted or half-built import (this build ran mid-rebuild, in the
    # window between delete_source_slice() and the source's re-import); or a
    # source builder that emitted entries but dropped every sense, or stopped
    # populating headword_search, so load_senses() had nothing to propose for
    # it. All three are handled the same way, deliberately: the judgement is
    # left alone rather than destroyed.
    #
    # The trade: a permanent retirement looks identical to the other two, so
    # its judged rows — and the concepts they keep alive — now survive every
    # rebuild unless someone deletes them on purpose. Those surviving
    # concepts keep their stale elected forms and ship through
    # filter_concepts() right alongside the live concept for the same
    # headword — the 9553fae failure mode, accepted here because a lost
    # judgement is unrecoverable and this is not.
    #
    # There is an alarm, but it covers only the first of the three cases.
    # tests/test_concept_acceptance.py test_an_elected_headword_was_written_
    # by_a_member runs against the real database and goes red when a source's
    # ENTRY rows go — a retirement or a slice delete — because the carcass's
    # elected headword then has no entry behind it. That is the signal the
    # deliberate cleanup is due, not a regression to chase in 54. It does NOT
    # fire for a builder that emitted entries but dropped every sense or its
    # headword_search: the entry rows are still there with their headwords
    # intact, so the invariant matches and the carcass ships a duplicate
    # concept in silence. Nothing else in the suite catches that either.
    # Watch that source's own import — the suite will not do it for you.
    #
    # One thing this keying buys that is easy to miss: when a build collapses
    # entirely and proposes nothing at all, `rebuilt` is empty, so nothing is
    # discarded and every judgement in the database survives. Keyed on `entry`
    # instead, a catastrophic build annihilated all of them — every source
    # still had entry rows, so every judged key looked like a departed sense.
    _live = {k[0] for k in rebuilt}
    for key in [k for k in judged if k not in rebuilt and k[0] in _live]:
        con.execute("DELETE FROM concept_member WHERE source_id=? AND "
                    " source_entry_id=? AND sense_number IS ?", key)

    # Liveness on ANY member, a rejected one included. That is safe only
    # because repointing is now unconditional: a rejected row always names the
    # concept this build just minted for its grouping, never a pre-rebuild
    # one, so it can no longer keep a stale concept alive.
    con.execute("DELETE FROM concept WHERE id NOT IN "
                "(SELECT concept_id FROM concept_member)")
    # Safety net, not the main path. After the repointing above nothing in
    # normal operation names a concept that is gone; this stays for a
    # genuinely dangling row.
    con.execute("DELETE FROM concept_member WHERE status IN (?,?) "
                "  AND concept_id NOT IN (SELECT id FROM concept)", _JUDGED)
    con.execute("DELETE FROM concept_member_evidence WHERE member_id NOT IN "
                "(SELECT id FROM concept_member)")
    con.commit()
    return counts


def run(write: bool) -> None:
    con = sqlite3.connect(DB_PATH)
    views = load_senses(con)
    concepts = []
    for key in sorted(views):
        concepts.extend(form_concepts(views[key]))

    sizes = defaultdict(int)
    for c in concepts:
        sizes[len({m["view"]["source_id"] for m in c["members"]})] += 1
    print(f"concepts: {len(concepts):,}")
    for n in sorted(sizes):
        print(f"    spanning {n} source(s): {sizes[n]:,}")

    if not write:
        print("\n(dry run — pass --write to persist)")
        con.close()
        return
    print("\n" + repr(persist(con, concepts)))
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="persist to the DB")
    run(ap.parse_args().write)
