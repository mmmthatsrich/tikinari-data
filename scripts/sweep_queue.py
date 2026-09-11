"""The audit sweep's durable cluster queue.

55,827 clusters judged across many sessions. A session WILL die — tokens, a
crash, a closed laptop — so the queue is built so that dying costs at most one
cluster. A cluster is claimed, worked and completed inside one transaction, and
the cursor advances only on commit. Predicting where a session ends is the wrong
problem; surviving it anywhere is the right one.

Order is priority, then tier, then key:

    priority 0  the calibration slice, stratified across tiers and deterministic
    tier 1      5+ sources   3,726 clusters — 7% of the corpus, 46% of its text
    tier 2      3-4 sources  8,178
    tier 3      2 sources    7,545
    tier 4      1 source    36,378 — no cross-source question to ask

Hardest first, so stopping early still means the most-consulted words are done.

Every completed cluster records the rubric version that judged it. A finding
class discovered at cluster 40,000 invalidates the 39,999 before it, and a
targeted re-sweep has to know which those are — without that, a multi-session
sweep silently produces a corpus whose early half was judged by a weaker
standard than its late half, which is the inconsistency the sweep exists to
remove.
"""
import hashlib
from datetime import datetime, timedelta, timezone

QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS sweep_cluster (
    cluster_key     TEXT PRIMARY KEY,   -- entry.headword_search
    entry_count     INTEGER,
    source_count    INTEGER,
    sense_count     INTEGER,
    tier            INTEGER,            -- 1 = most sources, 4 = single source
    priority        INTEGER NOT NULL DEFAULT 1,   -- 0 = calibration slice
    status          TEXT NOT NULL DEFAULT 'pending',
                                        -- pending | in_progress | done | failed
    claimed_by      TEXT,               -- sweep session id
    claimed_at      TEXT,
    completed_at    TEXT,
    rubric_version  TEXT,               -- which rubric judged it
    finding_count   INTEGER,
    patch_count     INTEGER,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_sweep_cluster_next
    ON sweep_cluster(status, priority, tier, cluster_key);
CREATE INDEX IF NOT EXISTS idx_sweep_cluster_rubric
    ON sweep_cluster(rubric_version);
"""

OPEN = ("pending", "in_progress")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seed_clusters(con) -> int:
    """Create or refresh one row per cluster. Never reopens completed work."""
    con.execute("""
        INSERT INTO sweep_cluster
            (cluster_key, entry_count, source_count, sense_count, tier)
        SELECT k, ents, srcs,
               (SELECT COUNT(*) FROM sense s JOIN entry e2 ON e2.id = s.entry_id
                 WHERE e2.headword_search = k),
               CASE WHEN srcs >= 5 THEN 1 WHEN srcs >= 3 THEN 2
                    WHEN srcs = 2 THEN 3 ELSE 4 END
          FROM (SELECT headword_search AS k, COUNT(*) AS ents,
                       COUNT(DISTINCT source_id) AS srcs
                  FROM entry GROUP BY headword_search)
        WHERE TRUE
        ON CONFLICT(cluster_key) DO UPDATE SET
            entry_count = excluded.entry_count,
            source_count = excluded.source_count,
            sense_count = excluded.sense_count,
            tier = excluded.tier
    """)
    con.commit()
    return con.execute("SELECT COUNT(*) FROM sweep_cluster").fetchone()[0]


def mark_calibration(con, per_tier: int = 125, seed: int = 1) -> int:
    """Put a deterministic, tier-stratified sample at the head of the queue.

    The log is only a control if it is read early enough to change the outcome,
    so the sweep stops after this slice for review before the rubric is applied
    to everything else.
    """
    picked = []
    for (tier,) in con.execute(
            "SELECT DISTINCT tier FROM sweep_cluster ORDER BY tier"):
        keys = [r[0] for r in con.execute(
            "SELECT cluster_key FROM sweep_cluster WHERE tier = ? AND status = 'pending'",
            (tier,))]
        # Deterministic without depending on Python's PRNG stream staying put.
        keys.sort(key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest())
        picked.extend(keys[:per_tier])
    con.executemany("UPDATE sweep_cluster SET priority = 0 WHERE cluster_key = ?",
                    [(k,) for k in picked])
    con.commit()
    return len(picked)


def claim_next(con, session_id: str, tier: int | None = None) -> str | None:
    """Claim the next cluster, or None when the queue is empty.

    The UPDATE re-checks status, so a cluster can only be claimed once even if
    two workers select the same candidate.
    """
    where = "status = 'pending'" + (" AND tier = ?" if tier else "")
    args = (tier,) if tier else ()
    while True:
        row = con.execute(
            f"SELECT cluster_key FROM sweep_cluster WHERE {where} "
            "ORDER BY priority, tier, cluster_key LIMIT 1", args).fetchone()
        if row is None:
            return None
        key = row[0]
        taken = con.execute(
            "UPDATE sweep_cluster SET status = 'in_progress', claimed_by = ?, "
            "claimed_at = ? WHERE cluster_key = ? AND status = 'pending'",
            (session_id, _now().isoformat(), key)).rowcount
        con.commit()
        if taken:
            return key


def complete(con, cluster_key: str, *, rubric_version: str,
             finding_count: int = 0, patch_count: int = 0,
             status: str = "done", notes: str | None = None) -> None:
    """Close a cluster. Call inside the same transaction as its writes."""
    con.execute(
        "UPDATE sweep_cluster SET status = ?, completed_at = ?, rubric_version = ?, "
        "finding_count = ?, patch_count = ?, notes = ? WHERE cluster_key = ?",
        (status, _now().isoformat(), rubric_version, finding_count, patch_count,
         notes, cluster_key))
    con.commit()


def release_stale(con, older_than_minutes: int = 60) -> int:
    """Return abandoned claims to the queue. Completed work is never touched."""
    cutoff = (_now() - timedelta(minutes=older_than_minutes)).isoformat()
    n = con.execute(
        "UPDATE sweep_cluster SET status = 'pending', claimed_by = NULL, "
        "claimed_at = NULL WHERE status = 'in_progress' AND claimed_at < ?",
        (cutoff,)).rowcount
    con.commit()
    return n


def requeue_before_rubric(con, current_versions) -> int:
    """Reopen clusters judged under a superseded rubric.

    `current_versions` are the versions considered up to date; anything else
    that is done goes back to pending.
    """
    versions = list(current_versions)
    ph = ",".join("?" * len(versions)) or "NULL"
    n = con.execute(
        f"UPDATE sweep_cluster SET status = 'pending', claimed_by = NULL, "
        f"claimed_at = NULL WHERE status = 'done' "
        f"AND (rubric_version IS NULL OR rubric_version NOT IN ({ph}))",
        versions).rowcount
    con.commit()
    return n


def progress(con) -> dict:
    """Counts by status, plus a per-tier breakdown of what is left."""
    out = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0}
    for status, n in con.execute(
            "SELECT status, COUNT(*) FROM sweep_cluster GROUP BY status"):
        out[status] = n
    out["total"] = sum(v for k, v in out.items() if k != "total")
    out["remaining_by_tier"] = dict(con.execute(
        "SELECT tier, COUNT(*) FROM sweep_cluster WHERE status IN ('pending', "
        "'in_progress') GROUP BY tier ORDER BY tier"))
    return out
