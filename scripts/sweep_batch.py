"""Assemble one cluster into the view the audit sweep judges.

A cluster is one normalised headword and everything every source says about it:
entries, their senses, examples, forms, relations and domains, plus every
cognate set linked into any of them.

All four judgements come from this one read — field placement, cross-source
consistency, which sense an etymology means, and which entries are the same
word — and they inform each other. The sense inventory is what tells you which
sense a protoform matches; the cross-source senses are what tell you a link is
spurious homophony. `aho` is the case in point: 'cord' and 'daylight' are both
attached to the same entry, and neither can be judged without the other in view.

**Addresses are `source_id:source_entry_id`**, with `#n` for a sense. Never
`entry.id`, which DATABASE_REFERENCE documents as volatile across rebuilds — a
finding must name something a patch can still find after the next projection.

Size is not a concern: the largest cluster in the corpus (`mata`, 117 entries
across 9 sources) is about 32k characters all in, and none exceeds that, so a
batch is never truncated. Nothing is hidden from the judgement.
"""

_ENTRY_SQL = """
SELECT id, source_id, source_entry_id, headword, headword_en, part_of_speech,
       part_of_speech_en, part_of_speech_mi, dialect, loan_marker, locator
  FROM entry WHERE headword_search = ?
 ORDER BY source_id, source_entry_id
"""

_SENSE_SQL = """
SELECT id, entry_id, sense_number, gloss_en, gloss_mi, definition_raw,
       register, note, part_of_speech, part_of_speech_en
  FROM sense WHERE entry_id IN (%s) ORDER BY entry_id, COALESCE(sense_number, 1)
"""

_EXAMPLE_SQL = """
SELECT sense_id, entry_id, text_mi, text_en, citation, source_abbrev
  FROM example WHERE entry_id IN (%s) ORDER BY entry_id, sort_no
"""

_FORM_SQL = "SELECT entry_id, form, form_type FROM form WHERE entry_id IN (%s)"

_RELATION_SQL = """
SELECT r.entry_id, r.rel_type, r.target_headword, r.note,
       t.source_id AS t_src, t.source_entry_id AS t_seid, r.target_sense_id
  FROM relation r LEFT JOIN entry t ON t.id = r.target_entry_id
 WHERE r.entry_id IN (%s)
"""

_DOMAIN_SQL = ("SELECT entry_id, domain, domain_lang FROM entry_domain "
               "WHERE entry_id IN (%s)")

_ETY_SQL = """
SELECT l.entry_id, l.sense_id, l.source, l.match_method,
       cs.protoform, cs.level, cs.gloss
  FROM ETY_entry_link l JOIN ETY_cognateset cs ON cs.id = l.cognateset_id
 WHERE l.entry_id IN (%s)
 ORDER BY l.entry_id, cs.protoform
"""


def _ph(n: int) -> str:
    return ",".join("?" * n) if n else "NULL"


_CONCEPT_IDS_SQL = """
SELECT DISTINCT cm.concept_id FROM concept_member cm
  JOIN entry e ON e.source_id = cm.source_id
   AND e.source_entry_id = cm.source_entry_id
 WHERE e.headword_search = ? ORDER BY cm.concept_id
"""

_CONCEPT_SQL = ("SELECT status, confidence, headword, gloss_en, gloss_mi "
                "  FROM concept WHERE id = ?")

_CONCEPT_MEMBER_SQL = """
SELECT id, source_id, source_entry_id, sense_number, status, confidence
  FROM concept_member WHERE concept_id = ?
 ORDER BY source_id, source_entry_id
"""

_CONCEPT_MEMBER_EVIDENCE_SQL = ("SELECT kind, detail FROM concept_member_evidence "
                                 " WHERE member_id = ?")


