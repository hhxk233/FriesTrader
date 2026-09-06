"""Codex pre/post MCP hook: session/quote checks and an append-only evidence journal.

No broker credentials, requests or orders are issued by this module. Hook payloads
are untrusted data. The journal stores only selected fields, not account numbers.
"""
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
import argparse
from contextlib import closing
import re

from dry_run_readiness import compute_readiness, load_records
from execution_evidence import (capital_status, decimal, fingerprint, order_key,
                                payload, quote_check, timestamp, verified_readiness, MAX_REVIEW_AGE_SECONDS)
from market_session import now_central, session_at

ROOT = Path(__file__).resolve().parent.parent


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, session TEXT, kind TEXT, "
               "symbol TEXT, at TEXT, body TEXT)")
    return db


def put(db, event_id, session, kind, symbol, now, body):
    db.execute("INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?)",
               (event_id, session, kind, symbol, now.isoformat(), json.dumps(body, sort_keys=True)))


def latest(db, session, kind, symbol):
    row = db.execute("SELECT at,body FROM evidence WHERE session=? AND kind=? AND symbol=? "
                     "ORDER BY rowid DESC LIMIT 1", (session, kind, symbol)).fetchone()
    return (timestamp(row[0]), json.loads(row[1])) if row else (None, None)


