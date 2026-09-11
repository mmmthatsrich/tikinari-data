"""The sweep supervisor: budget metering, the 95% stop, and reset-resume.

The budget logic lives in a process OUTSIDE the model, so it behaves the same
every run and does not depend on the sweep noticing anything about itself.

The usage-limit path cannot be exercised for real from here — you cannot make a
limit happen on demand — so the runner is injected and the tests simulate a
refusal, including the reset timestamp. That is the difference between the path
being untested and being tested against a fixture.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

from sweep_supervisor import parse_tick, seconds_until, should_stop, supervise

OK = json.dumps({
    "is_error": False, "subtype": "success", "total_cost_usd": 0.39921,
    "session_id": "abc-123", "result": "done 25 clusters", "num_turns": 1,
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 39910,
              "cache_read_input_tokens": 0, "output_tokens": 4},
})


def _limit(reset_iso):
    return json.dumps({
        "is_error": True, "subtype": "error_during_execution",
        "result": f"Claude usage limit reached. Your limit will reset at {reset_iso}.",
        "total_cost_usd": 0.0, "usage": {},
    })


class ParseTick(unittest.TestCase):
    def test_a_successful_tick_reports_its_tokens_and_cost(self):
        t = parse_tick(OK)
        self.assertFalse(t["is_error"])
        self.assertEqual(t["tokens"], 2 + 39910 + 0 + 4)
        self.assertAlmostEqual(t["cost_usd"], 0.39921)
        self.assertEqual(t["session_id"], "abc-123")

    def test_cache_creation_counts_toward_the_budget(self):
        # ~40k per invocation of fixed overhead; ignoring it would make the
        # budget meaningless and the 95% stop arrive far too late.
        self.assertGreater(parse_tick(OK)["tokens"], 39000)

    def test_a_usage_limit_is_recognised_with_its_reset_time(self):
        reset = "2026-09-12T14:00:00+00:00"
        t = parse_tick(_limit(reset))
        self.assertTrue(t["limit_hit"])
        self.assertEqual(t["limit_reset_at"], datetime.fromisoformat(reset))

    def test_an_epoch_reset_is_understood_too(self):
        t = parse_tick(json.dumps({
            "is_error": True,
            "result": "Claude usage limit reached|1789000000"}))
        self.assertTrue(t["limit_hit"])
        self.assertIsNotNone(t["limit_reset_at"])

    def test_an_ordinary_error_is_not_a_usage_limit(self):
        t = parse_tick(json.dumps({"is_error": True, "result": "file not found"}))
        self.assertTrue(t["is_error"])
        self.assertFalse(t["limit_hit"])

    def test_unparseable_output_is_an_error_not_a_crash(self):
        t = parse_tick("not json at all")
        self.assertTrue(t["is_error"])
        self.assertFalse(t["limit_hit"])
        self.assertEqual(t["tokens"], 0)


class Budget(unittest.TestCase):
    def test_it_stops_at_the_threshold(self):
        self.assertFalse(should_stop(spent=94_000, budget=100_000))
        self.assertTrue(should_stop(spent=95_000, budget=100_000))

    def test_the_threshold_is_configurable(self):
        self.assertTrue(should_stop(spent=80_000, budget=100_000, threshold=0.8))

    def test_no_budget_means_no_stop(self):
        self.assertFalse(should_stop(spent=10 ** 9, budget=None))


class ResetWait(unittest.TestCase):
    def test_it_waits_until_the_reset_plus_a_margin(self):
        now = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
        reset = now + timedelta(minutes=30)
        self.assertAlmostEqual(seconds_until(reset, now=now, margin=60),
                               30 * 60 + 60, delta=1)

    def test_a_reset_already_past_waits_only_the_margin(self):
        now = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
        self.assertEqual(seconds_until(now - timedelta(hours=1), now=now, margin=30),
                         30)


class Supervise(unittest.TestCase):
    def test_it_runs_until_the_queue_is_empty(self):
        remaining = [3]

        def runner(_):
            remaining[0] -= 1
            return OK

        out = supervise(runner=runner, has_work=lambda: remaining[0] > 0,
                        budget_tokens=None)
        self.assertEqual(out["ticks"], 3)
        self.assertEqual(out["stopped_because"], "queue_empty")

    def test_it_stops_at_95_percent_of_the_budget(self):
        out = supervise(runner=lambda _: OK, has_work=lambda: True,
                        budget_tokens=100_000)
        # each tick is ~39,916 tokens; the third crosses 95,000
        self.assertEqual(out["ticks"], 3)
        self.assertEqual(out["stopped_because"], "budget")

    def test_a_usage_limit_sleeps_until_reset_and_then_continues(self):
        reset = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        seq = [_limit(reset), OK]
        slept = []
        work = [1]          # one cluster of work; the limit tick does none of it

        def runner(_):
            out = seq.pop(0)
            if out == OK:
                work[0] -= 1
            return out

        out = supervise(runner=runner, has_work=lambda: work[0] > 0,
                        budget_tokens=None, sleeper=slept.append)
        self.assertEqual(len(slept), 1)
        self.assertGreater(slept[0], 0)
        self.assertEqual(out["limit_waits"], 1)
        self.assertEqual(out["stopped_because"], "queue_empty")

    def test_a_limit_refusal_does_not_consume_budget(self):
        reset = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        seq = [_limit(reset), OK]
        out = supervise(runner=lambda _: seq.pop(0), has_work=lambda: bool(seq),
                        budget_tokens=None, sleeper=lambda s: None)
        self.assertEqual(out["tokens"], parse_tick(OK)["tokens"])

    def test_repeated_hard_errors_abort_rather_than_spin(self):
        out = supervise(runner=lambda _: json.dumps({"is_error": True,
                                                     "result": "boom"}),
                        has_work=lambda: True, budget_tokens=None,
                        max_consecutive_errors=3)
        self.assertEqual(out["stopped_because"], "errors")
        self.assertEqual(out["ticks"], 3)

    def test_a_tick_cap_is_honoured(self):
        out = supervise(runner=lambda _: OK, has_work=lambda: True,
                        budget_tokens=None, max_ticks=2)
        self.assertEqual(out["ticks"], 2)
        self.assertEqual(out["stopped_because"], "max_ticks")

    def test_each_tick_is_reported_as_it_happens(self):
        seen = []
        work = [2]

        def runner(_):
            work[0] -= 1
            return OK

        supervise(runner=runner, has_work=lambda: work[0] > 0,
                  budget_tokens=None, on_tick=seen.append)
        self.assertEqual(len(seen), 2)
        self.assertIn("tokens", seen[0])

    def test_the_session_id_is_passed_to_the_next_tick_for_reuse(self):
        # Resuming reuses the cached prompt: cache_read instead of a fresh
        # ~40k cache_creation every invocation.
        got = []
        work = [2]

        def runner(session_id):
            got.append(session_id)
            work[0] -= 1
            return OK

        supervise(runner=runner, has_work=lambda: work[0] > 0, budget_tokens=None)
        self.assertIsNone(got[0])
        self.assertEqual(got[1], "abc-123")


if __name__ == "__main__":
    unittest.main()