def _concepts_for(con, cluster_key):
    """The proposed concepts covering this cluster, with their evidence."""
    rows = con.execute(_CONCEPT_IDS_SQL, (cluster_key,)).fetchall()
    out = []
    for (cid,) in rows:
        c = con.execute(_CONCEPT_SQL, (cid,)).fetchone()
        members = []
        for mid, src, seid, sn, status, conf in con.execute(
                _CONCEPT_MEMBER_SQL, (cid,)):
            evidence = [dict(zip(("kind", "detail"), r)) for r in con.execute(
                _CONCEPT_MEMBER_EVIDENCE_SQL, (mid,))]
            members.append({"address": f"{src}:{seid}"
                                       + (f"#{sn}" if sn else ""),
                            "status": status, "confidence": conf,
                            "evidence": evidence})
        out.append({"id": cid, "status": c["status"], "confidence": c["confidence"],
                    "headword": c["headword"], "gloss_en": c["gloss_en"],
                    "gloss_mi": c["gloss_mi"], "members": members})
    return out


def assemble(con, cluster_key: str) -> dict:
    """Everything the sweep needs to judge one cluster."""
    entries = [dict(r) for r in con.execute(_ENTRY_SQL, (cluster_key,))]
    batch = {
        "cluster_key": cluster_key,
        "entry_count": len(entries),
        "source_count": len({e["source_id"] for e in entries}),
        "entries": [],
        "concepts": _concepts_for(con, cluster_key),
        "etymology": [],
    }
    if not entries:
        return batch

    ids = [e["id"] for e in entries]
    by_id = {e["id"]: e for e in entries}
    addr = {e["id"]: f"{e['source_id']}:{e['source_entry_id']}" for e in entries}
    ph = _ph(len(ids))

    senses = {}
    sense_addr = {}
    for r in con.execute(_SENSE_SQL % ph, ids):
        s = dict(r)
        n = s["sense_number"]
        s["address"] = f"{addr[s['entry_id']]}#{n if n is not None else 1}"
        sense_addr[s["id"]] = s["address"]
        s["examples"] = []
        senses.setdefault(s["entry_id"], []).append(s)

    loose = {}
    for r in con.execute(_EXAMPLE_SQL % ph, ids):
        x = {k: r[k] for k in ("text_mi", "text_en", "citation", "source_abbrev")}
        target = next((s for s in senses.get(r["entry_id"], [])
                       if s["id"] == r["sense_id"]), None)
        # An example whose sense_id does not match one of this entry's senses is
        # itself a finding; surface it rather than dropping it silently.
        (target["examples"] if target else
         loose.setdefault(r["entry_id"], [])).append(x)

    grouped = {}
    for name, sql, keep in (
            ("forms", _FORM_SQL, ("form", "form_type")),
            ("relations", _RELATION_SQL,
             ("rel_type", "target_headword", "note", "t_src", "t_seid",
              "target_sense_id")),
            ("domains", _DOMAIN_SQL, ("domain", "domain_lang"))):
        acc = {}
        for r in con.execute(sql % ph, ids):
            acc.setdefault(r["entry_id"], []).append({k: r[k] for k in keep})
        grouped[name] = acc

    for e in entries:
        eid = e.pop("id")
        e["address"] = addr[eid]
        e["senses"] = [{k: v for k, v in s.items() if k not in ("id", "entry_id")}
                       for s in senses.get(eid, [])]
        e["forms"] = grouped["forms"].get(eid, [])
        e["domains"] = grouped["domains"].get(eid, [])
        e["relations"] = [
            {"rel_type": r["rel_type"], "target_headword": r["target_headword"],
             "note": r["note"], "target_sense_id": r["target_sense_id"],
             "target_address": (f"{r['t_src']}:{r['t_seid']}" if r["t_src"] else None)}
            for r in grouped["relations"].get(eid, [])]
        if eid in loose:
            e["orphan_examples"] = loose[eid]
        batch["entries"].append(e)

    for r in con.execute(_ETY_SQL % ph, ids):
        batch["etymology"].append({
            "protoform": r["protoform"], "level": r["level"], "gloss": r["gloss"],
            "source": r["source"], "match_method": r["match_method"],
            "entry_address": addr[r["entry_id"]],
            "sense_address": sense_addr.get(r["sense_id"]),
        })
    return batch


