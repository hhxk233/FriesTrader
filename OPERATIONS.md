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
trading phase; this is not a replacement for quote-timestamp validation inside
a running Phase B or a guarantee it cannot run across the closing time.

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
account/watchlist/scan settings, order tools, entry logic or live-order gates.
In particular, dry-run remains dry-run; collecting enough procedural examples
does not automatically turn on live trading or establish a strategy advantage.

## Inspection and regression (no trading)

```powershell
python -X utf8 scripts\audit_history.py --compact
python -X utf8 -m unittest discover -s scripts -p test_scheduled_cycle.py -v
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
