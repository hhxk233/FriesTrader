"""Pure validation of broker evidence. No network calls and no order placement."""
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from market_session import session_at

MAX_QUOTE_AGE_SECONDS = 120
MAX_QUOTE_SKEW_SECONDS = 30
MAX_REVIEW_AGE_SECONDS = 60


def decimal(value, positive=False):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid decimal evidence") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("non-finite or non-positive price/quantity")
    return number


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing_evidence_timestamp")
    value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("evidence timestamp must include timezone")
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def quote_check(quote, symbol, now):
    session = session_at(now)
    if not session["is_regular_session"]:
        raise ValueError("outside_regular_session")
    if not isinstance(quote, dict) or quote.get("symbol") != symbol:
        raise ValueError("missing_or_mismatched_quote")
    if quote.get("state") != "active" or quote.get("has_traded") is not True:
        raise ValueError("inactive_or_untraded_instrument")
    bid, ask = decimal(quote.get("bid_price"), True), decimal(quote.get("ask_price"), True)
    if bid > ask:
        raise ValueError("crossed_quote")
    times = [timestamp(quote[key]) for key in ("venue_bid_time", "venue_ask_time")]
    for observed in times:
        age = (now - observed).total_seconds()
        if age < -5 or age > MAX_QUOTE_AGE_SECONDS or not session_at(observed)["is_regular_session"]:
            raise ValueError("stale_future_or_off_session_quote")
    if abs((times[0] - times[1]).total_seconds()) > MAX_QUOTE_SKEW_SECONDS:
        raise ValueError("asynchronous_bid_ask")
    return {"bid": str(bid), "ask": str(ask), "observed_at": min(times).isoformat()}


def order_key(args):
    allowed = ("account_number", "symbol", "side", "type", "quantity", "dollar_amount",
               "limit_price", "stop_price", "tax_lots")
    values = {key: args[key] for key in allowed if args.get(key) is not None}
    for key in ("quantity", "dollar_amount", "limit_price", "stop_price"):
        if key in values:
            values[key] = str(decimal(values[key], True).normalize())
    if ("quantity" in values) == ("dollar_amount" in values):
        raise ValueError("order_requires_exactly_one_size")
    if args.get("side") not in ("buy", "sell"):
        raise ValueError("invalid_order_side")
    values["market_hours"] = args.get("market_hours", "regular_hours")
    values["time_in_force"] = args.get("time_in_force", "gfd")
    return fingerprint(values)


def payload(response):
    if not isinstance(response, dict) or response.get("isError"):
        raise ValueError("broker_tool_failed")
    if isinstance(response.get("structuredContent"), dict):
        return payload(response["structuredContent"])
    if isinstance(response.get("data"), dict):
        return response["data"]
    for block in response.get("content", []):
        if block.get("type") == "text":
            try:
                return payload(json.loads(block["text"]))
            except (ValueError, TypeError):
                continue
    raise ValueError("missing_structured_broker_evidence")


def capital_status(rules, evidence, account_hash):
    """Net deposits are an attested cash-flow fact, NOT current NAV or buying power."""
    try:
        if (evidence.get("account_hash") != account_hash or evidence.get("confirmed") is not True
                or not evidence.get("source") or not evidence.get("as_of_date")):
            raise ValueError("missing_confirmation")
        dt.date.fromisoformat(evidence["as_of_date"])
        amount = decimal(evidence["net_deposits_usd"], True)
        if amount != decimal(rules["starting_capital_usd"], True):
            raise ValueError("configured_capital_mismatches_confirmed_net_deposits")
        return {"verified": True, "net_deposits_usd": str(amount), "source": evidence["source"]}
    except (ValueError, KeyError, TypeError):
        return {"verified": False, "net_deposits_usd": None,
                "reason": "Net deposits require matching account-specific operator or statement evidence; NAV is not a substitute."}


def verified_readiness(db, execution, now):
    completed = {}
    samples = set()
    for session, at, body in db.execute("SELECT session,at,body FROM evidence WHERE kind='phase_b_completed'"):
        when = timestamp(at)
        if json.loads(body).get("mode") == "dry_run" and when <= now and session_at(when)["is_regular_session"]:
            completed[session] = session_at(when)["date"]
    for event_id, session, at in db.execute("SELECT id,session,at FROM evidence WHERE kind='paper_preview'"):
        if session in completed and timestamp(at) <= now:
            samples.add(event_id)
    dates = len(set(completed.values()))
    return {"verified_regular_dates": dates, "verified_previews": len(samples),
            "required_dates": execution["dry_run_min_cycles_before_live"],
            "required_previews": execution["dry_run_min_successful_reviews_before_live"],
            "ready": dates >= execution["dry_run_min_cycles_before_live"] and
                     len(samples) >= execution["dry_run_min_successful_reviews_before_live"]}
