"""Supervise a long sweep: meter the budget, stop at 95%, wait out a reset.

The budget logic lives in a process OUTSIDE the model. It behaves the same every
run and does not depend on the sweep noticing anything about itself, which is
what "set the process to stop at 95%" asks for.

Each tick invokes `claude -p "<prompt>" --output-format json` over a bounded
chunk of clusters and reads the usage back out of the result. Real shape:

    {"is_error": false, "subtype": "success", "total_cost_usd": 0.39921,
     "session_id": "...", "result": "...",
     "usage": {"input_tokens": 2, "cache_creation_input_tokens": 39910,
               "cache_read_input_tokens": 0, "output_tokens": 4}}

**Cache creation is the dominant cost of a tick.** A trivial invocation measured
39,910 cache-creation tokens — fixed overhead paid per process start. One
cluster per tick across 55,827 clusters would be billions of tokens of pure
overhead, so a tick must cover many clusters, and the session id is threaded
into the next invocation so a resume reads the cache instead of recreating it.

**Reset handling is reactive, not predictive.** The supervisor never guesses at
a clock: it waits to be refused, reads the reset time out of the refusal, sleeps
until then plus a margin, and carries on. A refusal costs no budget.
"""
import json
import re
import time
from datetime import datetime, timezone

# 'Claude usage limit reached. Your limit will reset at 2026-09-12T14:00:00+00:00.'
# and the older pipe-delimited epoch form.
_LIMIT_RE = re.compile(r"usage limit reached", re.I)
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?"
                     r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_EPOCH_RE = re.compile(r"\|(\d{9,13})\b")


def _reset_from(text: str):
    """The reset moment named in a refusal, or None."""
    if not text:
        return None
    if (m := _EPOCH_RE.search(text)):
        ts = int(m.group(1))
        if ts > 10 ** 11:            # milliseconds
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if (m := _ISO_RE.search(text)):
        raw = m.group(0).replace("Z", "+00:00").replace(" ", "T")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def parse_tick(stdout: str) -> dict:
    """Read one `claude -p --output-format json` result.

    Unparseable output is an error, never an exception — a supervisor that dies
    on a malformed tick is worse than one that reports it and stops.
    """
    tick = {"is_error": True, "limit_hit": False, "limit_reset_at": None,
            "tokens": 0, "cost_usd": 0.0, "session_id": None, "result": "",
            "raw": stdout}
    try:
        data = json.loads(stdout)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except Exception:
        tick["result"] = "unparseable supervisor output"
        return tick

    usage = data.get("usage") or {}
    tick.update(
        is_error=bool(data.get("is_error")),
        tokens=sum(int(usage.get(k) or 0) for k in
                   ("input_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens", "output_tokens")),
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        session_id=data.get("session_id"),
        result=data.get("result") or "",
    )
    blob = f"{tick['result']} {data.get('subtype') or ''} {data.get('api_error_status') or ''}"
    if tick["is_error"] and _LIMIT_RE.search(blob):
        tick["limit_hit"] = True
        tick["limit_reset_at"] = _reset_from(blob)
    return tick


def cli_runner(prompt: str, *, cwd=None, timeout: int = 3600,
               extra_args=()) -> callable:
    """Build a runner that shells out to `claude -p ... --output-format json`.

    Returns a callable taking the previous tick's session_id, so a tick resumes
    the prior session where possible: a resume reads the cached prompt instead
    of paying ~40k cache-creation tokens again.
    """
    import subprocess

    def run(session_id=None) -> str:
        cmd = ["claude", "-p", prompt, "--output-format", "json", *extra_args]
        if session_id:
            cmd += ["--resume", session_id]
        try:
            done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, encoding="utf-8")
        except subprocess.TimeoutExpired:
            return json.dumps({"is_error": True,
                               "result": f"supervisor: tick exceeded {timeout}s"})
        # A refusal can arrive on stderr with nothing on stdout; keep both so
        # the usage-limit detector still sees the message.
        return done.stdout.strip() or json.dumps(
            {"is_error": True, "result": (done.stderr or "").strip()
             or f"supervisor: no output (exit {done.returncode})"})

    return run


def should_stop(*, spent: int, budget: int | None, threshold: float = 0.95) -> bool:
    """True once the session has used its share of the budget."""
    if not budget:
        return False
    return spent >= budget * threshold


def seconds_until(reset_at, *, now=None, margin: int = 60) -> float:
    """How long to sleep for a reset, never negative, always past it."""
    now = now or datetime.now(timezone.utc)
    if reset_at is None:
        return float(margin)
    delta = (reset_at - now).total_seconds()
    return float(margin) if delta <= 0 else delta + margin


def supervise(*, runner, has_work, budget_tokens: int | None,
              threshold: float = 0.95, max_ticks: int | None = None,
              max_consecutive_errors: int = 5, sleeper=time.sleep,
              on_tick=None, reset_margin: int = 60,
              default_limit_wait: int = 900) -> dict:
    """Drive ticks until the queue empties, the budget runs out, or ticks fail.

    `runner(session_id) -> stdout` is injected so the usage-limit path can be
    exercised against a fixture: a real limit cannot be produced on demand.
    """
    spent, cost, ticks, waits, errors = 0, 0.0, 0, 0, 0
    session_id = None
    reason = "queue_empty"

    while has_work():
        if should_stop(spent=spent, budget=budget_tokens, threshold=threshold):
            reason = "budget"
            break
        if max_ticks is not None and ticks >= max_ticks:
            reason = "max_ticks"
            break

        tick = parse_tick(runner(session_id))
        ticks += 1

        if tick["limit_hit"]:
            waits += 1
            errors = 0          # being refused is not a fault
            wait = (seconds_until(tick["limit_reset_at"], margin=reset_margin)
                    if tick["limit_reset_at"] else float(default_limit_wait))
            if on_tick:
                on_tick({**tick, "n": ticks, "waiting_s": wait})
            sleeper(wait)
            continue

        spent += tick["tokens"]
        cost += tick["cost_usd"]
        if tick["is_error"]:
            errors += 1
        else:
            errors = 0
            session_id = tick["session_id"] or session_id
        if on_tick:
            on_tick({**tick, "n": ticks, "spent": spent})
        if errors >= max_consecutive_errors:
            reason = "errors"
            break
    else:
        reason = "queue_empty"

    if should_stop(spent=spent, budget=budget_tokens, threshold=threshold) \
            and reason == "queue_empty" and has_work():
        reason = "budget"

    return {"ticks": ticks, "tokens": spent, "cost_usd": round(cost, 4),
            "limit_waits": waits, "stopped_because": reason,
            "session_id": session_id}
