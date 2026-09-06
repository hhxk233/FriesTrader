# Current Codex CLI operation

The scheduled entry point is `scripts/run_cycle.ps1`. Do not replay the old
four-daily A/committee/B heartbeat instructions or catch up missed slots.
All times below are America/Chicago, including daylight saving.

| Day / time | Work |
| --- | --- |
| Normal exchange day, 09:10 / 12:10 / 14:10 | Phase A -> four-researcher, two-round committee -> conditional Phase B |
| Normal exchange day, 15:10 | One end-of-day committee/reconciliation; no new A or B |
| Early-close day, 09:10 | Intraday cycle |
| Early-close day, 12:10 | End-of-day review; later wakeups exit immediately |
| Weekend | No scheduled wakeups |
| Exchange holiday | Calendar check exits before research/model calls |

The heartbeat runs on weekdays at the four configured times. Its short outer
wakeup still occurs on weekday holidays; it invokes only the local calendar
check and then exits. Each start slot allows 30 minutes of scheduler delay, not
unlimited catch-up. The current slot gets one attempt, guarded by a process lock
and a persistent record in `logs/scheduled-cycle-*.json`. Failures stop subsequent
steps. Incomplete/failed attempts are not automatically replayed because order
delivery could be uncertain; inspect the record before a manual recovery.

NYSE's [published calendar](https://www.nyse.com/trade/hours-calendars) is embedded
for 2026-2028. Unknown years fail explicitly. Exceptional unscheduled exchange
closures require a calendar update. Closed-session protection is also applied
to direct A/B/committee entry points. The cycle rechecks the session before each
trading phase. A per-tool MCP hook additionally checks at review/placement time,
so a Phase B that runs across closing cannot queue its next order through those
supported tool paths. Quote timestamps must be regular-session, at most 120 seconds
old (5-second future-clock tolerance), with bid/ask skew at most 30 seconds,
positive prices, non-crossed book and active instrument. Placement also requires
an exact alert-free preview within 60 seconds, the unchanged original live gate,
forward verified regular-session samples at the existing numerical thresholds,
and confirmed net-deposit basis for buys. Capital uncertainty does not block sells.
An attempted order ref_id is recorded before forwarding; uncertain delivery is
reconciled instead of blindly retried. No order tools are removed.

The launcher uses the actual `codex.exe` first, checks its loaded hooks through
the local app-server (no model call), and only then enables those vetted hooks
for that invocation. Unreviewed hooks from another source cause a preflight error.
This follows the official [Codex Hooks](https://learn.chatgpt.com/docs/hooks)
contract. Hooks are a guardrail for supported MCP paths, not a broker-side atomic
execution guarantee or an adversarial sandbox. Direct untrusted CLI sessions can
skip hooks; use the project launcher. This does not enable live trading.

## Simpler research and auditable counts

- Keep the existing chair, four primary researchers, two rounds and conditional
  Opus consultation. Primary researchers search original news sources directly.
- Default the optional eight-role external news desk to off. Do not recreate it
  as eight fallback agents. Its existing manual opt-in remains available.
- Supply deterministic local counts through committee start. Separate calendar
  dates from regular-session dates, risk-rejection records from unique rejected
  proposal versions, and broker facts from local previews.
- A research hypothesis can enter the existing strategy library as candidate or
  observing with attributable support, opposition, sample size, invalidation and
  next test. No fills does not justify inventing a return or declaring an edge.
- Intraday cannot modify the strategy library. End-of-day may update it under
  existing validation; only `risk_rules.json.personalization` is committee-owned.

No changes were made to Phase A/B task text, phase prompts, hard risk rules,
account/watchlist/scan settings, order tools or entry logic. The caller now enforces
timestamp evidence and actual-configuration checks alongside the original live gate.
In particular, dry-run remains dry-run; collecting enough procedural examples
does not automatically turn on live trading or establish a strategy advantage.

## Inspection and regression (no trading)

```powershell
python -X utf8 scripts\audit_history.py --compact
python -X utf8 -m unittest discover -s scripts -p 'test_*.py' -v
python -X utf8 scripts\paper_ledger.py --compact
.\scripts\run_cycle.ps1 -Preview -At '2026-09-08T09:10:00-05:00'
.\scripts\run_cycle.ps1 -Preview -At '2026-11-27T12:10:00-06:00'
```

`-At` is preview-only and cannot override the execution clock. A normal scheduled
invocation is `.\scripts\run_cycle.ps1`; inspect its `scheduled_cycle` JSON and
the referenced decision/report. Do not independently run B again after it.

Historical observations as of 2026-09-05: 22 completed Phase B cycles across
9 calendar dates; only 5 cycles across 4 dates occurred during regular sessions.
31 unique successful previews are workflow evidence. Local logs have zero
explicitly placed order records, but local records alone do not reconcile broker
fills. Preview-only operation does not maintain simulated positions/exits/P&L,
so strategy return and win rate remain unavailable. Historical records and the
existing procedural readiness calculation have not been rewritten.

## Forward accounting and funding evidence

Successful new Phase A files are archived under `logs/phase-a-snapshots/` before
the caller publishes output. Phase B must preserve the old trade-log byte prefix
and append exactly one new final cycle_summary; an unchanged old log is an error.
The raw MCP evidence journal is `logs/runtime-evidence.sqlite` (local, ignored by
Git). It records selected public quote fields, account-free portfolio summaries,
verified previews, denied calls and completed B sessions. Account numbers are
never stored; identities use hashes. It is serialized transactionally by SQLite.

The shadow ledger replays only forward timestamp-validated dry-run previews.
Its frozen $1000 hypothetical cash is NOT an assertion of broker deposits. It
tracks cash, FIFO lots, observed bid valuations, partial/full sells and simulated
realized P&L. No overspending, shorting, unmarketable-limit fills, historical
backfills, or invented exits. Assumptions are explicit: immediate ask/bid fills,
zero fees/slippage, no fill probability model. This is useful prospective
accounting, not a complete backtest or clone of the strategy's portfolio decisions.
If no subsequent sell preview exists, there is no closed-lot win rate to report.
The committee sees these figures separately from actual broker performance.

`capital_basis.json` next to the private `local.json` must attest the account's
net contributed capital, including the chosen cash-flow valuation of in-kind
transfers. Fields: account_hash (execution_evidence.fingerprint of the account),
confirmed (true), net_deposits_usd, as_of_date (YYYY-MM-DD), and source. It must
match the configured starting_capital_usd; current NAV, interest, unrealized
gains and tax cost basis are not substitutes. The operator updates this evidence
after funding changes; the committee never writes it or changes hard settings.
Missing/mismatched evidence blocks live buys, but allows labelled dry-run previews
and does not independently block risk-reducing sells. Transferred BOXX is external
funding, not a strategy win; pending cost/lot data remains unavailable.
