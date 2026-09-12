"""Claim a cluster, record what was judged, close it — atomically.

The runner supplies primitives; the judgement is the model's. What it guarantees
is that a cluster's findings, its patches and its completion land together or
not at all. A session that dies mid-cluster leaves that cluster claimable again
with nothing half-written — which is what makes dying cost one cluster instead
of a session's work.

**Every patch hangs off a finding.** Patches are nested inside the finding that
justified them, so a field cannot be changed without a recorded reason. The log
is the control surface; an unexplained change is precisely what it exists to
prevent, and making that structurally impossible is better than discouraging it.

**Validation happens before any write.** The whole payload is checked first, so a
malformed patch at the end cannot leave half a cluster's findings committed.

Driven either as a library or from the command line:

    py scripts/sweep_runner.py next   --session S1 [--tier 1]
    py scripts/sweep_runner.py record --session S1 --file findings.json
    py scripts/sweep_runner.py status
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH
from sweep_batch import assemble, render
from sweep_findings import ACTIONS, KINDS, record_finding
from sweep_patch import PATCHABLE, apply_patches, record_patch
from sweep_queue import claim_next, complete, progress, release_stale
from sweep_rubric import VERSION

# A membership is a judgement, so it changes only through a recorded finding.
# The spec also lists split and merge. They are deliberately NOT here: both are
# expressible as confirm/reject on the memberships involved, and a first-class
# split needs a rule for which concept keeps the id that nothing yet depends on.
CONCEPT_ACTIONS = {"confirm_member", "reject_member"}
_MEMBER_RE = re.compile(r"^([^:]+):([^#]+)(?:#(\d+))?$")


def claim(con, session_id: str, tier: int | None = None):
    """Claim the next cluster. Returns (key, batch, rendered) or (None, None, None)."""
    key = claim_next(con, session_id, tier=tier)
    if key is None:
        return None, None, None
    batch = assemble(con, key)
    return key, batch, render(batch)


def _parse_member(addr: str):
    """(source_id, source_entry_id, sense_number) from 'source:entry#sense'.

    sense_number is None when the address has no '#sense' — a NULL
    sense_number, matched with `IS`, never `=`, since SQLite's `=` never
    matches NULL.
    """
    m = _MEMBER_RE.match(addr.strip())
    if not m:
        raise ValueError(f"unparseable member {addr!r}")
    src, seid, sn = m.group(1), m.group(2), m.group(3)
    return src, seid, (int(sn) if sn else None)


def _validate(con, payload) -> dict:
    """Check the whole payload before a single row is written.

    This includes resolving every concept_action's member address against
    concept_member: a membership that does not exist is caught here, before
    the findings loop begins, rather than discovered mid-apply. That is what
    lets the apply pass run without a real prospect of failing partway
    through a payload that already validated.
    """
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    key = payload.get("cluster_key")
    if not key:
        raise ValueError("payload must name its cluster_key")

    findings = payload.get("findings") or []
    if not isinstance(findings, list):
        raise ValueError("findings must be a list")

    for i, f in enumerate(findings):
        where = f"findings[{i}]"
        if not isinstance(f, dict):
            raise ValueError(f"{where} must be an object")
        if f.get("kind") not in KINDS:
            raise ValueError(f"{where}: unknown kind {f.get('kind')!r}")
        for field in ("subject", "summary"):
            if not (f.get(field) or "").strip():
                raise ValueError(f"{where}: {field} is required")
        if f.get("action", "none") not in ACTIONS:
            raise ValueError(f"{where}: unknown action {f.get('action')!r}")
        for j, p in enumerate(f.get("patches") or []):
            at = f"{where}.patches[{j}]"
            if not isinstance(p, dict):
                raise ValueError(f"{at} must be an object")
            table, field = p.get("target_table"), p.get("field")
            if table not in PATCHABLE:
                raise ValueError(f"{at}: not a patchable table {table!r}")
            if field not in PATCHABLE[table]:
                raise ValueError(f"{at}: not a patchable field {table}.{field!r}")
            for req in ("source_id", "source_entry_id", "reason"):
                if not (str(p.get(req) or "")).strip():
                    raise ValueError(f"{at}: {req} is required")
        for j, a in enumerate(f.get("concept_actions") or []):
            at = f"{where}.concept_actions[{j}]"
            if a.get("action") not in CONCEPT_ACTIONS:
                raise ValueError(f"{at}: unknown action {a.get('action')!r}")
            member = (a.get("member") or "").strip()
            if not member:
                raise ValueError(f"{at}: member is required")
            src, seid, sn = _parse_member(member)
            row = con.execute(
                "SELECT 1 FROM concept_member WHERE source_id = ? "
                "  AND source_entry_id = ? AND sense_number IS ?",
                (src, seid, sn)).fetchone()
            if row is None:
                raise ValueError(f"{at}: no concept membership for {member!r}")
    return payload


def _apply_concept_actions(con, finding):
    """Mark a membership confirmed or rejected.

    A confirm also confirms the member's CONCEPT. Nothing else in the codebase
    sets concept.status, so without this the sweep could not change what ships:
    the export keeps `status = 'confirmed' OR confidence IN (certain,
    probable)`, and confirming a member of an uncertain concept left the
    concept uncertain, the export dropped it, and the judgement never reached
    users. The spec allows exactly this — "a concept can be confirmed while one
    of its members is still proposed. That's the common case: five witnesses
    obviously the same word, a sixth uncertain."

    A reject does NOT touch the concept: excluding one witness says nothing
    about whether the rest of the grouping is right.

    `_validate` already resolved every member address against concept_member,
    so the rowcount == 0 case below should not occur in practice. It stays as
    defence in depth — belt, not the buckle — for the unlikely case of a row
    disappearing between validation and here.
    """
    now = datetime.now(timezone.utc).isoformat()
    for a in finding.get("concept_actions") or []:
        src, seid, sn = _parse_member(a["member"])
        confirming = a["action"] == "confirm_member"
        cur = con.execute(
            "UPDATE concept_member SET status = ? WHERE source_id = ? "
            "  AND source_entry_id = ? AND sense_number IS ?",
            ("confirmed" if confirming else "rejected", src, seid, sn))
        if cur.rowcount == 0:
            raise ValueError(f"no concept membership for {a['member']!r}")
        if confirming:
            con.execute(
                "UPDATE concept SET status = 'confirmed', last_updated = ? "
                "  WHERE id IN (SELECT concept_id FROM concept_member "
                "                WHERE source_id = ? AND source_entry_id = ? "
                "                  AND sense_number IS ?)",
                (now, src, seid, sn))


def record(con, session_id: str, payload, *, rubric_version: str = VERSION) -> dict:
    """Write a cluster's findings and patches and close it, all or nothing."""
    payload = _validate(con, payload)
    key = payload["cluster_key"]

    held = con.execute(
        "SELECT status, claimed_by FROM sweep_cluster WHERE cluster_key = ?",
        (key,)).fetchone()
    if held is None:
        raise ValueError(f"no such cluster: {key!r}")
    status, holder = (held["status"], held["claimed_by"]) if hasattr(held, "keys") \
        else (held[0], held[1])
    if status != "in_progress":
        raise ValueError(f"cluster {key!r} is {status}, not claimed")
    if holder != session_id:
        raise ValueError(f"cluster {key!r} is held by {holder!r}, not {session_id!r}")

    n_findings = n_patches = 0
    try:
        for f in payload.get("findings") or []:
            finding_id = record_finding(
                con, session_id=session_id, cluster_key=key,
                rubric_version=rubric_version, kind=f["kind"],
                subject=f["subject"], summary=f["summary"], detail=f.get("detail"),
                severity=f.get("severity"), confidence=f.get("confidence"),
                action=f.get("action", "none"))
            n_findings += 1
            for p in f.get("patches") or []:
                record_patch(
                    con, source_id=p["source_id"],
                    source_entry_id=p["source_entry_id"],
                    sense_number=p.get("sense_number"),
                    target_table=p["target_table"], field=p["field"],
                    old_value=p.get("old_value"), new_value=p.get("new_value"),
                    reason=p["reason"], finding_id=finding_id,
                    session_id=session_id, cluster_key=key,
                    rubric_version=rubric_version)
                n_patches += 1
        # Concept membership changes are applied after every finding and patch
        # in the payload is recorded. `_validate` already resolved every
        # member address, so this loop is not expected to raise — the real
        # guarantee is the pre-flight check, not what follows here.
        #
        # The `con.rollback()` in `except` below is defence in depth, not the
        # primary mechanism, and its safety window is narrower than it looks:
        # apply_patches() and complete() each call con.commit() themselves,
        # and SQLite's commit flushes the *entire* pending transaction on the
        # connection, not just the caller's own statements. So the instant
        # apply_patches() runs (whenever n_patches > 0), any concept_member
        # update made here is committed right along with it — rollback can
        # only undo this loop's work if something raises before that point.
        # That is fine today because nothing downstream of a successful pass
        # here is expected to fail, but it holds by call ordering, not design.
        for f in payload.get("findings") or []:
            _apply_concept_actions(con, f)
        applied = apply_patches(con) if n_patches else {"applied": 0, "stale": 0,
                                                       "missing": 0}
        complete(con, key, rubric_version=rubric_version,
                 finding_count=n_findings, patch_count=n_patches,
                 notes=payload.get("notes"))
        con.commit()
    except Exception:
        # Leave nothing half-written and hand the cluster back. Each step is
        # independent: cleanup that can itself fail would strand the cluster
        # in_progress until the stale-release, which is the one outcome worse
        # than the original error.
        #
        # Discard first: if _apply_concept_actions raised (the only case this
        # rollback is meant for), nothing past it has run — apply_patches()
        # and complete() have not committed yet — so any concept_member
        # update made above is still uncommitted and this undoes it without
        # touching a single row record_finding/record_patch already committed.
        try:
            con.rollback()
        except Exception:
            pass
        for stmt, params in (
            ("DELETE FROM sweep_patch WHERE cluster_key = ? AND session_id = ?",
             (key, session_id)),
            ("DELETE FROM sweep_finding WHERE cluster_key = ? AND session_id = ?",
             (key, session_id)),
            ("UPDATE sweep_cluster SET status = 'pending', claimed_by = NULL, "
             "claimed_at = NULL WHERE cluster_key = ?", (key,)),
        ):
            try:
                con.execute(stmt, params)
            except Exception:
                pass
        try:
            con.commit()
        except Exception:
            pass
        raise

    return {"cluster_key": key, "findings": n_findings, "patches": n_patches,
            "applied": applied["applied"], "stale": applied["stale"],
            "missing": applied["missing"], "rubric_version": rubric_version}


def _open(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("next", "record", "status", "release"))
    ap.add_argument("--session", default="manual")
    ap.add_argument("--tier", type=int)
    ap.add_argument("--file", help="findings JSON for `record`")
    ap.add_argument("--db")
    ap.add_argument("--stale-minutes", type=int, default=60)
    args = ap.parse_args(argv)

    con = _open(args.db)
    if args.command == "next":
        key, _batch, text = claim(con, args.session, tier=args.tier)
        print(text if key else "queue empty")
    elif args.command == "record":
        if not args.file:
            ap.error("record needs --file")
        payload = Path(args.file).read_text(encoding="utf-8")
        print(json.dumps(record(con, args.session, payload), ensure_ascii=False))
    elif args.command == "release":
        print(f"released {release_stale(con, args.stale_minutes)} stale claim(s)")
    else:
        p = progress(con)
        print(json.dumps(p, ensure_ascii=False))
    con.close()


if __name__ == "__main__":
    main()
