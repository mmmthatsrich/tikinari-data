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
import json
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
from concept_evidence import (GlossIndex, SEED_CONFIDENCE,
                              cognate_unique_pairs, confidence_for,
                              lexeme_key, positive_evidence, seed_blocks)


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
            "lexeme": lexeme_key(src, seid, hw, locator),
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


def form_concepts(views, index):
    """Group one headword key's sense-views into concepts.

    Seeds attach to a concept only on positive evidence linking them to it, and
    only when no block holds against ANY existing member. That second clause is
    the anti-chaining rule: if two words are separated by their own source's
    numbering, no third source compatible with each can later join them.
    """
    # Uniqueness is a property of the candidate set, so it is decided once
    # against the whole bucket and then read pair by pair (D43).
    unique_cognates = cognate_unique_pairs(views)

    concepts = []
    for seed in _seed_groups(views):
        placed = False
        for concept in concepts:
            existing = [m["view"] for m in concept["members"]]

            # A block against any current member rules the whole concept out.
            # seed_blocks, not blocks: the part-of-speech reason is weighed
            # against the seed's whole inventory, because a lexeme is the
            # source's own grouping and tags spread over its sense rows are
            # the same claim as a comma list on one (D44).
            if seed_blocks(seed, existing):
                continue

            evidence = []
            for s in seed:
                for e in existing:
                    found = positive_evidence(s, e, index, unique_cognates)
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

    # Re-score every member against the concept it ENDED UP IN, not against
    # whoever happened to be present when it attached.
    #
    # Seeds are processed in sorted order, so a member's confidence used to be
    # frozen at attach time. On the 'ikarangi' cluster that made te_aka
    # 'galaxy.' uncertain even though te_matatiki 'Galaxy' — coverage 1.00
    # against it — joined the same concept moments later: te_aka had scored
    # against paekupu's forty-word definition and never saw te_matatiki. It
    # also left the FOUNDING seed with no evidence at all, and so with its
    # seed confidence untouched: certain by virtue of never having been
    # compared to anything, which flattered it.
    #
    # positive_evidence returns nothing for a same-source pair, so within-
    # source members contribute nothing here and the seeding step remains the
    # only thing that groups a source's own senses.
    for c in concepts:
        if len(c["members"]) > 1:
            for m in c["members"]:
                pooled, seen = [], set()
                for other in c["members"]:
                    if other is m:
                        continue
                    for e in positive_evidence(m["view"], other["view"], index,
                                               unique_cognates):
                        tag = (e["kind"], e["detail"])
                        if tag not in seen:
                            seen.add(tag)
                            pooled.append(e)
                seed_conf = SEED_CONFIDENCE.get(m["view"]["source_id"], "certain")
                rescored = min((confidence_for(pooled, []), seed_conf),
                               key=("uncertain", "probable", "certain").index)
                m["evidence"] = pooled
                # Re-scoring may only RAISE a membership, never lower it.
                # Members joining adds evidence; it cannot unmake the evidence
                # that justified this member's own attachment. Scored both
                # ways against the corpus, lowering was badly wrong: it
                # demoted every founding seed — which has no evidence because
                # it was never compared to anything — and min() then sank the
                # concept with it, taking the app from 90,187 concepts to
                # 74,409. Monotone, the same change can only ever ship more.
                m["confidence"] = max(
                    (m["confidence"], rescored),
                    key=("uncertain", "probable", "certain").index)

    for c in concepts:
        c["confidence"] = min((m["confidence"] for m in c["members"]),
                              key=("uncertain", "probable", "certain").index)
    return concepts


NOW = datetime.now(timezone.utc).isoformat()

_JUDGED = ("confirmed", "rejected")


