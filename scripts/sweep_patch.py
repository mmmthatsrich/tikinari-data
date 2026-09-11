"""The audit sweep's patch layer: record a correction, replay it after rebuilds.

`50_build_unified.py` is a pure projection — it deletes a source's slice and
rebuilds it from the landing tables — so anything the sweep writes straight into
the unified core is destroyed by the next rebuild of that source. Corrections
are therefore recorded here and replayed at the end of each build, the same hook
the POS pass and the sense resolver already use.

**Keying.** Patches are addressed by (source_id, source_entry_id, sense_number),
never by `entry.id`, which DATABASE_REFERENCE documents as volatile across
rebuilds — a patch keyed on it would silently reattach to a different word.
(source_id, source_entry_id) is unique across all 153,543 entries, and although
67,625 senses carry a NULL sense_number, no entry with more than one sense does,
so the triple names exactly one row.

**Staleness is per FIELD, not per entry.** A patch applies only while the field
still holds the value it was judged against:

  - field == old_value  -> apply
  - field == new_value  -> already applied; a no-op, not an error
  - anything else       -> the source changed that field after the judgement.
                           The patch is marked stale and NOT applied: upstream's
                           own correction outranks an older judgement of ours.

An edit elsewhere in the same entry does not block the patch, so a source adding
one example does not discard corrections to fields nobody touched.

**Revert is a mark, not an undo.** Reverted patches are skipped at replay, so the
next rebuild simply reprojects the source's own value.
"""
from datetime import datetime, timezone

# What a patch may touch. Anything else is refused — these names are
# interpolated into SQL, and the sweep is autonomous.
PATCHABLE = {
    "entry": {"headword", "headword_sort", "headword_search", "headword_en",
              "part_of_speech", "loan_marker", "dialect", "locator"},
    "sense": {"gloss_en", "gloss_mi", "definition_raw", "register",
              "part_of_speech", "note"},
}

PATCH_DDL = """
CREATE TABLE IF NOT EXISTS sweep_patch (
    id              INTEGER PRIMARY KEY,
    finding_id      TEXT,            -- one judgement may emit several patches
    session_id      TEXT,            -- for reverting a whole sweep session
    cluster_key     TEXT,            -- headword_search the judgement was made on
    rubric_version  TEXT,            -- which rubric produced it
    source_id       TEXT NOT NULL,
    source_entry_id TEXT NOT NULL,
    sense_number    INTEGER,         -- NULL for an entry-level field
    target_table    TEXT NOT NULL,   -- 'entry' | 'sense'
    field           TEXT NOT NULL,
    old_value       TEXT,            -- the value this was judged against
    new_value       TEXT,
    reason          TEXT NOT NULL,   -- why, in the sweep's own words
    created_at      TEXT,
    reverted_at     TEXT,
    last_status     TEXT,            -- applied | stale | missing
    last_applied_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sweep_patch_target
    ON sweep_patch(source_id, source_entry_id);
CREATE INDEX IF NOT EXISTS idx_sweep_patch_finding ON sweep_patch(finding_id);
CREATE INDEX IF NOT EXISTS idx_sweep_patch_session ON sweep_patch(session_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(target_table: str, field: str) -> None:
    if target_table not in PATCHABLE:
        raise ValueError(f"not a patchable table: {target_table!r}")
    if field not in PATCHABLE[target_table]:
        raise ValueError(f"not a patchable field: {target_table}.{field!r}")


def record_patch(con, *, source_id, source_entry_id, sense_number, target_table,
                 field, old_value, new_value, reason, finding_id=None,
                 session_id=None, cluster_key=None, rubric_version=None):
    """Record one correction. Does not touch the data — replay does that."""
    _check(target_table, field)
    if not reason:
        raise ValueError("a patch must say why")
    cur = con.execute(
        "INSERT INTO sweep_patch (finding_id, session_id, cluster_key, "
        "rubric_version, source_id, source_entry_id, sense_number, target_table, "
        "field, old_value, new_value, reason, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (finding_id, session_id, cluster_key, rubric_version, source_id,
         str(source_entry_id), sense_number, target_table, field,
         old_value, new_value, reason, _now()))
    con.commit()
    return cur.lastrowid


def revert(con, *, patch_id=None, finding_id=None, session_id=None) -> int:
    """Mark patches reverted so replay skips them. Returns how many."""
    if patch_id is not None:
        where, arg = "id = ?", patch_id
    elif finding_id is not None:
        where, arg = "finding_id = ?", finding_id
    elif session_id is not None:
        where, arg = "session_id = ?", session_id
    else:
        raise ValueError("revert needs a patch_id, finding_id or session_id")
    n = con.execute(f"UPDATE sweep_patch SET reverted_at = ? "
                    f"WHERE reverted_at IS NULL AND {where}", (_now(), arg)).rowcount
    con.commit()
    return n


def _locate(con, p):
    """(rowid, current value) for the patch's target, or (None, None)."""
    if p["target_table"] == "entry":
        row = con.execute(
            f"SELECT id, {p['field']} FROM entry "
            "WHERE source_id = ? AND source_entry_id = ?",
            (p["source_id"], p["source_entry_id"])).fetchone()
    else:
        row = con.execute(
            f"SELECT s.id, s.{p['field']} FROM sense s "
            "JOIN entry e ON e.id = s.entry_id "
            "WHERE e.source_id = ? AND e.source_entry_id = ? "
            "  AND COALESCE(s.sense_number, 1) = COALESCE(?, 1)",
            (p["source_id"], p["source_entry_id"], p["sense_number"])).fetchone()
    return (row[0], row[1]) if row else (None, None)


def apply_patches(con, source_id: str | None = None) -> dict:
    """Replay unreverted patches. Returns {applied, stale, missing}.

    `source_id` limits the replay to one source, which is what a per-source
    rebuild needs.
    """
    sql = ("SELECT id, source_id, source_entry_id, sense_number, target_table, "
           "field, old_value, new_value FROM sweep_patch WHERE reverted_at IS NULL")
    args = ()
    if source_id:
        sql += " AND source_id = ?"
        args = (source_id,)

    counts = {"applied": 0, "stale": 0, "missing": 0}
    now = _now()
    for row in con.execute(sql, args).fetchall():
        p = dict(zip(("id", "source_id", "source_entry_id", "sense_number",
                      "target_table", "field", "old_value", "new_value"), row))
        try:
            _check(p["target_table"], p["field"])
        except ValueError:
            continue
        rowid, current = _locate(con, p)
        if rowid is None:
            status = "missing"
        elif current == p["new_value"]:
            status = "applied"          # already in place; replay is idempotent
        elif current == p["old_value"]:
            con.execute(f"UPDATE {p['target_table']} SET {p['field']} = ? "
                        "WHERE id = ?", (p["new_value"], rowid))
            status = "applied"
            counts["applied"] += 1
        else:
            status = "stale"            # the source moved under us; it wins
            counts["stale"] += 1
        if status == "missing":
            counts["missing"] += 1
        con.execute("UPDATE sweep_patch SET last_status = ?, last_applied_at = ? "
                    "WHERE id = ?", (status, now, p["id"]))
    con.commit()
    return counts
