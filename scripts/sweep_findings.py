"""The audit sweep's findings log — the record that gets reviewed.

The decision was to review the LOG rather than gate a queue, which makes this
the control surface. It has to say what was judged, why, and what was done —
for findings that changed something and equally for findings that changed
nothing.

**Not every finding is a patch.** 'This cognate set is spurious homophony here'
and 'these two entries are the same word' change no field on any row. If only
patch-producing judgements were recorded, the log would understate what the
sweep examined, and a reader could not tell a cluster that was clean from a
cluster whose problems were invisible to the rubric.

**Reverting a finding reverts the patches it produced**, so the unit you undo is
the judgement, not its consequences. A judgement that turns out to be wrong is
wrong in all of its effects.

Finding ids are readable and stable — `S1:aho:3` — so a log line can be quoted
in a conversation and found again.
"""
from datetime import datetime, timezone

KINDS = {
    "field_placement",      # content sitting in the wrong column
    "consistency",          # sources disagree in a way one of them gets wrong
    "etymology_sense",      # which sense a cognate set actually means
    "spurious_etymology",   # the link is homophony, not descent
    "duplicate",            # two entries are the same word
    "homograph",            # two entries share a spelling and are NOT the same word
    "macronisation",        # spelling differs across sources for one word
    "observation",          # noted, no action proposed
}

ACTIONS = {"applied", "queued", "none", "deferred"}

FINDING_DDL = """
CREATE TABLE IF NOT EXISTS sweep_finding (
    id              INTEGER PRIMARY KEY,
    finding_id      TEXT NOT NULL UNIQUE,   -- 'S1:aho:3'; also on sweep_patch
    session_id      TEXT,
    cluster_key     TEXT NOT NULL,
    rubric_version  TEXT,
    kind            TEXT NOT NULL,
    severity        TEXT,                   -- high | medium | low
    confidence      TEXT,                   -- certain | probable | uncertain
    subject         TEXT NOT NULL,          -- the address(es) judged
    summary         TEXT NOT NULL,          -- one line
    detail          TEXT,                   -- the reasoning, in full
    action          TEXT NOT NULL DEFAULT 'none',
    created_at      TEXT,
    reverted_at     TEXT,
    reviewed_at     TEXT,
    review          TEXT                    -- a human verdict, later
);
CREATE INDEX IF NOT EXISTS idx_sweep_finding_cluster ON sweep_finding(cluster_key);
CREATE INDEX IF NOT EXISTS idx_sweep_finding_session ON sweep_finding(session_id);
CREATE INDEX IF NOT EXISTS idx_sweep_finding_kind    ON sweep_finding(kind);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_finding(con, *, session_id, cluster_key, kind, subject, summary,
                   detail=None, rubric_version=None, severity=None,
                   confidence=None, action="none") -> str:
    """Record one judgement. Returns its finding_id."""
    if not kind or kind not in KINDS:
        raise ValueError(f"unknown finding kind: {kind!r}")
    if not summary or not summary.strip():
        raise ValueError("a finding must say what it found")
    if not subject or not str(subject).strip():
        raise ValueError("a finding must say what it is about")
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action!r}")

    n = con.execute(
        "SELECT COUNT(*) FROM sweep_finding WHERE session_id IS ? AND cluster_key = ?",
        (session_id, cluster_key)).fetchone()[0] + 1
    finding_id = f"{session_id}:{cluster_key}:{n}"
    con.execute(
        "INSERT INTO sweep_finding (finding_id, session_id, cluster_key, "
        "rubric_version, kind, severity, confidence, subject, summary, detail, "
        "action, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (finding_id, session_id, cluster_key, rubric_version, kind, severity,
         confidence, str(subject), summary.strip(), detail, action, _now()))
    con.commit()
    return finding_id


def revert_finding(con, finding_id: str) -> int:
    """Undo a judgement and every patch it produced. Returns patches reverted."""
    from sweep_patch import revert as revert_patches
    n = revert_patches(con, finding_id=finding_id) if _has_patches(con) else 0
    con.execute("UPDATE sweep_finding SET reverted_at = ? WHERE finding_id = ? "
                "AND reverted_at IS NULL", (_now(), finding_id))
    con.commit()
    return n


def _has_patches(con) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sweep_patch'"
    ).fetchone() is not None


def findings_for(con, *, cluster_key=None, session_id=None, kind=None) -> list:
    """Findings, each with the number of patches it produced."""
    where, args = [], []
    for col, val in (("cluster_key", cluster_key), ("session_id", session_id),
                     ("kind", kind)):
        if val is not None:
            where.append(f"f.{col} = ?")
            args.append(val)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    patches = (", (SELECT COUNT(*) FROM sweep_patch p "
               "WHERE p.finding_id = f.finding_id) AS patch_count"
               if _has_patches(con) else ", 0 AS patch_count")
    rows = con.execute(
        f"SELECT f.*{patches} FROM sweep_finding f{clause} ORDER BY f.id", args)
    return [dict(r) for r in rows]


def session_summary(con, session_id: str) -> dict:
    """What one sweep session did, for the top of the log."""
    by_kind = dict(con.execute(
        "SELECT kind, COUNT(*) FROM sweep_finding WHERE session_id = ? "
        "GROUP BY kind ORDER BY COUNT(*) DESC", (session_id,)))
    by_action = dict(con.execute(
        "SELECT action, COUNT(*) FROM sweep_finding WHERE session_id = ? "
        "GROUP BY action", (session_id,)))
    row = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT cluster_key), COUNT(reverted_at) "
        "FROM sweep_finding WHERE session_id = ?", (session_id,)).fetchone()
    return {"session_id": session_id, "total": row[0], "clusters": row[1],
            "reverted": row[2], "by_kind": by_kind, "by_action": by_action}


def render_log(con, *, session_id=None, cluster_key=None) -> str:
    """The log as read: a summary, then every judgement with its reasoning."""
    rows = findings_for(con, session_id=session_id, cluster_key=cluster_key)
    if not rows:
        return "no findings"

    out = []
    if session_id:
        s = session_summary(con, session_id)
        out.append(f"SWEEP SESSION {session_id} — {s['total']} findings across "
                   f"{s['clusters']} clusters")
        if s["reverted"]:
            out.append(f"  {s['reverted']} reverted")
        out.append("  " + ", ".join(f"{k}={v}" for k, v in s["by_kind"].items()))
        out.append("  " + ", ".join(f"{k}={v}" for k, v in s["by_action"].items()))
        out.append("")

    current = None
    for f in rows:
        if f["cluster_key"] != current:
            current = f["cluster_key"]
            out.append(f"── {current} " + "─" * max(0, 58 - len(current)))
        flags = [b for b in (f["severity"], f["confidence"]) if b]
        tail = f"  ({', '.join(flags)})" if flags else ""
        mark = "  [REVERTED]" if f["reverted_at"] else ""
        out.append(f"  {f['finding_id']}  {f['kind']}  ->  {f['action']}"
                   f"{tail}{mark}")
        out.append(f"      subject : {f['subject']}")
        out.append(f"      finding : {f['summary']}")
        if f["detail"]:
            out.append(f"      because : {f['detail']}")
        if f["patch_count"]:
            out.append(f"      patches : {f['patch_count']}")
    return "\n".join(out)
