import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from audit_history import summarize
from market_session import HOLIDAYS, EARLY_CLOSE, scheduled_plan, session_at
from run_cycle import StageSkipped, cycle_lock, run_cycle


def time(value):
    return dt.datetime.fromisoformat(value)


class CalendarTests(unittest.TestCase):
    def test_all_published_holidays_and_early_closes(self):
        for year, dates in HOLIDAYS.items():
            for day in dates.split():
                with self.subTest(year=year, day=day):
                    self.assertFalse(session_at(time(f"{year}-{day}T12:10:00-06:00"))["is_trading_day"])
        for day in EARLY_CLOSE:
            with self.subTest(day=day):
                self.assertEqual(scheduled_plan(time(f"{day}T12:10:00-06:00" if "11-" in day or "12-" in day
                                                      else f"{day}T12:10:00-05:00"))["action"], "end_of_day")

    def test_weekend_and_labor_day(self):
        for day in ("2026-09-05", "2026-09-06", "2026-09-07"):
            for hour in (8, 9, 12, 14, 15, 16, 20):
                self.assertEqual(scheduled_plan(time(f"{day}T{hour:02d}:10:00-05:00"))["action"], "skip")

    def test_normal_schedule_and_boundaries(self):
        for hour, action in ((8, "skip"), (9, "intraday"), (12, "intraday"), (14, "intraday"),
                             (15, "end_of_day"), (16, "skip"), (20, "skip")):
            self.assertEqual(scheduled_plan(time(f"2026-09-08T{hour:02d}:10:00-05:00"))["action"], action)
        self.assertFalse(session_at(time("2026-09-08T08:29:59-05:00"))["is_regular_session"])
        self.assertTrue(session_at(time("2026-09-08T08:30:00-05:00"))["is_regular_session"])
        self.assertFalse(session_at(time("2026-09-08T15:00:00-05:00"))["is_regular_session"])
        self.assertEqual(scheduled_plan(time("2026-09-08T09:40:00-05:00"))["action"], "skip")

    def test_dst_and_nonobserved_new_year(self):
        self.assertTrue(session_at(time("2026-03-06T15:10:00+00:00"))["is_regular_session"])
        self.assertTrue(session_at(time("2026-03-09T14:10:00+00:00"))["is_regular_session"])
        self.assertTrue(session_at(time("2027-12-31T09:10:00-06:00"))["is_trading_day"])
        self.assertEqual(session_at(time("2026-07-02T14:10:00-05:00"))["state"], "regular")
        with self.assertRaises(ValueError):
            session_at(time("2029-01-02T09:10:00-06:00"))
        with self.assertRaises(ValueError):
            session_at(time("2026-09-08T09:10:00"))


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.current = time("2026-09-08T09:10:00-05:00")
        self.calls = []
        self.vote = True
        self.fail = None

    def invoke(self, script, args):
        self.calls.append((script, args))
        if self.fail == (args[0] if script == "run_codex.ps1" else "committee"):
            raise RuntimeError("injected step failure")
        if script == "run_committee.ps1":
            output = Path(args[args.index("-CommitteeDecisionPath") + 1])
            report = Path(args[args.index("-CommitteeReportPath") + 1])
            mode = args[args.index("-ReviewMode") + 1]
            report.write_text("fixture report", encoding="utf-8")
            output.write_text(json.dumps({"date": "2026-09-08", "review_mode": mode,
                                          "report_path": str(report), "run_phase_b": self.vote}), encoding="utf-8")

    def run_it(self, preview=False):
        return run_cycle(self.repo, self.invoke, lambda: self.current, preview)

    def test_normal_handoff_and_no_duplicate(self):
        self.assertEqual(self.run_it()["phase_b"], "completed")
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.run_it()["reason"], "slot_already_attempted")
        self.assertEqual(len(self.calls), 3)

    def test_skip_vote(self):
        self.vote = False
        self.assertEqual(self.run_it()["phase_b"], "not_run")
        self.assertEqual(len(self.calls), 2)

    def test_failure_does_not_skip_a_step_or_retry(self):
        for step, expected_calls in (("A", 1), ("committee", 2), ("B", 3)):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as folder:
                self.repo = Path(folder)
                self.calls = []
                self.fail = step
                self.assertEqual(self.run_it()["status"], "failed")
                self.assertEqual(len(self.calls), expected_calls)
                self.assertEqual(self.run_it()["status"], "blocked")
                self.assertEqual(len(self.calls), expected_calls)

    def test_post_close_only_runs_review_once(self):
        self.current = time("2026-09-08T15:10:00-05:00")
        self.vote = False
        result = self.run_it()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["phase_a"], "not_run")
        self.assertEqual(result["phase_b"], "not_run")
        self.assertIn("-PostCloseReview", self.calls[0][1])
        self.run_it()
        self.assertEqual(len(self.calls), 1)

    def test_closed_day_and_preview_have_no_side_effects(self):
        self.run_it(preview=True)
        self.current = time("2026-09-05T09:10:00-05:00")
        self.assertEqual(self.run_it()["status"], "skipped")
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_close_during_research_prevents_b(self):
        def invoke(script, args):
            self.invoke(script, args)
            if script == "run_committee.ps1":
                self.current = time("2026-09-08T15:01:00-05:00")
        result = run_cycle(self.repo, invoke, lambda: self.current)
        self.assertEqual(result["phase_b"], "skipped_session_ended")
        self.assertEqual(len(self.calls), 2)

    def test_close_during_a_prevents_committee(self):
        def invoke(script, args):
            self.invoke(script, args)
            self.current = time("2026-09-08T15:01:00-05:00")
        result = run_cycle(self.repo, invoke, lambda: self.current)
        self.assertEqual(result["reason"], "session_ended_after_phase_a")
        self.assertEqual(len(self.calls), 1)

    def test_lock_prevents_overlapping_model_runs(self):
        logs = self.repo / "logs"
        logs.mkdir()
        with cycle_lock(logs / "scheduled-cycle.lock"):
            self.assertEqual(self.run_it()["reason"], "cycle_already_running")
        self.assertEqual(self.calls, [])

    def test_missing_decision_and_invalid_eod_handoff(self):
        result = run_cycle(self.repo, lambda *args: None, lambda: self.current)
        self.assertEqual(result["status"], "failed")
        self.current = time("2026-09-08T15:10:00-05:00")
        self.assertEqual(self.run_it()["status"], "failed")
        self.assertEqual(len(self.calls), 1)

    def test_child_skip_is_not_reported_as_completed_phase(self):
        def invoke(script, args):
            raise StageSkipped("child_calendar_skipped_before_model_start")
        result = run_cycle(self.repo, invoke, lambda: self.current)
        self.assertEqual(result["phase_a"], "skipped_session_ended")
        self.assertEqual(result["committee"], "not_run")

    def test_io_failure_is_not_misreported_as_overlap(self):
        def invoke(script, args):
            raise PermissionError("fixture access denied")
        result = run_cycle(self.repo, invoke, lambda: self.current)
        self.assertEqual(result["status"], "failed")
        self.assertIn("access denied", result["error"])