def _derived_long(con):
    """Member keys whose word is formed on a base carrying a long vowel.

    Attested word formation settles this: where a source itself says hōmai is
    hō + mai, the macron follows from morphology rather than from a vote.

    Restricted to derived = 0 for that reason. ngata's 4,646 rows are our
    segmentation of a comma-separated run, not the source's pairing, and they
    carry 'probable' — good enough to record, not good enough to settle a
    spelling that propagates into the app's canonical headword. Dropping them
    here changes no election today: all 1,195 with a macronised base were
    measured against the pre-change database and moved zero of 91,140 elected
    headwords (tests/test_derived_long_scope.py).

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
            "  FROM derivation d JOIN entry e ON e.id = d.entry_id "
            " WHERE d.derived = 0")
    except sqlite3.OperationalError:
        return out
    for src, seid, base in rows:
        if any(ch in "āēīōū" for ch in (base or "").lower()):
            out.add((src, str(seid)))
    return out


def _concept_status(member_keys, judged):
    """'confirmed' only where a judge saw this grouping, else 'proposed' (D47).

    A member-level confirm sets a concept-level status — nothing else sets
    `concept.status`, and without it the sweep could not change what ships.
    But the concept is rebuilt from nothing every run, so the old rule, a bare
    `any(member is confirmed)`, re-applied one judgement to whatever grouping
    now existed. A sweep session confirmed te_aka:516 in a te_aka-only
    concept; a later fix merged hepatakakupu:4287 in; and the rebuilt concept
    came back confirmed with a member no judge had ever seen inside it.

    That is not only bookkeeping: `filter_concepts` ships a concept when
    `status = 'confirmed' OR confidence IN (certain, probable)`, so a
    confirmed concept bypasses the confidence filter and carries its
    unexamined members out with it.

    So a confirmation must name the grouping it was granted to, and covers
    only a grouping that adds nothing to it. Losing a member is fine: the
    judge saw more than is here now and nothing unexamined has appeared.
    A rejected member is not part of the grouping at all — the rejection
    records that the sense does NOT belong.

    A confirmation with no recorded grouping cannot be checked, so it cannot
    confirm. That covers rows judged before the column existed. Nothing is
    destroyed either way: the member keeps its own `confirmed` status, and
    only the concept-level claim waits to be re-earned, because a lost
    judgement is unrecoverable and this is not.
    """
    present = {k for k in member_keys
               if judged.get(k, (None, None, None, None))[1] != "rejected"}
    for key in member_keys:
        cid, status, conf, grouping = judged.get(
            key, (None, None, None, None))
        if status != "confirmed" or grouping is None:
            continue
        seen = {tuple(k) for k in grouping}
        if present <= seen:
            return "confirmed"
    return "proposed"


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
    for cid, src, seid, sn, status, conf, grouping in con.execute(
            "SELECT concept_id, source_id, source_entry_id, sense_number, "
            "       status, confidence, confirmed_grouping FROM concept_member "
            " WHERE status IN (?,?)", _JUDGED):
        judged[(src, str(seid), sn)] = (
            cid, status, conf,
            None if grouping is None else json.loads(grouping))

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
        status = _concept_status([m["view"]["member_key"] for m in members],
                                 judged)

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
                # status is the human's and is never touched here; confidence
                # is derived and must be re-derived, or a row judged under one
                # rule keeps that rule's confidence for ever while the evidence
                # rows beside it — which this same loop rewrites — say
                # otherwise. The re-tuning mechanism in the gloss-evidence
                # spec §6 fits thresholds by pairing a judgement with its
                # measurements, so the judged rows are exactly the labels that
                # must not go stale.
                con.execute(
                    "UPDATE concept_member SET concept_id=?, entry_id=?, "
                    " sense_id=?, confidence=? WHERE source_id=? AND "
                    " source_entry_id=? AND sense_number IS ?",
                    (concept_id, v["entry_id"], v["sense_id"], m["confidence"],
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
                    " detail, weight, coverage, distinctiveness) "
                    " VALUES (?,?,?,?,?,?)",
                    (mid, e["kind"], e["detail"], e["weight"],
                     e["coverage"], e["distinctiveness"]))

        # A rejected member stays attached to the concept it was excluded
        # from — that is what the judgement records — but every rebuild mints
        # new concept ids, so it is carried onto the rebuilt row rather than
        # left pointing at the old one. It is NOT counted as a member: it
        # elects nothing, earns no evidence rows, and does not keep a concept
        # alive (see the orphan sweep below).
        #
        # Consequence for §6's re-tier story: the DELETE FROM
        # concept_member_evidence above runs unconditionally, and this branch
        # re-inserts nothing, so a rejected membership keeps its judgement but
        # loses its coverage/distinctiveness on every rebuild of 54. A
        # threshold re-fit that wants the rejected rows' measurements must
        # read them BEFORE running 54 again, not after -- by the time this
        # loop finishes, the negative half of the labelled data is gone.
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
    # Once per run, not once per pair: 0.6s over 150,037 glosses against
    # ~1.15M pair comparisons. Built here rather than in concept_evidence so
    # that module stays free of DB code.
    index = GlossIndex(
        g for (g,) in con.execute(
            "SELECT gloss_en FROM sense WHERE gloss_en IS NOT NULL"))
    print(f"gloss index: {len(index):,} glosses")
    concepts = []
    for key in sorted(views):
        concepts.extend(form_concepts(views[key], index))

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
