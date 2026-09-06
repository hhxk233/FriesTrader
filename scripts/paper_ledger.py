"""Forward-only shadow accounting of timestamp-validated dry-run previews.

Not an execution simulator: hypothetical immediate market/marketable-limit fills
at observed ask/bid, zero fees/slippage, FIFO basis. No invented exits or backfills.
Its cash, holdings and results NEVER affect the live account or live-readiness gate.
"""
import argparse
from contextlib import closing
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

from execution_evidence import decimal, quote_check, timestamp
from market_session import now_central


def replay(events, initial_cash, cutoff):
    cash = decimal(initial_cash, True)
    basis = cash
    lots, marks = defaultdict(list), {}
    seen, fills, skips, closed = set(), [], [], []
    for event_id, kind, symbol, at, body in events:
        observed = timestamp(at)
        if observed > cutoff:
            continue
        try:
            if kind == "quote":
                checked = quote_check(body, symbol, observed)
                marks[symbol] = (decimal(checked["bid"]), checked["observed_at"])
                continue
            if kind != "paper_preview" or event_id in seen:
                continue
            seen.add(event_id)
            order, quote = body["order"], body["quote"]
            checked = quote_check(quote, symbol, observed)
            side = order["side"]
            if side not in ("buy", "sell"):
                raise ValueError("invalid_side")
            price = decimal(checked["ask"] if side == "buy" else checked["bid"], True)
            if order["type"] not in ("market", "limit"):
                raise ValueError("conditional_order_not_simulated")
            if order["type"] == "limit":
                limit = decimal(order["limit_price"], True)
                if (side == "buy" and limit < price) or (side == "sell" and limit > price):
                    raise ValueError("unmarketable_limit_no_fill_assumed")
            qty = decimal(order["quantity"], True) if order.get("quantity") else decimal(order["dollar_amount"], True) / price
            qty = qty.quantize(decimal("0.000001"), rounding="ROUND_DOWN")
            if qty <= 0:
                raise ValueError("quantity_rounds_to_zero")
            notional = qty * price
            if side == "buy":
                if notional > cash:
                    raise ValueError("insufficient_shadow_cash")
                cash -= notional
                lots[symbol].append({"quantity": qty, "cost": price, "event_id": event_id,
                                     "proposal_id": body.get("proposal_id")})
            else:
                if qty > sum(lot["quantity"] for lot in lots[symbol]):
                    raise ValueError("no_shadow_inventory_for_sell")
                remaining = qty
                while remaining:
                    lot = lots[symbol][0]
                    sold = min(remaining, lot["quantity"])
                    closed.append({"symbol": symbol, "quantity": str(sold),
                                   "pnl": (price - lot["cost"]) * sold,
                                   "entry_event": lot["event_id"], "exit_event": event_id,
                                   "proposal_id": lot["proposal_id"]})
                    lot["quantity"] -= sold
                    remaining -= sold
                    if not lot["quantity"]:
                        lots[symbol].pop(0)
                cash += notional
            marks[symbol] = (decimal(checked["bid"]), checked["observed_at"])
            fills.append({"id": event_id, "symbol": symbol, "side": side, "quantity": str(qty),
                          "assumed_price": str(price), "at": at, "proposal_id": body.get("proposal_id")})
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            skips.append({"id": event_id, "symbol": symbol, "reason": str(exc)})
    positions, stale = [], []
    market_value = decimal(0)
    cost_value = decimal(0)
    for symbol, holdings in sorted(lots.items()):
        if not holdings:
            continue
        qty = sum(lot["quantity"] for lot in holdings)
        cost = sum(lot["quantity"] * lot["cost"] for lot in holdings)
        mark, at = marks[symbol]
        market_value += qty * mark
        cost_value += cost
        if timestamp(at).astimezone(cutoff.tzinfo).date() != cutoff.date():
            stale.append(symbol)
        positions.append({"symbol": symbol, "quantity": str(qty), "cost": str(cost),
                          "mark_price": str(mark), "mark_as_of": at, "value": str(qty * mark)})
    realized = sum((lot["pnl"] for lot in closed), decimal(0))
    wins = sum(lot["pnl"] > 0 for lot in closed)
    for lot in closed:
        lot["pnl"] = str(lot["pnl"])
    return {"simulation_only": True, "model": "forward preview replay, immediate ask/bid, zero fees/slippage, FIFO",
            "limitations": "Not a full strategy backtest. No fills from old previews, no invented exits, no claim of edge. Marks are as-of, not necessarily current.",
            "initial_cash": str(basis), "cash": str(cash), "positions": positions,
            "hypothetical_fill_count": len(fills), "closed_lot_count": len(closed),
            "closed_lot_win_rate": wins / len(closed) if closed else None,
            "realized_pnl": str(realized), "unrealized_pnl_at_marks": str(market_value - cost_value),
            "nav_at_marks": str(cash + market_value),
            "return_at_marks": str((cash + market_value - basis) / basis), "stale_mark_symbols": stale,
            "fills": fills, "closed_lots": closed, "skipped": skips}


def report(root, cutoff, compact=False):
    path = root / "logs/runtime-evidence.sqlite"
    # The originally requested $1000 is a frozen HYPOTHETICAL budget, never a deposit assertion.
    events = []
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            rows = db.execute("SELECT id,kind,symbol,at,body FROM evidence ORDER BY rowid").fetchall()
            events = [(a,b,c,d,json.loads(e)) for a,b,c,d,e in rows]
    result = replay(events, "1000", cutoff)
    if compact:
        for key in ("fills", "closed_lots", "skipped"):
            result[key + "_count"] = len(result.pop(key))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    print(json.dumps(report(root, timestamp(args.cutoff) if args.cutoff else now_central(), args.compact), indent=2))
