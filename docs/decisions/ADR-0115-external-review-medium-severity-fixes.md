# ADR-0115: second independent review — MEDIUM-severity fixes and residual doc drift

**Status:** Accepted
**Session:** 37 (continued)

## Context

ADR-0114 fixed the 3 confirmed HIGH-severity findings from the second,
independent 16-agent/727-file review (`main` @ `145ea95`, post-ADR-0113)
and explicitly deferred the report's ~40 MEDIUM and ~90 LOW findings.
The account owner asked to continue through MEDIUM ("미디움까지
처리"), then, mid-pass, to continue on through LOW as a follow-up once
MEDIUM was done ("미디움 끝나고 로우까지 처라"). This ADR records the
MEDIUM pass; the LOW pass is tracked separately (see `PROJECT_STATUS.md`
for its own session entry once complete).

**Method, unchanged from every prior review-remediation ADR in this
project**: every MEDIUM finding was independently re-verified against
the real source before any fix — several claims in the report were
imprecise, already-fixed by an earlier fix in this same pass, or (in a
few cases) simply wrong, and are noted as such below rather than
"fixed" anyway. Every real fix carries a regression test verified via
`git stash` to fail without the fix and pass with it, following this
project's own established discipline. Some MEDIUM-adjacent issues
surfaced independently while reading the flagged code (not in the
report itself) and are fixed here too, under the same rigor, labeled
"previously-remaining" — genuine bugs this session's own earlier
passes (ADR-0111/ADR-0112/ADR-0113/ADR-0114) had not yet reached.

## Decision

### Code fixes

**N-1 — `broker.live.session` `reconcile_order` cleared `RECONCILIATION_REQUIRED` on the first match, not on every order resolving.**
A single reconciled `client_order_id` returned the whole session to
`ACTIVE` even while sibling orders remained `BrokerOrderStatus.UNKNOWN`
— silently re-opening trading with unreconciled orders still
outstanding. Fixed to check every other tracked order before clearing
the state. This also closes a documentation gap in ADR-0111 itself
(D-1 below): that ADR's own §2 entry described `release_kill_switch`'s
guarantee without covering `reconcile_order`'s separate bug, so the
"orders must be reconciled before new trading resumes" invariant it
described was, at the time, only partially enforced.

**N-2 / previously-remaining — `ai_gateway.QuotaManager` had no restart-safe id seeding and always initialized `BillingStatus.CONFIRMED_FREE`.**
`_IdAllocator` restarted at 1 on every process restart, colliding with
already-persisted ids (same restart-safety class as ADR-0073's
established convention). `initialize()` also hardcoded
`CONFIRMED_FREE` regardless of the real billing status. Fixed:
`QuotaManager`/`_IdAllocator` now accept a `starting_id`, and
`initialize()` takes an explicit `billing_status` parameter.

**N-2 (continued) — natural quota exhaustion never set a `reset_time`.**
A provider hitting `remaining_requests == 0` through ordinary
decrementing (not an explicit 429) never got a `reset_time`, so it
stayed excluded from rotation forever instead of self-healing after
the real quota window. Fixed: `record_success()` now sets
`reset_time = at + timedelta(days=1)` on natural exhaustion, without
ever clobbering an already-open window.

**N-4 — `storage.serialization` silently dropped `PortfolioView.market_value` on every DB round-trip.**
`portfolio_view_to_dict`/`dict_to_portfolio_view` never touched the
field at all. Fixed to round-trip it, with backward-compatible
`.get()` handling for rows persisted before this fix.

**N-17 — `broker.live.kill_switch` fail-open on an unmeasurable, but configured, risk limit.**
`evaluate_kill_switch_triggers` only checked `config.X is not None and
measurement is not None and ...` — a configured limit with a `None`
measurement silently never triggered, instead of the fail-closed
`*_unmeasurable` treatment `account_state_known`/`position_state_known`
already used. Fixed to add `daily_loss_unmeasurable`/
`order_frequency_unmeasurable` reasons, matching the module's own
stated fail-closed discipline.

**N-6 — `broker.paper` had no restart-safe watermark for `observation_id`.**
Same restart-safety class as N-2: `PaperTradingSession.restore()` never
called into the adapter's id allocator, so a status observation
recorded after a restart could collide with (and be silently dropped
by) a pre-restart id. Fixed: new `PaperBrokerAdapter.
restore_observation_id_watermark()`, called for every persisted status
row during `restore()` before `rebuild_status_history()`.

**N-3 / N-12 / previously-remaining — `data_infra.provider`/`providers.*`/`quality` ingestion-time and error-handling gaps.**
`ingestion_time` could be computed strictly before `available_time` at
month-end/current-day boundaries (fixed via new `clamp_ingestion_time`,
wired into `tiingo.py`/`stooq.py`/`file_import.py`); a single symbol's
`normalize()` exception crashed the entire multi-symbol
`IngestionRunner` run instead of producing a per-symbol `FAILED` result
(fixed with a try/except boundary); `FallbackDataProvider` raised
`PermanentProviderError` even when only one of two underlying failures
was actually permanent (fixed to raise `TransientProviderError` unless
BOTH failures are permanent); `quality._check_split_consistency` could
divide by zero when the AFTER window's first close (not just the
BEFORE window's last close) was `<= 0` (fixed with the missing guard).

**N-7 / previously-remaining — `backtest.engine`/`trade_journal.backtest_adapter` checkpoint-boundary sequencing.**
Corporate actions for the NEXT checkpoint could be applied to the
portfolio before the current checkpoint's own fills, double-adjusting
splits and misattributing dividends at the exact boundary (fixed by
applying next-checkpoint corporate actions strictly after this
checkpoint's fills, with a refreshed `portfolio_view`).
`ingest_backtest_result`'s per-checkpoint loop could let a later
order's `portfolio_state` see an earlier SIBLING order's not-yet-
executed fill (same-checkpoint lookahead) — fixed with a `pending`
fill queue gated on `decision_time >= fill.execution_time`.

**N-8 / previously-remaining — `predict.experience`/`predict.predictor`/`regime.features`.**
`attach_prediction_context`'s `security_id` parameter was a blind
substitution rather than a per-record filter, letting one prediction's
context leak onto every decision passed in the same call regardless of
its actual security — fixed by making it `Optional[str] = None` and
filtering on `decision.security_id`. `RegimeAwarePredictor` reused the
wrapped `DriftPredictor`'s own `prediction_id`, risking a collision the
moment two predictors share a repository — fixed with its own
`_IdAllocator`. `regime.features`'s `compute_trend`/`compute_liquidity`/
`compute_correlation`/`compute_distribution_days` each carried a dead
`or reliability < config.min_data_completeness` disjunct (`data_
completeness` is capped at exactly `1.0` once `available >= required`,
the same `required` value used for both the raw length gate and the
reliability denominator on these four axes specifically — Volatility/
Stress use different denominators and were left unchanged) — removed
with an explanatory comment in place.

**N-9 / previously-remaining — `evolution.repository`/`storage.evolution_repository` natural-key collision.**
`ModelStatusTransition`'s dedup key omitted `passed`, so a later
passing retry of the same candidate/dataset/evaluation could collide
with an earlier failed attempt's row. Fixed by including `passed` in
both the in-memory and DuckDB natural-key lookups.

**N-10 / previously-remaining — `learning.dataset` `quality_status` ignored empty splits.**
`quality_status = "OK" if n > 0 else "INSUFFICIENT_SAMPLES"` passed
even when the TRAIN or VALIDATION split was empty after the configured
0.6/0.2/0.2 split fractions — a dataset with too few samples to
actually train/validate on was still reported `"OK"`. Fixed to require
both splits non-empty. A second, unrelated bug found while reading the
same function: `max_samples` sampling kept the OLDEST N results
(`valid_results[:config.sampling.max_samples]`) instead of the most
RECENT N — fixed to `[-max_samples:]`.

**N-11 — `strategy_research.factor_scores.net_stock_issuance_score` had no split adjustment.**
A stock split between two fundamentals periods produces a fake,
enormous "issuance" signal purely from the share-count mechanics of
the split, not real issuance. Fixed with an optional
`price_repository` parameter (backward-compatible default `None`, no
production caller exists yet) that, when supplied, adjusts the prior
period's share count by the compounded split ratio before computing
the log ratio.

**N-13 / N-14 / N-15 — script/workflow exit-code and artifact-layout gaps.**
`ingest_fundamentals_data.py`/`ingest_insider_transactions.py` reported
success (`rc=0`) whenever ANY symbol succeeded, masking individual
symbol failures — fixed with a `failed_symbols_from()` helper and an
exit code gated on it. `paper_trading_cycle.yml`'s artifact-restore
steps assumed `actions/upload-artifact@v4` never wraps a single-
directory upload in an extra subfolder — a behavior this session
cannot verify offline either way — fixed defensively (detect-and-
flatten, a no-op if unwrapped). `run_learning_cycle.py` returned `0`
even when `experiment.status == "FAILED"` — fixed to gate the exit
code on it.

**N-16 — `orchestration.paper_runner` fabricated `realized_pnl` on an unknown broker `average_cost`.**
The realized-PnL computation read cost basis from `PortfolioView.
average_cost` (non-Optional, defaults to `0.0` when the broker
genuinely doesn't know it) instead of the raw `BrokerPosition.
average_cost` (correctly `Optional[float]`) — an unknown cost basis
was silently treated as a `0.0` cost basis, fabricating the entire
sale proceeds as profit. Fixed by reading `account.positions` (the raw
broker-reported position) directly for this one computation, bypassing
the lossy intermediate view.

**previously-remaining — `storage.data_repository` restart-unsafe `batch_id` and f-string-interpolated SQL.**
`_next_raw_batch_id` was hardcoded to start at `1` on every
construction, colliding with already-persisted batches after a restart
(same class as N-2/N-6/N-9) — fixed with a `_compute_next_raw_batch_id()`
query seeding it past the real max. Four `read_parquet('{glob_pattern(...)}',
...)` calls interpolated the glob path directly into the SQL string —
fixed to `read_parquet(?, ...)` with the path bound as a parameter
(verified DuckDB supports binding this argument directly).
`storage.serialization`'s own module docstring overclaimed that every
timestamp round-trips UTC-normalized-and-naive; only column-based
fields do (`to_utc_naive`/`from_utc_naive`) — `payload_json`-embedded
fields (`_dt_iso`/`_dt_from_iso`) correctly preserve the original
ISO-8601 offset instead. Docstring corrected to describe both paths
accurately.

**previously-remaining — `monitoring.drift`/`monitoring.config` allowed a `min_drift_sample_count` that crashes.**
`detect_mean_shift`/`detect_variance_shift` compute sample variance
with an `(n - 1)` denominator; `MonitoringConfig.__post_init__` only
rejected `min_drift_sample_count <= 0`, so a threshold of `1` passed
validation and then crashed with `ZeroDivisionError` on the very first
single-sample window instead of producing `DriftStatus.UNKNOWN`. Fixed
by raising the validation floor to `2`.

**previously-remaining — `decision.agent.BaselineRuleDecisionAgent` fail-open on `StressState.UNKNOWN`.**
The regime gate blocked `NO_TRADE` when the Trend axis was `UNKNOWN`
but only checked the Stress axis for `HIGH`, silently falling through
to a directional decision when Stress was itself `UNKNOWN` — an
asymmetric fail-open inconsistent with the same gate's own Trend
handling and with this project's stated fail-closed default (§1.4).
Fixed with a `regime_stress_unknown` gate, same treatment as Trend;
`docs/specifications/PHASE-7-decision-agent.md`'s own gate table
updated to match (renumbered gates 5-7).

**previously-remaining — `run_multi_strategy_paper_trading_cycle.py` silently funded `buy_and_hold` with the wrong reference capital.**
`--initial-capital` defaulted to `1,000,000.0` and applied uniformly
to every requested strategy, including `buy_and_hold` — which
`broker.paper.us_longterm_config.PAPER_CAPITAL_USD` documents as
ADR-0028's own, deliberately smaller ($10,000) reference figure for
that specific strategy. An operator who ran `buy_and_hold` through
this script without remembering to pass `--initial-capital 10000`
explicitly got a session funded 100x larger than the documented
reference. Fixed: the flag now defaults to `None`; when omitted,
`buy_and_hold` strategies use `PAPER_CAPITAL_USD` and `run_cycle`
strategies use `PaperTradingConfig`'s own default — an explicit
`--initial-capital` still overrides both uniformly, unchanged.

**previously-remaining — `scripts/deploy/oracle_vm_bootstrap.sh` persisted the GitHub PAT to disk despite its own promise not to.**
The private-repo clone path built `AUTH_URL` by embedding the token
into the clone URL (`https://${GH_TOKEN}@...`) — `git clone` persists
whatever URL it is given into the clone's own `.git/config`
permanently, directly contradicting both this script's inline comment
("input hidden, not stored") and `ORACLE-CLOUD-DEPLOYMENT.md`'s
identical claim (D-11, deferred to the LOW pass for the doc-side
half of this same finding — the code fix here already closes the
actual leak). Fixed: the token is now passed as a one-off `git -c
http.extraheader=...` value — process-scoped only, never written to
any config file — instead of embedded in the clone URL.

### Documentation fixes (D-1 through D-6)

**D-1 — ADR-0111 described a stronger guarantee than the code, at the time, actually enforced.** Addressed as part of N-1 above; ADR-0111 itself now carries an addendum cross-referencing this ADR.

**D-2 — `docs/PROJECT_STATUS.md` carried the same class of stale
universe-count numeral (`40종목`/`16종목` for what are actually 39-
and 15-symbol universes) that ADR-0112 had already fixed at 4 specific
locations, in 14 further, previously-undetected locations** (the
existing regression test pinned only ADR-0112's own 4 strings, so this
whole class of same-shaped error was undetected elsewhere in the same
document). All 14 corrected; the only two remaining "16종목" mentions
in the document both correctly name Phase 22's separate, genuinely
16-ticker US long-term universe (not `PILOT_UNIVERSE_V1`). The
regression test (`tests/data_infra/
test_universe_documentation_numeric_consistency.py`) gained a new
count-based assertion (zero "40종목" occurrences, exactly 2 "16종목"
occurrences) so a *class* of future regression is caught, not just the
originally-cited strings. The same stale count was independently found
and fixed in a `src/data_infra/universe.py` comment (not in any of
the review's cited locations either).

**D-3 — `docs/research/STRATEGY-VALIDATION-REPORT.md` had the identical
class of error, 14 locations**, mixing correct (15/39/63) and stale
(16/40/64) universe-size mentions in the same document. All corrected;
verified zero remaining `16-symbol`/`40-symbol`/`64-symbol` substrings.

**D-4 — `README.md`'s "현재 상태" section was frozen at Phase 31 and
its test-count arithmetic chain had a genuine addition error** (`1605
+ 30` written as `= 1638`, which is only true if the real Phase 25
baseline was `1608`, not `1605` — both numbers are independently
verified real `pytest` run results from `PROJECT_STATUS.md`, three
tests apart for reasons the document does not record). Fixed: the
arithmetic chain now shows the real re-measured `1608` baseline with
an honest note about the unexplained +3 gap, rather than a smoothed-
over wrong sum. Both `README.md` and `PROJECT_STATUS.md`'s "Current
Phase"/현재 상태 sections gained a short forward-pointer noting that
Session 32-37's post-Phase-31 work (ADR-0111 through this ADR) happened
and where to find it, rather than rewriting the entire Phase 19-31
narrative to match (which already lives, correctly, in `PROJECT_STATUS.
md`'s own chronological session log).

**D-5 — `docs/operations/LIVE-TRADING-RUNBOOK.md`'s Prerequisites
checklist was frozen in the "limits not yet ratified" era.** The
account owner has since ratified concrete values for `max_daily_loss`/
`max_turnover`/`max_order_frequency_per_hour` (#1/#6/#7,
`LIVE-RISK-POLICY.md` "Session 36") and Option B (an unset limit
structurally blocks Live activation, not merely "has no effect") has
been implemented in `broker.live.safety_gate` since Phase 22/Session
36. The runbook still described these as unratified proposals with
"no effect until explicitly set." Rewritten to state the ratified
values, Option B's actual enforced behavior, and the ratified-but-not-
code-applied distinction accurately.

**D-6 — `PROJECT_MASTER_PLAN.md` carried 12 dangling `§N` cross-references** (§16, §31, §37 x2, §38, §48, §56, §69 x2, §75, §76, §80, §86, §87 — several more than the review's own originally-cited 8, found while verifying the cited ones against the document's real section numbers, which top out at §26). Each was re-identified by content match against its own citing sentence (e.g. "§80(변경관리 프로세스)" citing itself as Change Management unambiguously resolves to the real §19, the only section titled 변경관리; "§48 Validation Protocol" resolves to the real §13.4, the only section titled Validation Protocol) and corrected to the real target section using this document's actual `N.M` numbering. One of the same class of dangling reference was also found and fixed in `docs/decisions/ADR-0008-validation-protocol.md` (§48-49/§71 → §13.4-13.5) while cross-referencing the master plan's own §48 correction; the review's own broader "많은 초기 ADR들" (many early ADRs) scope was not fully swept beyond this — a large number of additional, individually-ambiguous `§N` references remain scattered across other early ADRs and are knowingly deferred rather than guessed at under time pressure (each would need the same content-matching verification done here, not a mechanical renumbering). The document's own stale `**Last Updated:** 2026-08-24 (Phase 0)` stamp was also corrected, with a note that the constitution/architecture content itself is intentionally unchanged since Phase 0 and `PROJECT_STATUS.md` is the authoritative source for actual project progress.

## What this does NOT do

Does not address the ~90 LOW-severity findings from the same review —
tracked as a separate, explicit follow-up pass per the account owner's
own instruction, with its own ADR once complete. Does not sweep the
remaining, individually-ambiguous dangling `§N` references scattered
across early ADR files beyond the one representative fix in ADR-0008
(D-6, deliberately deferred — see above). Does not add a real market-
calendar dependency anywhere it didn't already have one. Does not
retroactively correct any already-persisted database row affected by
N-2/N-6/N-9's historical id-collision risk (id-corrupted CONFIRMED_FREE
providers, dropped observations pre-restore, etc.) — only future runs
benefit from the restart-safety fixes.

## Tests

Every fix above carries at least one new regression test, verified via
`git stash` (fails without the fix, passes with it) before being
committed: `tests/ai_gateway/test_ai_gateway_quota_manager.py`,
`tests/storage/test_ai_gateway_repository.py`,
`tests/storage/test_serialization.py` (new file),
`tests/broker/live/test_live_session.py`,
`tests/broker/live/test_live_kill_switch.py`,
`tests/storage/test_paper_repository.py`,
`tests/data_infra/test_quality_real_data.py`,
`tests/data/test_provider_ingestion.py`,
`tests/data_infra/test_fallback_provider.py`,
`tests/data_infra/test_tiingo_provider.py`,
`tests/data_infra/test_stooq_provider.py`,
`tests/data_infra/test_file_import_provider.py`,
`tests/backtest/test_corporate_actions.py`,
`tests/trade_journal/test_backtest_integration.py`,
`tests/predict/test_predict_experience.py` (new file),
`tests/predict/test_regime_aware_predictor.py`,
`tests/evolution/test_status_transition_repository.py` (new file),
`tests/storage/test_evolution_repository.py`,
`tests/learning/test_dataset.py`,
`tests/evolution/test_pipeline.py` (new file),
`tests/learning/test_cleaning.py`,
`tests/strategy_research/test_factor_scores.py`,
`tests/data_infra/test_ingest_scripts_failed_symbols.py` (new file),
`tests/deploy/test_paper_trading_cycle_workflow.py`,
`tests/orchestration/test_run_learning_cycle_cli.py`,
`tests/orchestration/test_paper_runner.py`,
`tests/storage/test_data_repository_persistence.py`,
`tests/monitoring/test_monitoring_drift.py`,
`tests/decision/test_agent_baseline.py`,
`tests/orchestration/test_run_multi_strategy_paper_trading_cycle_cli.py`,
`tests/deploy/test_oracle_vm_bootstrap_script.py`,
`tests/data_infra/test_universe_documentation_numeric_consistency.py`.
Full suite re-run: **2862 passed, 0 failed** (up from ADR-0114's own
2799 on merged `main` HEAD, +63).