def hook(event, db, rules, account_hash, capital, proposals, now):
    name = event.get("tool_name", "").split("__")[-1]
    stage = event.get("hook_event_name")
    args = event.get("tool_input", {})
    if not isinstance(args, dict):
        raise ValueError("invalid_tool_arguments")
    session = fingerprint(os.environ.get("FRIESTRADER_RUN_ID") or event["session_id"])
    event_id = fingerprint([session, event["tool_use_id"], stage])
    symbol = args.get("symbol", "")
    order = name in ("review_equity_order", "place_equity_order")
    if stage == "PreToolUse" and order:
        if not session_at(now)["is_regular_session"]:
            raise ValueError("outside_regular_session: do not queue orders after close")
        if fingerprint(args.get("account_number")) != account_hash:
            raise ValueError("wrong_account")
        if args.get("market_hours", "regular_hours") != "regular_hours":
            raise ValueError("non_regular_order_session")
        signature = order_key(args)
        _, quote = latest(db, session, "quote", symbol)
        quote_check(quote, symbol, now)
        if name == "place_equity_order":
            if rules["execution"]["mode"] != "live":
                raise ValueError("execution_mode_is_not_live")
            when, reviewed = latest(db, session, "review:" + signature, symbol)
            if not reviewed or not 0 <= (now - when).total_seconds() <= MAX_REVIEW_AGE_SECONDS:
                raise ValueError("missing_or_expired_exact_order_review")
            quote_check(reviewed["quote"], symbol, now)
            if not reviewed["clear"]:
                raise ValueError("broker_alert_requires_resolution")
            if not rules.get("_readiness", {}).get("ready_for_live"):
                raise ValueError("existing_live_readiness_not_met")
            if not verified_readiness(db, rules["execution"], now)["ready"]:
                raise ValueError("verified_regular_session_evidence_not_met")
            if args["side"] == "buy" and not capital_status(rules, capital, account_hash)["verified"]:
                raise ValueError("unverified_net_deposit_basis: reconcile funding before live buys")
            uuid.UUID(args.get("ref_id", ""))
            ref = fingerprint(args["ref_id"])
            if db.execute("SELECT 1 FROM evidence WHERE id=?", (ref,)).fetchone():
                raise ValueError("order_already_attempted: reconcile broker state, do not blindly retry")
            # Write before forwarding: a timeout is uncertain delivery, never a new order.
            put(db, ref, session, "placement_attempt", symbol, now, {"signature": signature})
        return {}
    if stage != "PostToolUse":
        return {}
    data = payload(event.get("tool_response"))
    if name == "get_equity_quotes":
        for item in data.get("results") or []:
            if not item or not isinstance(item.get("quote"), dict):
                continue
            quote = item["quote"]
            ticker = quote.get("symbol", "")
            put(db, event_id + ticker, session, "quote", ticker, now, quote)
    elif name == "get_portfolio":
        if fingerprint(args.get("account_number")) == account_hash:
            safe = {key: data.get(key) for key in ("total_value", "cash", "equity_value", "pending_deposits", "currency")}
            put(db, event_id, session, "portfolio", "", now, safe)
    elif name == "review_equity_order":
        if fingerprint(args.get("account_number")) != account_hash:
            raise ValueError("wrong_account_review")
        for key in ("symbol", "side", "type"):
            if data.get(key) != args.get(key):
                raise ValueError("review_response_mismatch")
        for key in ("quantity", "dollar_amount", "limit_price", "stop_price"):
            if args.get(key) is not None and decimal(data.get(key), True) != decimal(args[key], True):
                raise ValueError("review_size_or_price_mismatch")
        quote = data.get("quote_data")
        quote_check(quote, symbol, now)
        if not isinstance(data.get("order_checks"), dict):
            raise ValueError("missing_order_checks")
        clear = data["order_checks"] == {}
        signature = order_key(args)
        put(db, event_id, session, "review:" + signature, symbol, now, {"quote": quote, "clear": clear})
        if clear and rules["execution"]["mode"] == "dry_run" and os.environ.get("FRIESTRADER_PHASE") == "B":
            matches = [p for p in proposals if p.get("stage") == "thesis" and p.get("symbol") == symbol]
            proposal_id = matches[-1].get("proposal_id") if matches else None
            # Mechanical sells may have no Phase A thesis. Use the call id rather than invent attribution.
            sample_id = (fingerprint([proposal_id, symbol, args["side"]]) if proposal_id and args["side"] == "buy"
                         else fingerprint([event_id, "paper"]))
            safe_args = {key: args.get(key) for key in ("symbol", "side", "type", "quantity", "dollar_amount", "limit_price")}
            put(db, sample_id, session, "paper_preview", symbol, now,
                {"order": safe_args, "quote": quote, "proposal_id": proposal_id,
                 "simulation_only": True, "capital_basis_verified": capital_status(rules, capital, account_hash)["verified"]})
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=ROOT / "logs/runtime-evidence.sqlite",
                        help="Alternative journal for isolated hook integration tests")
    options = parser.parse_args()
    event = {}
    try:
        event = json.load(sys.stdin)
        # The file lives in this checkout; never trust event.cwd as a storage/config path.
        private_path = Path(os.environ.get("FRIESTRADER_PRIVATE_CONFIG") or
                            Path.home() / ".codex/state/friestrader/local.json")
        private = json.loads(private_path.read_text(encoding="utf-8-sig"))
        rules = json.loads((ROOT / "risk_rules.json").read_text(encoding="utf-8-sig"))
        account = rules["account_number"]
        if account.startswith("YOUR_"):
            account = private["account_number"]
        capital_path = private_path.parent / "capital_basis.json"
        capital = json.loads(capital_path.read_text(encoding="utf-8-sig")) if capital_path.is_file() else {}
        if event.get("tool_name", "").endswith("__place_equity_order"):
            execution = rules["execution"]
            rules["_readiness"] = compute_readiness(load_records(ROOT / "trade_log.jsonl"),
                execution["dry_run_min_cycles_before_live"], execution["dry_run_min_successful_reviews_before_live"])
        proposals = load_records(ROOT / "pending_proposals.jsonl")
        with closing(connect(options.journal)) as db, db:
            result = hook(event, db, rules, fingerprint(account), capital, proposals, now_central())
        print(json.dumps(result))
        return 0
    except Exception as exc:
        # Do not leak raw tool input, account identifiers, or arbitrary broker error text.
        code = str(exc).split(":", 1)[0]
        reason = code if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]{3,100}", code) else "evidence_validation_failed"
        try:
            with closing(connect(options.journal)) as db, db:
                session = fingerprint(os.environ.get("FRIESTRADER_RUN_ID") or event.get("session_id"))
                put(db, fingerprint([session,event.get("tool_use_id"),"blocked"]),session,"blocked_call","",now_central(),
                    {"reason":reason,"phase":os.environ.get("FRIESTRADER_PHASE"),
                     "stage":event.get("hook_event_name"),"tool":event.get("tool_name","").split("__")[-1]})
        except Exception:
            reason = "validation_and_audit_storage_failed"
        if event.get("hook_event_name") == "PreToolUse":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                  "permissionDecision": "deny", "permissionDecisionReason": "FriesTrader: " + reason}}))
        else:
            print(json.dumps({"decision": "block", "reason": "FriesTrader evidence not accepted: " + reason}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
