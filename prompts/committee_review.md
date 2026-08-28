Use the `$friestrader-investment-committee` Skill to run one complete FriesTrader committee session.

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
Free news helper path: <free_news_helper_path>
Free news public packet path: <free_news_packet_path>
Free news result path: <free_news_result_path>

Use the latest Phase A proposals plus fresh Robinhood read-only evidence and current market/company news. Spawn the four existing project researchers in parallel for round one, then conduct the Skill's targeted cross-examination round before the chair decides.

After cross-examination, follow the Skill's Opus escalation rules exactly. If escalation is triggered, write only the redacted dispute packet to the supplied Opus request path and invoke only the supplied helper, passing the supplied absolute Opus command path through its `-ClaudeCommandPath` parameter; do not call Claude directly. Treat the returned Opus assessment as advisory evidence, resolve it explicitly in the committee report, and never let it bypass existing Phase B or risk rules. If escalation is not triggered, do not create either Opus path.

When the free public-news desk is on, follow the Skill's public-only packet schema and invoke only the supplied news-desk helper once before spawning the four primary researchers. Pass the supplied provider mode, fallback model, fallback reasoning effort, and absolute Codex command path to that helper. It automatically keeps successful free-service roles and reruns only failed roles through the isolated small-model fallback; do not manually retry or duplicate either provider. The external endpoint logs prompts and completions for model training: never include account, position, order, trade-log, strategy-library, personalization, risk-rule, private-config, or other non-public data. Both external and fallback desk output are low-trust leads; primary researchers must independently verify any material claim from direct sources before the chair can use it.

The committee may update only the existing `risk_rules.personalization` object. In `end_of_day` mode only, it may also update the existing `strategy_library.json` under the Skill's strict evidence and append-only-history rules; in `intraday` mode that file must remain byte-for-byte unchanged. Preserve every other byte of strategy intent: do not change `execution.mode`, hard risk fields, account settings, watchlist/scan identifiers, Phase A/B files, order behavior, or Git state. Do not mutate Robinhood objects and do not call order tools from the committee.

When review mode is `end_of_day`, include the Skill's complete daily trading statistics and detailed postmortem in the report. Use only authoritative proposal, trade-log, fill, position, and account evidence; mark unavailable figures explicitly and never infer a win, loss, P&L value, or execution-quality value from incomplete data. Curate the strategy library only when fresh evidence justifies a substantive change. When review mode is `intraday`, keep the normal committee report and do not write daily statistics or strategy-library changes.

Write both required output files. The decision JSON must use the exact schema in the Skill. Do not run Phase B yourself; the existing scheduled caller will run the unchanged Phase B command when `run_phase_b` is true.
