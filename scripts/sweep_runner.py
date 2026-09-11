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
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import DB_PATH
from sweep_batch import assemble, render
from sweep_findings import ACTIONS, KINDS, record_finding
from sweep_patch import PATCHABLE, apply_patches, record_patch
from sweep_queue import claim_next, complete, progress, release_stale
from sweep_rubric import VERSION


def claim(con, session_id: str, tier: int | None = None):
    """Claim the next cluster. Returns (key, batch, rendered) or (None, None, None)."""
    key = claim_next(con, session_id, tier=tier)
    if key is None:
        return None, None, None
    batch = assemble(con, key)
    return key, batch, render(batch)


def _validate(payload) -> dict:
    """Check the whole payload before a single row is written."""
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
    return payload


def record(con, session_id: str, payload, *, rubric_version: str = VERSION) -> dict:
    """Write a cluster's findings and patches and close it, all or nothing."""
    payload = _validate(payload)
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
