#!/usr/bin/env python3
# Part of FriesTrader (https://github.com/YizhiSong/FriesTrader)
# Copyright (c) 2026 Yizhi Song, MIT License -- see LICENSE
"""Validate the machine-readable Phase A -> Phase B handoff.

The validator is intentionally broker-independent. It checks the internal
contract that Phase B relies on and rejects malformed or cross-symbol records
before pending_proposals.jsonl can be committed or passed to the committee.
"""

import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path


SUMMARY_BUCKETS = ["rejected", "no_signal", "avoid", "long", "exit_existing"]
PHASE_A_STAGES = {"screened", "thesis", "summary"}
PRICE_FIELDS = ("current_price", "quote_symbol", "quote_as_of", "high_52_weeks")
PROPOSAL_ID_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})\|([A-Z][A-Z0-9.-]{0,9})$"
)
PRICE_MOVE_RE = re.compile(
    r"price_move_60d:\s*signed\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)),\s*"
    r"absolute\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"\(close_60d_ago:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"->\s*latest_close:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\)"
)
ROUNDING_TOLERANCE = 0.0002


def is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float))


def finite_positive(value):
    return is_number(value) and math.isfinite(value) and value > 0


def parse_timezone_aware(value):
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def load_jsonl(path):
    records = []
    errors = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_number}: record must be a JSON object")
            continue
        records.append((line_number, record))
    if not records and not errors:
        errors.append("file contains no JSON records")
    return records, errors


def require_fields(record, fields, context, errors):
    for field in fields:
        if field not in record:
            errors.append(f"{context}: missing required field {field!r}")


