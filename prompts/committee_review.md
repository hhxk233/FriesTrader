Use the `$friestrader-investment-committee` Skill to run one complete FriesTrader committee session.

You are already the committee chair process launched by `scripts\run_committee.ps1`. Execute the committee session directly in this process. Never invoke `scripts\run_committee.ps1`, never launch another committee chair, and never delegate the full committee session to a nested Codex process. The supplied free-news helper may launch its own isolated small-model workers; that is not a nested committee.

Review date in America/Chicago: <central_date>
Review mode: <review_mode>
Committee report path: <committee_report_path>
Decision JSON path: <committee_decision_path>
Opus escalation mode: <opus_escalation_mode>
Claude CLI available: <opus_available>
Opus model: <opus_model>
Opus effort: <opus_effort>
Opus maximum budget USD: <opus_max_budget_usd>
Opus helper path: <opus_helper_path>
Opus command path: <opus_command_path>
Opus request path: <opus_request_path>
Opus result path: <opus_result_path>
Free public-news desk: <free_news_desk_mode>
Free news agents: <free_news_agents>
Free news concurrency: <free_news_concurrency>
Free news provider mode: <free_news_provider_mode>
Free news Codex fallback model: <free_news_fallback_model>
Free news fallback reasoning effort: <free_news_fallback_reasoning_effort>
Codex command path: <codex_command_path>
Current PowerShell command path: <powershell_command_path>
Free news helper path: <free_news_helper_path>
Free news public packet path: <free_news_packet_path>
Free news result path: <free_news_result_path>

Use the latest Phase A proposals plus fresh Robinhood read-only evidence and current market/company news. Spawn the four existing project researchers in parallel for round one, then conduct the Skill's targeted cross-examination round before the chair decides.

Use these evidence-resolution and handoff rules when applying the existing committee Skill:

- Treat an authoritative primary source that conclusively resolves a Phase A wording or classification error as resolved evidence. Correct the record explicitly in the report and assess whether the correction changes direction, conviction, invalidation, or risk. A resolved wording defect is not by itself an unresolved accounting-basis mismatch and is not by itself a reason to require another Phase A run before a dry-run Phase B handoff.
- The 3% entry-gap check compares a fresh ask with the current proposal's exact thesis-time `current_price`. The 10% extension check compares a fresh ask with the configured moving-average reference through the existing Phase B helper. A move from the prior official close is market context only. Never claim either hard gate passed or failed from a prior-close return; if the exact proposal-relative or moving-average input is unavailable, mark that gate untested and leave it to Phase B.
- `run_phase_b=true` means only that at least one current proposal should enter the unchanged Phase B risk/review workflow; it is not an endorsement, an order authorization, or a bypass of any gate. An all-cash account, no current holding, researcher disagreement, or a non-unanimous vote is not an automatic veto. Conversely, set it to false when no proposal is decision-ready after resolved evidence is incorporated.
- The chair must decide from evidence after cross-examination. Do not use unanimity, Opus agreement, or the mere existence of a correctable wording defect as a hidden extra gate.

After cross-examination, follow the Skill's Opus escalation rules exactly. If escalation is triggered, write only the redacted dispute packet to the supplied Opus request path and invoke only the supplied helper in the current PowerShell tool shell with `& '<opus_helper_path>'`; pass the supplied absolute Opus command path through its `-ClaudeCommandPath` parameter. Do not start another `pwsh`/`powershell` process, guess an executable path, retry a failed launch, or call Claude directly. Treat the returned Opus assessment as advisory evidence, resolve it explicitly in the committee report, and never let it bypass existing Phase B or risk rules. If escalation is not triggered, do not create either Opus path.

When the free public-news desk is on, follow the Skill's public-only packet schema and invoke only the supplied news-desk helper once before spawning the four primary researchers. Invoke it directly in the current PowerShell tool shell with `& '<free_news_helper_path>'`; do not start another `pwsh`/`powershell` process, guess an executable path, or retry a failed launch. Pass the supplied provider mode, fallback model, fallback reasoning effort, and absolute Codex command path to that helper. The helper keeps successful free-service roles and, inside this committee sandbox, records unsuccessful roles in `fallback.deferred_to_committee` instead of recursively launching another Codex CLI. For those roles, follow the Skill and use the named `public_news_analyst` Luna subagent in bounded batches, then close all news-agent handles before spawning the four strong primary researchers. Do not retry failed news agents or duplicate a successful external role. A `skipped` or `failed` result is a recorded optional-news degradation, not a reason to stop the committee or invoke the helper again. The external endpoint logs prompts and completions for model training: never include account, position, order, trade-log, strategy-library, personalization, risk-rule, private-config, or other non-public data. Both external and fallback desk output are low-trust leads; primary researchers must independently verify any material claim from direct sources before the chair can use it.

The committee may update only the existing `risk_rules.personalization` object. In `end_of_day` mode only, it may also update the existing `strategy_library.json` under the Skill's strict evidence and append-only-history rules; in `intraday` mode that file must remain byte-for-byte unchanged. Preserve every other byte of strategy intent: do not change `execution.mode`, hard risk fields, account settings, watchlist/scan identifiers, Phase A/B files, order behavior, or Git state. Do not mutate Robinhood objects and do not call order tools from the committee.

When review mode is `end_of_day`, include the Skill's complete daily trading statistics and detailed postmortem in the report. Use only authoritative proposal, trade-log, fill, position, and account evidence; mark unavailable figures explicitly and never infer a win, loss, P&L value, or execution-quality value from incomplete data. Curate the strategy library only when fresh evidence justifies a substantive change. When review mode is `intraday`, keep the normal committee report and do not write daily statistics or strategy-library changes.

Write both required output files. The decision JSON must use the exact schema in the Skill. Do not run Phase B yourself; the existing scheduled caller will run the unchanged Phase B command when `run_phase_b` is true.
