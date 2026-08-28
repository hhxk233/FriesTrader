You are running the DAILY automated Phase A step (screening & thesis only) for a small real personal trading account on Robinhood (account_number: <your Robinhood account_number>). This repo has already been cloned into your working directory. PHASE_A_TASK.md in this checkout is the full source-of-truth spec for what to do (Steps 1-3) — read and follow it exactly.

First, determine today's REAL date, day-of-week, and time-of-day in America/Chicago (Central) via Bash — do not guess or infer these:
TZ='America/Chicago' date +'%Y-%m-%d'
TZ='America/Chicago' date +'%A'
TZ='America/Chicago' date +'%H:%M:%S'
Use the date as the 'date' field and the time as the 'timestamp' field (time-of-day only, e.g. "16:30:01" — never prepend the date to it) on every line you write, per PHASE_A_TASK.md's Output section.

Read risk_rules.json fresh from this checkout every run — never assume prior values or cache across runs.

Follow PHASE_A_TASK.md's Steps 1-3 exactly, including the screened/thesis/summary line shapes and the End-of-run summary section. Overwrite pending_proposals.jsonl in this checkout with this run's results (do not append to prior contents). Do NOT touch trade_log.jsonl.

Hard stop: the shared Robinhood MCP may expose place_equity_order, review_equity_order, place_option_order, review_option_order, cancel_equity_order, and cancel_option_order, but Phase A must not call any of them. Tool availability does not authorize execution here. Do not check or reference execution.mode.

When pending_proposals.jsonl is fully written, validate it before any git add, commit, push, or Phase B handoff:
python -X utf8 scripts/validate_phase_a.py pending_proposals.jsonl
If validation exits nonzero, stop without staging, committing, pushing, or continuing to Phase B. Report the validation errors; do not weaken or bypass the validator and do not leave a partial handoff.

Only after validation succeeds, commit and push it back to this repo's main branch:
git add pending_proposals.jsonl
git commit -m "Phase A run <date> <timestamp>"
git push origin main
If the push is rejected (e.g. a race with another run), run 'git pull --rebase origin main' once and retry the push once. If it still fails, report the exact conflict/error in your final summary rather than force-pushing or discarding either side's changes.

End with a concise summary of what you screened/filtered/proposed, and confirm the push succeeded (include the resulting commit hash).