def validate_price_fields(record, context, errors):
    require_fields(record, PRICE_FIELDS, context, errors)
    symbol = record.get("symbol")
    quote_symbol = record.get("quote_symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        errors.append(f"{context}: symbol must be a non-empty string")
    if not isinstance(quote_symbol, str) or not quote_symbol.strip():
        errors.append(f"{context}: quote_symbol must be a non-empty string")
    elif isinstance(symbol, str) and quote_symbol != symbol:
        errors.append(
            f"{context}: quote_symbol {quote_symbol!r} does not match symbol {symbol!r}"
        )
    if not finite_positive(record.get("current_price")):
        errors.append(f"{context}: current_price must be a finite positive number")
    if not finite_positive(record.get("high_52_weeks")):
        errors.append(f"{context}: high_52_weeks must be a finite positive number")
    if not parse_timezone_aware(record.get("quote_as_of")):
        errors.append(f"{context}: quote_as_of must be a timezone-aware ISO-8601 timestamp")


def validate_price_move(signal_check, context, errors):
    if not isinstance(signal_check, str) or "price_move_60d:" not in signal_check:
        return
    match = PRICE_MOVE_RE.search(signal_check)
    if match is None:
        errors.append(
            f"{context}: price_move_60d must include signed value, absolute value, "
            "close_60d_ago, and latest_close"
        )
        return
    signed_value, absolute_value, old_close, latest_close = map(float, match.groups())
    if old_close <= 0:
        errors.append(f"{context}: close_60d_ago must be positive")
        return
    expected_signed = (latest_close - old_close) / old_close
    if abs(signed_value - expected_signed) > ROUNDING_TOLERANCE:
        errors.append(
            f"{context}: signed 60-day move {signed_value} does not match raw closes "
            f"({expected_signed:.6f})"
        )
    if abs(absolute_value - abs(expected_signed)) > ROUNDING_TOLERANCE:
        errors.append(
            f"{context}: absolute 60-day move {absolute_value} does not match raw "
            f"closes ({abs(expected_signed):.6f})"
        )


def validate_records(numbered_records):
    errors = []
    if not numbered_records:
        return ["file contains no valid JSON records"]

    dates = set()
    seen_summary = False
    screened_by_symbol = {}
    thesis_symbols = set()
    summary_decisions = []

    for line_number, record in numbered_records:
        context = f"line {line_number}"
        require_fields(record, ("date", "timestamp", "stage"), context, errors)
        date_value = record.get("date")
        timestamp_value = record.get("timestamp")
        stage = record.get("stage")

        try:
            dt.date.fromisoformat(date_value)
            dates.add(date_value)
        except (TypeError, ValueError):
            errors.append(f"{context}: date must be YYYY-MM-DD")
        try:
            dt.time.fromisoformat(timestamp_value)
        except (TypeError, ValueError):
            errors.append(f"{context}: timestamp must be a time-only ISO value")

        if stage not in PHASE_A_STAGES:
            errors.append(f"{context}: unsupported Phase A stage {stage!r}")
            continue
        if seen_summary and stage != "summary":
            errors.append(f"{context}: {stage!r} record appears after summary records")
        if stage == "summary":
            seen_summary = True

        if stage == "screened":
            require_fields(
                record,
                (
                    "symbol",
                    "passed_filters",
                    "source",
                    "avg_volume",
                    "market_cap",
                    "signal_check",
                ),
                context,
                errors,
            )
            symbol = record.get("symbol")
            if isinstance(symbol, str):
                normalized_symbol = symbol.upper()
                if normalized_symbol in screened_by_symbol:
                    errors.append(f"{context}: duplicate screened symbol {symbol!r}")
                else:
                    screened_by_symbol[normalized_symbol] = (line_number, record)
            if not isinstance(record.get("passed_filters"), bool):
                errors.append(f"{context}: passed_filters must be boolean")
            if record.get("source") not in ("watchlist", "market_scan"):
                errors.append(f"{context}: source must be 'watchlist' or 'market_scan'")
            validate_price_fields(record, context, errors)
            validate_price_move(record.get("signal_check"), context, errors)

        elif stage == "thesis":
            require_fields(
                record,
                (
                    "symbol",
                    "proposal_id",
                    "thesis",
                    "conviction",
                    "invalidation",
                    "direction",
                    "risk_flags",
                    "sources",
                ),
                context,
                errors,
            )
            validate_price_fields(record, context, errors)
            symbol = record.get("symbol")
            proposal_id = record.get("proposal_id")
            proposal_match = (
                PROPOSAL_ID_RE.fullmatch(proposal_id)
                if isinstance(proposal_id, str)
                else None
            )
            if proposal_match is None:
                errors.append(
                    f"{context}: proposal_id must be YYYY-MM-DDTHH:MM:SS|SYMBOL"
                )
            elif (
                proposal_match.group(1) != date_value
                or proposal_match.group(2) != timestamp_value
                or proposal_match.group(3) != symbol
            ):
                errors.append(
                    f"{context}: proposal_id must match this thesis date, timestamp, and symbol"
                )
            normalized_symbol = symbol.upper() if isinstance(symbol, str) else None
            if normalized_symbol in thesis_symbols:
                errors.append(f"{context}: duplicate thesis symbol {symbol!r}")
            elif normalized_symbol is not None:
                thesis_symbols.add(normalized_symbol)

            screened_entry = screened_by_symbol.get(normalized_symbol)
            if screened_entry is None:
                errors.append(f"{context}: thesis has no matching screened record")
            else:
                screened_line, screened = screened_entry
                if screened.get("passed_filters") is not True:
                    errors.append(
                        f"{context}: thesis matches rejected screened record on line "
                        f"{screened_line}"
                    )
                for field in PRICE_FIELDS:
                    if field in record and field in screened and record[field] != screened[field]:
                        errors.append(
                            f"{context}: {field} does not match screened record on line "
                            f"{screened_line}"
                        )

            if record.get("conviction") not in ("high", "medium", "low"):
                errors.append(f"{context}: conviction must be high, medium, or low")
            if record.get("direction") not in ("long", "avoid", "exit_existing"):
                errors.append(f"{context}: unsupported direction {record.get('direction')!r}")
            if not isinstance(record.get("risk_flags"), list):
                errors.append(f"{context}: risk_flags must be an array")
            if not isinstance(record.get("sources"), list) or not record.get("sources"):
                errors.append(f"{context}: sources must be a non-empty array")

            if record.get("direction") == "long":
                require_fields(record, ("pct_below_52wk_high",), context, errors)
                pct = record.get("pct_below_52wk_high")
                current_price = record.get("current_price")
                high_52_weeks = record.get("high_52_weeks")
                if not is_number(pct) or not math.isfinite(pct):
                    errors.append(
                        f"{context}: pct_below_52wk_high must be a finite number"
                    )
                elif finite_positive(current_price) and finite_positive(high_52_weeks):
                    expected_pct = (high_52_weeks - current_price) / high_52_weeks
                    if abs(pct - expected_pct) > ROUNDING_TOLERANCE:
                        errors.append(
                            f"{context}: pct_below_52wk_high {pct} does not match "
                            f"current_price/high_52_weeks ({expected_pct:.6f})"
                        )

        elif stage == "summary":
            require_fields(record, ("decision", "symbols"), context, errors)
            decision = record.get("decision")
            summary_decisions.append(decision)
            if not isinstance(record.get("symbols"), list):
                errors.append(f"{context}: summary symbols must be an array")

    if len(dates) > 1:
        errors.append(f"records contain multiple dates: {sorted(dates)}")
    if summary_decisions != SUMMARY_BUCKETS:
        errors.append(
            "summary decisions must appear exactly once in this order: "
            + ", ".join(SUMMARY_BUCKETS)
        )
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl_path", type=Path)
    args = parser.parse_args()

    if not args.jsonl_path.is_file():
        print(f"Phase A validation failed: file not found: {args.jsonl_path}", file=sys.stderr)
        return 1

    records, errors = load_jsonl(args.jsonl_path)
    errors.extend(validate_records(records))
    if errors:
        print("Phase A validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    screened_count = sum(record["stage"] == "screened" for _, record in records)
    thesis_count = sum(record["stage"] == "thesis" for _, record in records)
    print(
        f"Phase A validation passed: {len(records)} records, "
        f"{screened_count} screened, {thesis_count} theses."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
