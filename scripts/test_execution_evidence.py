import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from execution_evidence import capital_status, fingerprint, order_key, payload, quote_check, verified_readiness
from paper_ledger import replay
from phase_output import validate_b
from tool_evidence_hook import connect, hook, put

NOW = dt.datetime.fromisoformat("2026-09-08T10:00:00-05:00")


def quote(price="10", ask="10.01", when=NOW):
    return {"symbol": "TEST", "bid_price": price, "ask_price": ask, "state": "active", "has_traded": True,
            "venue_bid_time": when.isoformat(), "venue_ask_time": when.isoformat()}


class EvidenceTests(unittest.TestCase):
    def test_good_quote(self):
        self.assertEqual(quote_check(quote(), "TEST", NOW)["ask"], "10.01")

    def test_bad_quote_matrix(self):
        variations = [{"bid_price": "nan"}, {"ask_price": "Infinity"}, {"bid_price": "0"},
                      {"bid_price": "11"}, {"symbol": "OTHER"}, {"state": "inactive"},
                      {"has_traded": False}, {"venue_ask_time": "2026-09-08T10:00:00"},
                      {"venue_bid_time": "2026-09-08T09:59:00-05:00"},
                      {"venue_bid_time": "2026-09-08T09:57:00-05:00"},
                      {"venue_bid_time": "2026-09-08T10:00:10-05:00"}, {"venue_bid_time":None}]
        for update in variations:
            with self.subTest(update=update), self.assertRaises((ValueError, KeyError)):
                quote_check({**quote(), **update}, "TEST", NOW)

    def test_close_blocks_even_recent_quote(self):
        with self.assertRaisesRegex(ValueError, "outside_regular"):
            quote_check(quote(when=NOW.replace(hour=14,minute=59,second=59)), "TEST", NOW.replace(hour=15))

    def test_payload_and_errors(self):
        self.assertEqual(payload({"content": [{"type": "text", "text": '{"data":{"x":1}}'}]}), {"x":1})
        self.assertEqual(payload({"structuredContent": {"data": {"x": 1}}}), {"x":1})
        with self.assertRaises(ValueError):
            payload({"isError": True, "structuredContent": {"data": {"x": 1}}})

    def test_nav_is_not_capital_evidence(self):
        rules = {"starting_capital_usd": 1000}
        self.assertFalse(capital_status(rules, {"total_value": "1008.878"}, "acct")["verified"])
        evidence = {"account_hash": "acct", "confirmed": True, "source": "operator cash-flow confirmation",
                    "as_of_date": "2026-09-05", "net_deposits_usd": "1000"}
        self.assertTrue(capital_status(rules, evidence, "acct")["verified"])
        self.assertFalse(capital_status(rules, {**evidence,"net_deposits_usd":"200"}, "acct")["verified"])
        self.assertFalse(capital_status(rules, evidence, "other-account")["verified"])


class HookTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = connect(Path(self.folder.name) / "test.sqlite")
        self.addCleanup(self.db.close)
        self.env = patch.dict(os.environ, {"FRIESTRADER_PHASE":"B", "FRIESTRADER_RUN_ID":"fixture"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.rules = {"starting_capital_usd":1000, "execution":{"mode":"dry_run",
                     "dry_run_min_cycles_before_live":1, "dry_run_min_successful_reviews_before_live":1},
                     "_readiness":{"ready_for_live":True}}
        self.args = {"account_number":"FAKE", "symbol":"TEST", "side":"buy", "quantity":"1", "type":"market"}
        self.proposals = [{"stage":"thesis","symbol":"TEST","proposal_id":"2026-09-08|TEST|v1"}]
        self.capital = {"account_hash":fingerprint("FAKE"), "confirmed":True,"source":"fixture",
                        "as_of_date":"2026-09-08","net_deposits_usd":"1000"}
        self.counter = 0

    def event(self, name, stage, args=None, data=None, now=NOW):
        self.counter += 1
        event = {"tool_name":"mcp__robinhood_trading__" + name, "hook_event_name":stage,
                 "tool_input": self.args if args is None else args, "session_id":"test",
                 "tool_use_id":str(self.counter), "tool_response":{"structuredContent":{"data":data}}}
        return hook(event, self.db, self.rules, fingerprint("FAKE"), self.capital, self.proposals, now)

    def capture(self):
        self.event("get_equity_quotes", "PostToolUse", {}, {"results":[{"quote":quote()}]})

    def review(self, alert=None, size="1"):
        self.capture()
        self.event("review_equity_order", "PreToolUse")
        self.event("review_equity_order", "PostToolUse", data={**self.args,"quantity":size,
                   "quote_data":quote(),"order_checks":alert or {}})

    def complete(self):
        put(self.db,"complete",fingerprint("fixture"),"phase_b_completed","",NOW,{"mode":"dry_run"})

    def test_quote_required_and_wrong_account(self):
        with self.assertRaises(ValueError):
            self.event("review_equity_order", "PreToolUse")
        self.capture()
        with self.assertRaisesRegex(ValueError,"wrong_account"):
            self.event("review_equity_order", "PreToolUse", {**self.args,"account_number":"OTHER"})

    def test_review_size_mismatch(self):
        with self.assertRaisesRegex(ValueError,"mismatch"):
            self.review(size="2")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM evidence WHERE kind='paper_preview'").fetchone()[0],0)

    def test_dryrun_never_places_and_records_preview_once(self):
        self.review()
        self.review()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM evidence WHERE kind='paper_preview'").fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,"not_live"):
            self.event("place_equity_order", "PreToolUse", {**self.args,"ref_id":"11111111-1111-4111-8111-111111111111"})

    def test_expiry_parameter_change_and_alert(self):
        self.review()
        self.complete()
        self.rules["execution"]["mode"]="live"
        with self.assertRaisesRegex(ValueError,"missing_or_expired"):
            self.event("place_equity_order", "PreToolUse", now=NOW+dt.timedelta(seconds=61))
        with self.assertRaisesRegex(ValueError,"missing_or_expired"):
            self.event("place_equity_order", "PreToolUse", {**self.args,"quantity":"2"})
        self.review(alert={"alert_type":"TEST"})
        with self.assertRaisesRegex(ValueError,"broker_alert"):
            self.event("place_equity_order", "PreToolUse")

    def test_verified_history_and_capital_and_duplicate(self):
        self.review()
        self.rules["execution"]["mode"]="live"
        with self.assertRaisesRegex(ValueError,"verified_regular"):
            self.event("place_equity_order", "PreToolUse")
        self.complete()
        self.capital["confirmed"]=False
        with self.assertRaisesRegex(ValueError,"net_deposit"):
            self.event("place_equity_order", "PreToolUse")
        self.capital["confirmed"]=True
        args = {**self.args,"ref_id":"11111111-1111-4111-8111-111111111111"}
        self.assertEqual(self.event("place_equity_order", "PreToolUse",args),{})
        with self.assertRaisesRegex(ValueError,"already_attempted"):
            self.event("place_equity_order", "PreToolUse",args)

    def test_capital_guard_does_not_block_risk_reducing_sell(self):
        self.args["side"]="sell"
        self.review()
        self.complete()
        self.rules["execution"]["mode"]="live"
        self.capital={}
        self.event("place_equity_order", "PreToolUse", {**self.args,"ref_id":"11111111-1111-4111-8111-111111111111"})

    def test_normalization(self):
        self.assertEqual(order_key(self.args),order_key({**self.args,"quantity":"1.000000"}))

    def test_mechanical_sells_and_unattributed_previews_are_not_lost(self):
        self.proposals=[]
        self.review()
        self.args["side"]="sell"
        self.review()
        self.review()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM evidence WHERE kind='paper_preview'").fetchone()[0],3)


class LedgerTests(unittest.TestCase):
    def row(self, key, side="buy", qty="2", q=None, order_type="market"):
        return (key,"paper_preview","TEST",NOW.isoformat(), {"order":{"side":side,"quantity":qty,
                "symbol":"TEST","type":order_type,"limit_price":"5"},"quote":q or quote(),"proposal_id":key})

    def test_cash_fifo_mark_and_no_backfilled_win_rate(self):
        buy=self.row("buy")
        result=replay([buy,buy],"1000",NOW)
        self.assertEqual(result["hypothetical_fill_count"],1)
        self.assertEqual(result["cash"],"979.98000000")
        self.assertIsNone(result["closed_lot_win_rate"])
        sell=self.row("sell","sell","1",quote("11","11.01"))
        result=replay([buy,sell],"1000",NOW)
        self.assertEqual(result["closed_lot_count"],1)
        self.assertEqual(result["realized_pnl"],"0.99000000")
        self.assertEqual(result["closed_lot_win_rate"],1)

    def test_insufficient_cash_inventory_limits_and_future(self):
        rows=[self.row("cash",qty="200"), self.row("inventory",side="sell"), self.row("limit",order_type="limit")]
        result=replay(rows,"1000",NOW)
        self.assertEqual(result["hypothetical_fill_count"],0)
        self.assertEqual(len(result["skipped"]),3)
        self.assertEqual(replay([self.row("future")],"1000",NOW-dt.timedelta(seconds=1))["hypothetical_fill_count"],0)

    def test_no_stale_price_fills(self):
        result=replay([self.row("old",q=quote(when=NOW-dt.timedelta(minutes=3)))],"1000",NOW)
        self.assertEqual(result["hypothetical_fill_count"],0)

    def test_append_only_phase_b(self):
        before=b'{"stage":"old"}\n'
        for bad in (before,b'{"stage":"changed"}\n',before+b'{"stage":"order"}\n'):
            with self.assertRaises(ValueError):
                validate_b(before,bad)
        self.assertEqual(len(validate_b(before,before+b'{"stage":"cycle_summary"}\n')),1)


if __name__ == "__main__":
    unittest.main()