class StatisticsTests(unittest.TestCase):
    def test_cutoff_versions_and_multiple_reasons(self):
        base = {"date": "2026-09-05", "timestamp": "16:38:17"}
        trades = [{**base, "stage": "cycle_summary", "mode": "dry_run"},
                  {**base, "stage": "risk_check", "symbol": "IOT", "proposal_id": "old|IOT", "passed": False, "reason": "gap"},
                  {**base, "stage": "risk_check", "symbol": "IOT", "proposal_id": "old|IOT", "passed": False, "reason": "extension"},
                  {**base, "timestamp": "21:00:00", "stage": "cycle_summary", "mode": "dry_run"}]
        proposals = [{**base, "stage": "screened", "symbol": "X", "passed_filters": False},
                     {**base, "stage": "summary", "decision": "rejected", "symbols": ["X"]},
                     {**base, "stage": "summary", "decision": "no_signal", "symbols": []}]
        result = summarize(trades, proposals, time("2026-09-05T20:21:06-05:00"))
        self.assertEqual(result["today_phase_b"]["completed_cycles"], 1)
        self.assertEqual(result["today_phase_b"]["risk_block_records"], 2)
        self.assertEqual(result["today_phase_b"]["blocked_proposal_versions"], 1)
        self.assertEqual(result["historical_phase_b"]["regular_session_dates"], 0)
        self.assertEqual(result["latest_phase_a"]["buckets"], {"rejected": 1, "no_signal": 0})
        self.assertIsNone(result["performance"]["win_rate"])


if __name__ == "__main__":
    unittest.main()
