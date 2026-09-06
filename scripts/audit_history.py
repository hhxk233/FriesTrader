"""Reproducible local evidence counts, never inferred fills or investment returns."""
import argparse
from contextlib import closing
from collections import Counter
import datetime as dt
import json
from pathlib import Path

from dry_run_readiness import compute_readiness, load_records, review_key
from market_session import CENTRAL, now_central, session_at
from paper_ledger import report as paper_report
from execution_evidence import capital_status, fingerprint, verified_readiness
import os
import sqlite3


def row_time(row):
    return dt.datetime.fromisoformat(f"{row['date']}T{row['timestamp']}").replace(tzinfo=CENTRAL)


def summarize(trades, proposals, cutoff):
    cutoff = cutoff.astimezone(CENTRAL)
    before = [row for row in trades if row_time(row) <= cutoff]
    today = [row for row in before if row["date"] == cutoff.date().isoformat()]

    def counts(rows):
        cycles = {(r["date"], r["timestamp"]) for r in rows if r.get("stage") == "cycle_summary"}
        summaries = [r for r in rows if r.get("stage") == "cycle_summary"]
        orders = [r for r in rows if r.get("stage") == "order"]
        blocked = [r for r in rows if r.get("stage") == "risk_check" and r.get("passed") is False]
        blocked_versions = {(r.get("proposal_id") or r.get("proposal_date"), r.get("symbol")) for r in blocked}
        regular = [r for r in summaries if session_at(row_time(r))["is_regular_session"]]
        return {
            "completed_cycles": len(cycles),
            "distinct_dates": len({day for day, _ in cycles}),
            "regular_session_cycles": len({(r["date"], r["timestamp"]) for r in regular}),
            "regular_session_dates": len({r["date"] for r in regular}),
            "off_session_cycles": len(cycles) - len({(r["date"], r["timestamp"]) for r in regular}),
            "dry_run_order_records": sum(r.get("mode") == "dry_run" for r in orders),
            "successful_preview_versions": len({review_key(r) for r in orders
                if r.get("mode") == "dry_run" and r.get("would_execute") is True
                and r.get("review_succeeded") is True and r.get("review_failed") is not True
                and review_key(r) is not None}),
            "explicitly_placed_order_records": sum(r.get("placed") is True for r in orders),
            "risk_pass_records": sum(r.get("stage") == "risk_check" and r.get("passed") is True for r in rows),
            "risk_block_records": len(blocked),
            "blocked_proposal_versions": len(blocked_versions),
            "risk_block_reasons": dict(Counter(r.get("reason", "unavailable") for r in blocked)),
        }

    available = [r for r in proposals if row_time(r) <= cutoff]
    latest_time = max((row_time(r) for r in available), default=None)
    latest = [r for r in available if row_time(r) == latest_time]
    screened = [r for r in latest if r.get("stage") == "screened"]
    theses = [r for r in latest if r.get("stage") == "thesis"]
    buckets = {r["decision"]: len(r["symbols"]) for r in latest if r.get("stage") == "summary"}
    # Never reconstruct a day's overwritten Phase A history from the latest file.
    return {
        "cutoff_central": cutoff.isoformat(),
        "coverage": "Local logs only. Fill, P&L, deposit and quote-quality claims require broker reconciliation.",
        "latest_phase_a": {"timestamp": latest_time.isoformat() if latest_time else None,
                           "screened": len(screened), "theses": len(theses), "buckets": buckets,
                           "conviction_mix": dict(Counter(r.get("conviction") for r in theses)),
                           "coverage": "latest available version only; not the sum of all daily runs"},
        "today_phase_b": counts(today),
        "historical_phase_b": counts(before),
        "readiness_counts": compute_readiness(before, 10, 5),
        "performance": {"fills": None, "closed_trades": None, "win_rate": None,
                        "strategy_return": None, "reason": "Previews do not simulate holdings, exits or fill P&L."},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", help="ISO time with UTC offset")
    parser.add_argument("--compact", action="store_true", help="Omit verbose reason histogram for committee input")
    args = parser.parse_args()
    cutoff = dt.datetime.fromisoformat(args.cutoff) if args.cutoff else now_central()
    if cutoff.tzinfo is None:
        parser.error("cutoff must include UTC offset")
    root = Path(__file__).resolve().parent.parent
    result = summarize(load_records(root / "trade_log.jsonl"), load_records(root / "pending_proposals.jsonl"), cutoff)
    # Read the actual configured procedural thresholds; no change to the live gate.
    rules = json.loads((root / "risk_rules.json").read_text(encoding="utf-8-sig"))
    records = [r for r in load_records(root / "trade_log.jsonl") if row_time(r) <= cutoff]
    result["readiness_counts"] = compute_readiness(records, rules["execution"]["dry_run_min_cycles_before_live"],
                                                 rules["execution"]["dry_run_min_successful_reviews_before_live"])
    result["shadow_ledger"] = paper_report(root, cutoff, compact=True)
    private_path = Path(os.environ.get("FRIESTRADER_PRIVATE_CONFIG") or Path.home() / ".codex/state/friestrader/local.json")
    if private_path.is_file():
        private = json.loads(private_path.read_text(encoding="utf-8-sig"))
        capital_path = private_path.parent / "capital_basis.json"
        capital = json.loads(capital_path.read_text(encoding="utf-8-sig")) if capital_path.is_file() else {}
        account = rules["account_number"]
        if account.startswith("YOUR_"):
            account = private["account_number"]
        result["capital_basis"] = capital_status(rules, capital, fingerprint(account))
    path = root / "logs/runtime-evidence.sqlite"
    result["verified_execution_evidence"] = {"verified_regular_dates": 0, "verified_previews": 0, "ready": False}
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            result["verified_execution_evidence"] = verified_readiness(db, rules["execution"], cutoff)
    snapshots = []
    for path in sorted((root / "logs/phase-a-snapshots").glob("*.jsonl")):
        rows = load_records(path)
        if rows and rows[0].get("date") == cutoff.date().isoformat() and row_time(rows[0]) <= cutoff:
            snapshots.append({"source": str(path), "funnel": summarize([], rows, cutoff)["latest_phase_a"]})
    result["archived_phase_a_runs_today"] = snapshots
    if args.compact:
        for key in ("today_phase_b", "historical_phase_b"):
            result[key].pop("risk_block_reasons")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
