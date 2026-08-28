#!/usr/bin/env python3
# Part of FriesTrader (https://github.com/YizhiSong/FriesTrader)
# Copyright (c) 2026 Yizhi Song, MIT License -- see LICENSE
"""Prioritize a saved scan's candidates by existing entry-extension fit.

Reads the saved scan's provisional candidates, in the scan's own order, as a
JSON array from stdin.  Each item must contain ``symbol``, ``current_price``,
and chronological ``daily_closes``.  Candidates at or below the configured
extension limit are placed first, candidates with insufficient history next,
and known-overextended candidates last.  Ordering remains stable inside every
bucket.  This is research prioritization only; Phase B still recalculates and
enforces the hard entry gate with fresh data.
"""

import argparse
import json
import math
import sys


STATUS_RANK = {"within_limit": 0, "unknown": 1, "over_limit": 2}


def finite_positive(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def annotate(candidate, lookback_days, max_extension_pct):
    symbol = candidate.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("candidate has a missing or invalid symbol")
    current_price = candidate.get("current_price")
    if not finite_positive(current_price):
        raise ValueError(f"symbol {symbol!r} has an invalid current_price")
    closes = candidate.get("daily_closes")
    if not isinstance(closes, list):
        raise ValueError(f"symbol {symbol!r} daily_closes must be an array")
    if any(not finite_positive(close) for close in closes):
        raise ValueError(f"symbol {symbol!r} has a non-positive daily close")

    result = dict(candidate)
    result.pop("daily_closes", None)
    if len(closes) < lookback_days:
        result.update(
            {
                "execution_fit": "unknown",
                "moving_average": None,
                "extension_pct": None,
                "lookback_bars_used": len(closes),
            }
        )
        return result

    trailing_closes = closes[-lookback_days:]
    moving_average = sum(trailing_closes) / lookback_days
    extension_pct = (current_price - moving_average) / moving_average
    status = "over_limit" if extension_pct > max_extension_pct else "within_limit"
    result.update(
        {
            "execution_fit": status,
            "moving_average": round(moving_average, 6),
            "extension_pct": round(extension_pct, 6),
            "lookback_bars_used": lookback_days,
        }
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, required=True)
    parser.add_argument("--max-extension-pct", type=float, required=True)
    parser.add_argument("--max-candidates", type=int, required=True)
    args = parser.parse_args()

    if args.lookback_days <= 0 or args.max_candidates < 0:
        parser.error("lookback-days must be positive and max-candidates non-negative")
    if args.max_extension_pct < 0:
        parser.error("max-extension-pct must be non-negative")

    try:
        candidates = json.load(sys.stdin)
        if not isinstance(candidates, list):
            raise ValueError("stdin must contain a JSON array")
        annotated = [
            annotate(candidate, args.lookback_days, args.max_extension_pct)
            for candidate in candidates
        ]
    except (json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    ranked = sorted(annotated, key=lambda item: STATUS_RANK[item["execution_fit"]])
    selected = ranked[: args.max_candidates]
    deferred = ranked[args.max_candidates :]
    print(
        json.dumps(
            {
                "selected": selected,
                "deferred": deferred,
                "counts": {
                    status: sum(item["execution_fit"] == status for item in annotated)
                    for status in STATUS_RANK
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
