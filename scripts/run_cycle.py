"""Scheduled caller: calendar -> A -> committee -> conditional B, or EOD review.

The existing phase scripts retain all trading rules and tools. No catch-up runs.
"""
import argparse
import contextlib
import datetime as dt
import json
import os
from pathlib import Path
import subprocess

from market_session import now_central, scheduled_plan, session_at


class CycleAlreadyRunning(Exception):
    pass


class StageSkipped(Exception):
    pass


def save_record(path, record):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    temporary.replace(path)


@contextlib.contextmanager
def cycle_lock(path):
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError) as exc:
            raise CycleAlreadyRunning() from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def run_cycle(repo, invoke, clock=now_central, preview=False):
    plan = scheduled_plan(clock())
    if plan["action"] == "skip" or preview:
        return {**plan, "status": "preview" if preview else "skipped"}
    logs = repo / "logs"
    logs.mkdir(exist_ok=True)
    try:
        with cycle_lock(logs / "scheduled-cycle.lock"):
            marker = logs / f"scheduled-cycle-{plan['slot']}.json"
            if marker.exists():
                previous = json.loads(marker.read_text(encoding="utf-8"))
                return {**plan, "status": "skipped" if previous["status"] == "completed" else "blocked",
                        "reason": "slot_already_attempted", "previous_status": previous["status"], "record": str(marker)}
            record = {**plan, "status": "running", "phase_a": "not_run", "committee": "not_run",
                      "phase_b": "not_run", "record": str(marker)}
            save_record(marker, record)
            stamp = clock().strftime("%Y%m%d-%H%M%S-%f")
            decision_path = logs / f"committee-decision-{stamp}.json"
            report_path = logs / f"committee-review-{stamp}.md"
            record.update(committee_decision=str(decision_path), committee_report=str(report_path))

            def still_open():
                current = session_at(clock())
                return current["date"] == plan["date"] and current["is_regular_session"]

            try:
                if plan["action"] == "intraday":
                    if not still_open():
                        raise RuntimeError("session ended before Phase A")
                    record["phase_a"] = "running"
                    save_record(marker, record)
                    invoke("run_codex.ps1", ["A", "-Model", "gpt-5.6-sol"])
                    record["phase_a"] = "completed"
                    if not still_open():
                        record.update(status="completed", reason="session_ended_after_phase_a")
                        save_record(marker, record)
                        return record
                args = ["-Model", "gpt-5.6-luna", "-ReasoningEffort", "medium",
                        "-ReviewMode", plan["action"], "-FreeNewsDesk", "off",
                        "-CommitteeDecisionPath", str(decision_path), "-CommitteeReportPath", str(report_path)]
                if plan["action"] == "end_of_day":
                    args.append("-PostCloseReview")
                record["committee"] = "running"
                save_record(marker, record)
                invoke("run_committee.ps1", args)
                decision = json.loads(decision_path.read_text(encoding="utf-8-sig"))
                if (type(decision.get("run_phase_b")) is not bool or decision.get("date") != plan["date"]
                        or decision.get("review_mode") != plan["action"]
                        or Path(decision.get("report_path", "")).resolve() != report_path.resolve()
                        or not report_path.is_file()):
                    raise ValueError("committee decision does not match this scheduled run")
                record["committee"] = "completed"
                record["decision"] = decision
                if plan["action"] == "end_of_day" and decision["run_phase_b"]:
                    raise ValueError("post-close review must not request Phase B")
                if decision["run_phase_b"] and still_open():
                    record["phase_b"] = "running"
                    save_record(marker, record)
                    invoke("run_codex.ps1", ["B", "-Model", "gpt-5.6-sol"])
                    record["phase_b"] = "completed"
                elif decision["run_phase_b"]:
                    record["phase_b"] = "skipped_session_ended"
                record["status"] = "completed"
            except StageSkipped as exc:
                for stage in ("phase_a", "committee", "phase_b"):
                    if record[stage] == "running":
                        record[stage] = "skipped_session_ended"
                record.update(status="completed", reason=str(exc))
            except Exception as exc:
                record.update(status="failed", error=str(exc))
            save_record(marker, record)
            return record
    except CycleAlreadyRunning:
        return {**plan, "status": "skipped", "reason": "cycle_already_running"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--powershell", required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--at", help="Preview only; never override the execution clock")
    args = parser.parse_args()
    if args.at and not args.preview:
        parser.error("--at requires --preview")
    repo = Path(__file__).resolve().parent.parent

    def invoke(script, arguments):
        command = [args.powershell, "-NoProfile", "-File", str(repo / "scripts" / script), *arguments]
        skipped = False
        with subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace") as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                skipped |= line.startswith(("phase_skipped=", "committee_skipped="))
            code = process.wait()
        if code:
            raise subprocess.CalledProcessError(code, command)
        if skipped:
            raise StageSkipped("child_calendar_skipped_before_model_start")

    clock = (lambda: dt.datetime.fromisoformat(args.at)) if args.at else now_central
    result = run_cycle(repo, invoke, clock, args.preview)
    print("scheduled_cycle=" + json.dumps(result))
    return 1 if result["status"] in ("failed", "blocked") else 0


if __name__ == "__main__":
    raise SystemExit(main())
