#!/usr/bin/env python3
# Part of FriesTrader (https://github.com/YizhiSong/FriesTrader)
# Copyright (c) 2026 Yizhi Song, MIT License -- see LICENSE
"""Compute the historical dry-run evidence used by the live-order gate.

The date requirement measures distinct completed dry-run dates.  The preview
requirement separately measures unique dry-run orders whose Robinhood
``review_equity_order`` call explicitly succeeded.  Merely reaching a
``risk_check`` or writing a failed/cancelled preview does not count.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def load_records(path_value):
    if path_value == "-":
        lines = sys.stdin.read().splitlines()
        source = "stdin"
    else:
        path = Path(path_value)
        if not path.is_file():
            raise ValueError(f"trade log not found: {path}")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        source = str(path)

    records = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{source} line {line_number}: invalid JSON: {exc.msg}"
            ) from exc
        if not isinstance(record, dict):
            raise ValueError(f"{source} line {line_number}: expected a JSON object")
        records.append(record)
    return records


def valid_iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def review_key(record):
    symbol = record.get("symbol")
    action = record.get("action")
    proposal_id = record.get("proposal_id")
    if isinstance(proposal_id, str) and proposal_id.strip():
        version = proposal_id.strip()
    else:
        proposal_date = record.get("proposal_date")
        if valid_iso_date(proposal_date):
            version = proposal_date
        else:
            # Mechanical position-management sells do not always originate
            # from a Phase A proposal. Their own log timestamp identifies the
            # completed preview sample without merging same-day sell calls.
            record_date = record.get("date")
            record_timestamp = record.get("timestamp")
            if not valid_iso_date(record_date) or not isinstance(
                record_timestamp, str
            ):
                return None
            version = f"{record_date}T{record_timestamp}"
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    if action not in ("buy", "sell"):
        return None
    return (version, symbol.upper(), action)


def compute_readiness(records, min_dates, min_successful_reviews):
    dry_run_dates = {
        record["date"]
        for record in records
        if record.get("stage") == "cycle_summary"
        and record.get("mode") == "dry_run"
        and valid_iso_date(record.get("date"))
    }

    successful_review_keys = set()
    for record in records:
        if (
            record.get("stage") != "order"
            or record.get("mode") != "dry_run"
            or record.get("would_execute") is not True
            or record.get("review_succeeded") is not True
            or record.get("review_failed") is True
        ):
            continue
        key = review_key(record)
        if key is not None:
            successful_review_keys.add(key)

    dates_count = len(dry_run_dates)
    reviews_count = len(successful_review_keys)
    blocking_requirements = []
    if dates_count < min_dates:
        blocking_requirements.append("dry_run_dates")
    if reviews_count < min_successful_reviews:
        blocking_requirements.append("successful_dry_run_reviews")

    return {
        "dry_run_dates": dates_count,
        "dry_run_dates_required": min_dates,
        "successful_dry_run_reviews": reviews_count,
        "successful_dry_run_reviews_required": min_successful_reviews,
        "ready_for_live": not blocking_requirements,
        "blocking_requirements": blocking_requirements,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trade-log",
        default="trade_log.jsonl",
        help="path to trade_log.jsonl, or - to read JSONL from stdin",
    )
    parser.add_argument("--min-dates", type=int, required=True)
    parser.add_argument("--min-successful-reviews", type=int, required=True)
    args = parser.parse_args()

    if args.min_dates < 0 or args.min_successful_reviews < 0:
        parser.error("minimum counts must be non-negative")

    try:
        records = load_records(args.trade_log)
        result = compute_readiness(
            records, args.min_dates, args.min_successful_reviews
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