def _trim(text, limit=200):
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def render(batch: dict) -> str:
    """The compact text the sweep actually reads."""
    out = [f"CLUSTER {batch['cluster_key']!r} — {batch['entry_count']} entries, "
           f"{batch['source_count']} sources"]
    if not batch["entries"]:
        return out[0] + "\n(no entries)"

    current = None
    for e in batch["entries"]:
        if e["source_id"] != current:
            current = e["source_id"]
            out.append(f"\n── {current} " + "─" * max(0, 58 - len(current)))
        head = f"  {e['address']}  {e['headword']!r}"
        bits = [b for b in (e["part_of_speech"], e["part_of_speech_en"],
                            e["dialect"], e["loan_marker"]) if b]
        out.append(head + (("  [" + " | ".join(bits) + "]") if bits else ""))
        if e.get("headword_en"):
            out.append(f"      headword_en: {_trim(e['headword_en'])!r}")
        for s in e["senses"]:
            n = s["sense_number"] if s["sense_number"] is not None else 1
            out.append(f"      s{n} {s['address']}")
            for field in ("gloss_en", "gloss_mi", "definition_raw", "register", "note"):
                if s.get(field):
                    out.append(f"         {field:14s} {_trim(s[field])!r}")
            for x in s["examples"]:
                out.append(f"         ex  mi={_trim(x['text_mi'], 120)!r}")
                if x["text_en"]:
                    out.append(f"             en={_trim(x['text_en'], 120)!r}")
                if x["citation"]:
                    out.append(f"             cit={x['citation']!r}")
        for x in e.get("orphan_examples", []):
            out.append(f"      !! example not attached to any sense: "
                       f"{_trim(x['text_mi'], 90)!r}")
        for f in e["forms"]:
            out.append(f"      form  {f['form_type']}: {f['form']!r}")
        for r in e["relations"]:
            tgt = r["target_address"] or "UNRESOLVED"
            sense = f" sense={r['target_sense_id']}" if r["target_sense_id"] else ""
            note = f"  note={_trim(r['note'], 60)!r}" if r["note"] else ""
            out.append(f"      rel   {r['rel_type']} -> {r['target_headword']!r} "
                       f"[{tgt}{sense}]{note}")
        for d in e["domains"]:
            out.append(f"      domain {d['domain']!r} ({d['domain_lang']})")

    if batch.get("concepts"):
        out.append(f"\n── CONCEPTS ──────────────────────────────────────────────")
        out.append("   (proposed groupings. Judge each MEMBERSHIP on its own — ")
        out.append("    yes or no — not the concept as a whole. Evidence is pooled")
        out.append("    per source word and attached to every sense that word")
        out.append("    contributed: it is the reason that word joined the concept,")
        out.append("    not a claim about this one sense.)")
        for c in batch["concepts"]:
            out.append(f"   concept {c['id']}  [{c['status']}/{c['confidence']}]"
                       f"  {c['headword']!r}")
            if c["gloss_en"]:
                out.append(f"       en {_trim(c['gloss_en'], 70)!r}")
            if c["gloss_mi"]:
                out.append(f"       mi {_trim(c['gloss_mi'], 70)!r}")
            for m in c["members"]:
                out.append(f"       {m['address']:<34} "
                           f"{m['status']}/{m['confidence']}")
                for e in m["evidence"]:
                    out.append(f"           {e['kind']}: {_trim(e['detail'], 60)}")

    if batch["etymology"]:
        out.append(f"\n── ETYMOLOGY ─────────────────────────────────────────────")
        out.append("   (all links are match_method='headword_exact' — matched on "
                   "spelling,")
        out.append("    never on meaning. Competing sets on one entry are the "
                   "judgement.)")
        for link in batch["etymology"]:
            lvl = f"[{link['level']}]" if link["level"] else ""
            tgt = link["sense_address"] or (link["entry_address"] + " (no sense)")
            out.append(f"   {link['protoform']:<14} {lvl:<7} "
                       f"{_trim(link['gloss'], 60)!r}")
            out.append(f"       -> {tgt}   via {link['source']}")
    return "\n".join(out)
