"""Export the human-authored sweep state to a small file git can hold.

Everything else in the staging database is a projection. Delete `concept`,
`derivation`, `ETY_entry_link` — a script rebuilds them. Sweep judgements are
not like that: they are decisions a person made reading one cluster at a
time, and nothing regenerates them. They live in a gitignored 568 MB database
on one disk, and until this script there was no copy anywhere else.

What it carries, and nothing more:

  judgements  concept_member rows whose status is not 'proposed' — the
              confirmations and rejections themselves
  findings    every sweep_finding
  patches     every sweep_patch
  clusters    sweep_cluster rows that have been claimed or completed

What it deliberately leaves out:

  - The 175,083 'proposed' memberships. Machine output, rebuilt on demand by
    54_build_concepts, and carrying them would bury the handful that matter.
  - The 55,736 pending sweep_cluster rows. Queue state, reseeded by
    seed_clusters() from the corpus.
  - entry_id, sense_id, concept_id. All three are REMINTED by every rebuild.
    Exporting them would be worse than useless: a restore would put a
    judgement onto whatever row happened to inherit the number. The stable
    address is (source_id, source_entry_id, sense_number), which is the same
    address persist() uses to carry judgements across a rebuild.

Output is sorted and indented so two dumps of one database are byte
identical — the file lives in git, and spurious churn would make its history
unreadable.

    py scripts/61_export_judgements.py              # write data/judgements.json
    py scripts/61_export_judgements.py --restore    # put them back
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from utils import DB_PATH

OUT_PATH = Path(__file__).parent.parent / "data" / "judgements.json"

_FINDING_COLS = ("finding_id", "session_id", "cluster_key", "rubric_version",
                 "kind", "severity", "confidence", "subject", "summary",
                 "detail", "action", "created_at", "reverted_at",
                 "reviewed_at", "review")
_PATCH_COLS = ("finding_id", "session_id", "cluster_key", "rubric_version",
               "source_id", "source_entry_id", "sense_number", "target_table",
               "field", "old_value", "new_value", "reason", "created_at",
               "reverted_at", "last_status", "last_applied_at")
_CLUSTER_COLS = ("cluster_key", "status", "completed_at", "rubric_version",
                 "finding_count", "patch_count", "notes")


def _rows(con, table, cols, where=""):
    """Sorted list of dicts, so the output is byte-stable across dumps."""
    try:
        got = con.execute(
            f"SELECT {', '.join(cols)} FROM {table} {where}").fetchall()
    except sqlite3.OperationalError:
        return []                      # table absent in an older database
    return sorted((dict(zip(cols, r)) for r in got),
                  key=lambda d: json.dumps(d, sort_keys=True,
                                           ensure_ascii=False))


def export_judgements(con) -> dict:
    """Everything a person decided, keyed on addresses that survive a rebuild."""
    judged = ("source_id", "source_entry_id", "sense_number", "status")
    return {
        "judgements": _rows(con, "concept_member", judged,
                            "WHERE status <> 'proposed'"),
        "findings": _rows(con, "sweep_finding", _FINDING_COLS),
        "patches": _rows(con, "sweep_patch", _PATCH_COLS),
        "clusters": _rows(con, "sweep_cluster", _CLUSTER_COLS,
                          "WHERE status <> 'pending'"),
    }


def restore_judgements(con, payload) -> dict:
    """Put judgements back onto a database that has lost them.

    Only `status` is written. Confidence is derived and is re-derived by
    54_build_concepts; the volatile id columns are re-resolved there too.

    A judgement whose membership no longer exists is REPORTED, never dropped
    quietly: it means the corpus no longer holds that sense, and a person
    should know their decision could not be replaced.
    """
    restored, missing = 0, []
    for j in payload.get("judgements", []):
        key = (j["source_id"], j["source_entry_id"], j["sense_number"])
        cur = con.execute(
            "UPDATE concept_member SET status = ? WHERE source_id = ? "
            "  AND source_entry_id = ? AND sense_number IS ?",
            (j["status"],) + key)
        if cur.rowcount:
            restored += 1
        else:
            sn = "" if key[2] is None else f"#{key[2]}"
            missing.append(f"{key[0]}:{key[1]}{sn}")
    con.commit()
    return {"restored": restored, "missing": sorted(missing)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--restore", action="store_true",
                    help="write the file's judgements back into the database")
    ap.add_argument("--db")
    ap.add_argument("--file", default=str(OUT_PATH))
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db or DB_PATH)
    path = Path(args.file)

    if args.restore:
        payload = json.loads(path.read_text(encoding="utf-8"))
        result = restore_judgements(con, payload)
        print(f"restored {result['restored']:,} judgement(s) from {path}")
        for addr in result["missing"]:
            print(f"  NOT RESTORED — no such membership: {addr}")
        if result["missing"]:
            print(f"\n{len(result['missing'])} judgement(s) could not be "
                  "placed. Those senses are no longer in the corpus; the "
                  "decisions behind them are in the findings above.")
    else:
        # Deliberately no timestamp in the payload. The file's whole purpose
        # is to live in git, and a clock reading would make every dump show a
        # diff even when not one judgement had changed — burying the real
        # history under churn. Git already records when it was committed.
        payload = export_judgements(con)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False),
            encoding="utf-8")
        size = path.stat().st_size
        print(f"wrote {path}  ({size / 1024:.1f} KB)")
        for name in ("judgements", "findings", "patches", "clusters"):
            print(f"  {name:<12} {len(payload[name]):>6,}")
    con.close()


if __name__ == "__main__":
    main()
