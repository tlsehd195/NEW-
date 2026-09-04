# Production Readiness Matrix

Phase 17 Production Safety Review, updated in Phase 18 (Paper
Trading Performance Report), Phase 20 (Real Market Data Foundation
& Documentation Sync), Phase 21 (Toss Broker Adapter Completion),
Phase 22 (Real-Data Paper Trading / US Long-Term System Hardening),
Phase 23 (Strategy Research & Real Market Data Validation),
Phase 24 (Real Market Data + Expandable US Equity Universe),
Phase 25 (Long-Horizon Real-Data Strategy Validation), Phase 26
(Long-Horizon Real-Data Validation, re-verification), Phase 27
(Real-Data Walk-Forward Validation & Strategy Evidence), Phase 28
(Real-Data Walk-Forward Execution & Strategy Evidence), Phase 29
(Long-Horizon / Broad-US-Universe / Survivorship-Aware Real Walk-Forward
Validation), Phase 30 (Real Historical US Equity Dataset
Acquisition, Survivorship-Aware Dataset Validation, and Full
Walk-Forward Execution -- attempted, environment-blocked), and Phase 31
(Real Data Acquisition / Historical Universe Data Source Audit).
One row per area the review instruction names. "Status" is one of
PASS / FAIL / BLOCKED / UNKNOWN / PARTIAL. "Blocking?" answers "does
this alone prevent Live activation today" independent of every other
row. "Human Decision Required?" names the specific decision, or "No"
if none remains.

**Phase 21 note on the four Toss-related BLOCKING rows below**: Phase
20 upgraded these four capabilities' evidence from Tier 2 to Tier 1
(the user provided the official OpenAPI spec directly). Phase 21 then
**implemented all four in code** against that Tier 1 schema
(`docs/decisions/ADR-0027-toss-broker-adapter-completion.md`). **This
still does not change any row's Status or Blocking column**:
`get_capabilities()` deliberately still reports `CapabilityStatus.UNKNOWN`
for all four, because `UNKNOWN`'s own definition ("exists per research,
never independently verified end-to-end") is exactly this phase's
outcome -- implemented, never operationally verified against a real
account, since no automated test may ever call the real Toss API. The
rows are still BLOCKED, but the reason has progressed twice now:
"endpoint unconfirmed" (pre-Phase-20) -> "endpoint confirmed,
implementation not yet built" (Phase 20) -> "implemented and tested,
never operationally verified" (Phase 21, current).

| Area | Requirement | Current State | Evidence | Status | Blocking? | Human Decision Required? | Next Action |
|---|---|---|---|---|---|---|---|
| Toss API (general) | Endpoints confirmed against official documentation before use | All 4 previously-UNKNOWN capabilities now Tier 1 documented (Phase 20) **and implemented in code (Phase 21)**, against `GET /api/v1/buying-power`/`GET /api/v1/holdings`/`GET /api/v1/orders/{orderId}`/`POST /api/v1/orders/{orderId}/cancel`; `get_capabilities()` still reports `UNKNOWN` for all four (implemented != operationally verified) | `docs/operations/TOSS-API-GAP-ANALYSIS.md` Phase 21 addendum; `docs/decisions/ADR-0027-toss-broker-adapter-completion.md` | **IMPLEMENTED & TESTED, NOT OPERATIONALLY VERIFIED** | **Yes** (code still reports UNKNOWN) | No (operational verification against a real account, not a policy choice) | Real credential availability + a human operator exercising each call against an actual Toss account, then promoting `CapabilityStatus` to `ENABLED` only for what is actually confirmed working |
| Authentication | OAuth2 Client Credentials, credentials never logged/persisted | Implemented, confined to `broker/toss/auth.py` | `tests/broker/toss/test_toss_auth.py`; repo-wide scan `tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree` | **PASS** | No | No | None |
| Account (balance query) | `get_account` against a confirmed endpoint | **Implemented (Phase 21)**: calls `GET /api/v1/buying-power?currency=USD` with the existing `X-Tossinvest-Account` header pattern; 4 new tests cover success/zero-balance/malformed/5xx | `src/broker/toss/adapter.py`; `tests/broker/toss/test_toss_adapter.py::TestGetAccount` | **BLOCKED** (pending operational verification, not the code) | **Yes** | No | Same as Toss API row |
| Positions | `get_positions` against a confirmed endpoint | **Implemented (Phase 21)**: calls `GET /api/v1/holdings`; a malformed item raises rather than silently dropping a position from the list (Known Issue: `()` is still ambiguous between "zero positions" and a caught failure, per the Protocol's return type -- unchanged limitation, not fixed this phase) | `src/broker/toss/adapter.py`; `tests/broker/toss/test_toss_adapter.py::TestGetPositions` | **BLOCKED** (pending operational verification) | **Yes** | No | Same as Toss API row |
| Orders (creation) | Submit order against a confirmed endpoint, correctly mapped responses | Implemented and confirmed; 5xx handling fixed this phase | `tests/broker/toss/test_toss_production_safety_contract.py` | **PASS** | No | No | None |
| Cancellation | `cancel_order` against a confirmed endpoint | **Implemented (Phase 21)**: calls `POST /api/v1/orders/{orderId}/cancel`; the response's newly-issued `orderId` is captured in a new, additive `BrokerOrderResponse.cancel_reference_id` field, never confused with the original order's id (`broker_order_id`, unchanged) | `src/broker/toss/adapter.py`; `tests/broker/toss/test_toss_adapter.py::TestCancelOrder`; `docs/decisions/ADR-0027` decision 3 | **BLOCKED** (pending operational verification) | **Yes** | No | Same as Toss API row; cancel-on-shutdown automation remains a separate, undecided policy question regardless (instruction section 22, unchanged from Phase 16) |
| Reconciliation | UNKNOWN/MISMATCH never MATCHED; blocks further submissions | Implemented, re-verified this phase | `tests/broker/live/test_production_safety_cross_cutting.py::TestReconciliationNeverBecomesMatchedOnceUnknownOrMismatched` | **PASS** | No | No | None |
| Risk (policy completeness) | Every named risk limit DEFINED or explicitly deferred with a human decision on file | 1 DEFINED, 6 INHERITED (never re-approved for real capital specifically), 3 UNDEFINED, 3 BLOCKING (no field exists). Reasoned *proposed* values exist for the 3 UNDEFINED fields (`max_daily_loss` = 2% of eventual initial capital, `max_turnover` = 2.0, `max_order_frequency_per_hour` = 6, revised down from Phase 20's original 3.0/30 -- see `LIVE-RISK-POLICY.md`'s "Revised" table) -- proposals only, still not ratified (`max_daily_loss` genuinely cannot be a concrete number until initial Live capital itself is decided). **UPDATED (Session 36, ADR-0045)**: the design-level "should `None` block Live" question is now resolved as Option B for all three fields (`max_daily_loss`/`max_order_frequency_per_hour` since Phase 22, `max_turnover` newly this session) -- `evaluate_safety_gate` now structurally blocks Live whenever any of the three is unset, closing the asymmetry this row used to describe | `docs/operations/LIVE-RISK-POLICY.md`; `src/broker/live/safety_gate.py`; `docs/decisions/ADR-0045` | **PARTIAL** | **Yes** (all three limits still unset in config) | **Yes** -- ratify or revise the 3 proposed numeric values in `LIVE-RISK-POLICY.md` (the "should `None` block" question is no longer open, only the actual numbers are) | Human ratifies/revises the 3 proposed values once initial Live capital is decided |
| Kill Switch | Auto-engage on critical conditions; AI cannot release | Implemented; `data_health` trigger added this phase | `tests/broker/live/test_live_kill_switch.py` | **PASS** | No | No | None |
| Monitoring | Portfolio/broker/data/model health collected, persisted, alertable | Phase 15 equity/PnL/drawdown gap closed in Phase 17; Paper performance-report metrics (Sharpe/Sortino/etc.) built in Phase 18 but deliberately not fed into Monitoring (a periodic report, not a component-health signal -- ADR-0024 decision, `docs/specifications/PHASE-18-paper-performance-and-validation.md` section 6) | `tests/integration/test_paper_monitoring_integration.py` | **PASS** | No | No | None |
| Drift | Feature/prediction drift detected and recorded | Implemented, unmodified this phase | `src/monitoring/drift.py`; Phase 14 tests | **PASS** | No | No | None |
| Paper Trading | Order->Fill->Journal->Experience traced with real code; performance evaluated beyond raw return | Lineage traced in Phase 17 (5 scenarios A-E); Phase 18 built `broker.paper.performance` (Sharpe/Sortino/Calmar/drawdown/turnover/cost/slippage/win-rate/benchmark) and re-verified the lineage under 8 further scenarios (A-H) including partial fill, insufficient cash/position, duplicate order id, broker failure, and drawdown. **UPDATED (Session 36, ADR-0067)**: `orchestration.paper_runner.run_cycle` is the first real Regime->Prediction->Decision->Sizing->Risk->Order-Validation->`PaperTradingSession.submit` pipeline in this codebase -- previously `PortfolioRiskEngine.assess` had zero callers anywhere in `src/` (only exercised by tests). Still not "a real, running Trading Engine loop" (no scheduler/timer); `run_cycle` is called once per checkpoint by whatever drives it, matching `BacktestEngine.run()`'s own per-checkpoint loop shape. **UPDATED further (Session 36 continued, ADR-0068)**: the `value_history` limitation above is closed -- `orchestration.paper_runner.PaperRunnerState` carries a real running portfolio-value series across successive `run_cycle` calls (opt-in; `state=None` preserves the original disabled behavior). The five upstream stages (Prediction/Regime/Decision/Sizing/Risk) can now be persisted through optional repository parameters reusing the exact classes `tests/integration/test_risk_lineage.py` already established. `scripts/run_paper_trading_cycle.py` is a real, tested (network-free, run end to end against a seeded DuckDB catalog) CLI that loops `run_cycle` over a real trading-day range against a real market-data catalog, sourcing `sector_by_security` from the chosen universe's own real `SymbolMetadata.sector` data -- still not an always-on scheduled process (runs once over a fixed window, then exits; a real external scheduler invoking it repeatedly remains out of scope) | `tests/broker/paper/test_paper_performance.py`; `tests/integration/test_paper_performance_scenarios.py`; `tests/orchestration/test_paper_runner.py`; `tests/orchestration/test_orchestration_boundary.py`; `tests/orchestration/test_run_paper_trading_cycle_cli.py`; `docs/decisions/ADR-0067`; `docs/decisions/ADR-0068` | **PASS** | No | No | Wiring an always-on scheduled process (an external scheduler invoking the CLI repeatedly); a Live-side equivalent (deliberately out of scope this session) |
| Learning | Experience -> Training Dataset provenance-safe; PAPER cannot become LIVE | Re-verified this phase, including a bypass-the-filter defense-in-depth test | `tests/integration/test_paper_learning_readiness_lineage.py::TestPaperToLearningProvenanceSafety` | **PASS** | No | No | None |
| Model Validation | No automatic Candidate->APPROVED/DEPLOYED path anywhere | Re-verified repo-wide (not just `evolution.*`) this phase | `tests/evolution/test_production_safety_candidate_boundary.py` | **PASS** | No | No | None |
| Rollback | Emergency halt and recovery procedure exists and matches code | Kill switch + Runbook exist. **UPDATED (Session 36, ADR-0045)**: `LiveTradingSession.engage_kill_switch` now automatically cancels every order not already known to be closed (`LiveTradingConfig.auto_cancel_on_kill_switch`, default `True`) -- the user's explicit decision, resolving a "DECISION REQUIRED" this project had repeatedly cited without ever recording an actual decision (the prior "ADR-0022 decision 8" citation was itself found to be wrong -- that ADR never discussed cancel-on-shutdown at all). The general, manually-initiated `Shutdown` procedure (`run_shutdown_checks`) is unchanged and still does not auto-cancel -- only an emergency kill-switch engagement does | `docs/operations/LIVE-TRADING-RUNBOOK.md`; `src/broker/live/session.py`; `docs/decisions/ADR-0045` | **PASS** | No | No | None -- resolved |
| Audit | Every critical event leaves a persisted record | Confirmed for broker/data/reconciliation/kill-switch/model/provider failures | `docs/specifications/PHASE-17-production-safety-review.md` section 6 | **PASS** | No | No | None |
| Secrets | Credential access confined to one file, never persisted | Re-verified repo-wide this phase (broader than Phase 13's package-scoped check) | `tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree` | **PASS** | No | No | None |
| Runbook | Procedures match actual code; no secret values stored in it | Re-read and mechanically verified this phase | `tests/broker/live/test_production_safety_cross_cutting.py::TestRunbookReferencesStillResolveInCode` | **PASS** | No | No | None |
| Benchmark | S&P 500 Buy & Hold uses the same period/capital/cost assumptions as the run it's compared against | True for the historical Backtest engine (`backtest.benchmark.BenchmarkResult` shares `initial_capital`/cost model by construction); Phase 18 built `broker.paper.performance.BenchmarkComparison` reusing the same `BenchmarkEngine` for Paper. Phase 20 resolved the long-open PRICE_RETURN vs TOTAL_RETURN `DECISION REQUIRED` (ADR-0026: SPY as proxy, TOTAL_RETURN target) and implemented `backtest.total_return.build_total_return_benchmark_points` to construct it. **UPDATED (Session 36)**: real SPY price/dividend data has since been ingested by the user in their own network-enabled environment and used as `SPY_TOTAL_RETURN_REAL` in real `run_long_horizon_validation.py` runs (see `docs/research/STRATEGY-VALIDATION-REPORT.md`) -- `BenchmarkComparison.status` is `AVAILABLE` for those real runs; this row no longer reads `BENCHMARK_UNAVAILABLE` as a blanket statement | `src/backtest/benchmark.py`; `src/backtest/total_return.py`; `src/broker/paper/performance.py`; `docs/decisions/ADR-0026-benchmark-return-type.md`; `docs/research/STRATEGY-VALIDATION-REPORT.md` | **PASS** (structure and real data both confirmed) | No | No | None -- benchmark data pipeline is real and working; only further real-data breadth (Stage 3+ universes) remains an ordinary ingestion step, not a benchmark-specific gap |
| Transaction Cost | Modeled and attributed | Implemented in Backtest (`backtest.metrics`) and Paper (`Fill.commission`/`spread_cost`), per-fill and now aggregated into a Paper-level report (`total_transaction_cost`, summed from `TradeRecord.transaction_cost`) | `src/broker/paper/journal.py`; `src/broker/paper/performance.py`; `tests/integration/test_paper_performance_scenarios.py::TestScenarioG_TransactionCostAndSlippageFlowIntoTheReport` | **PASS** | No | No | None |
| Slippage | Modeled and attributed | Implemented per-fill in both Backtest and Paper (`Fill.slippage_cost`); **not computed at all for Live** (`broker.live.journal.build_fill_from_broker_response` sets `slippage_cost=0.0`, documented as an honest limitation, no independent quote to compare against) | `src/broker/live/journal.py`; `docs/decisions/ADR-0022` decision 9 | **PASS** (Backtest/Paper); **KNOWN LIMITATION** (Live) | No | No | Unchanged from Phase 16 -- would require an independently-sourced quote feed |
| OOS (Out-of-Sample) | Validation split distinct from training | `learning.config.SplitConfig` (train/validation/test), chronological | `src/learning/config.py`; `src/learning/dataset.py` | **PASS** (split exists) | No | No | None -- statistical robustness (PBO/overfitting) remains explicitly deferred, see next row |
| Walk Forward | Rolling-window re-validation / PBO / Deflated Sharpe | **UPDATED (Session 36)**: `strategy_research.pbo_dsr.compute_pbo`/`compute_dsr_for_all_candidates` are implemented and have now run against real data multiple times. `run_long_horizon_validation.py` reports `EvidenceLevel` per candidate (CANDIDATE/ROBUSTNESS_PENDING) automatically once `assess_pbo_dsr_applicability`'s trigger conditions are met -- this has now fired for real, repeatedly. **UPDATED (Session 36 continued, ADR-0051/ADR-0052)**: 20 more literature candidates were raw-IC-screened and wired into the same pool (now 28 candidates total, up from 8, real 63-symbol `RESEARCH_UNIVERSE_STAGE3` run, PBO=14.29% across 70 CSCV splits). `size` briefly reached `CANDIDATE` before a concentration-report check found its held-out TEST return was 76.3% one security (an oil-price-supercycle-era energy name) -- traced to a genuine research-methodology gap (`top_n=5`, too narrow a portfolio breadth to average out one name's luck, found and fixed uniformly across all 28 candidates as `top_n=10`, not tuned per-candidate); re-verification correctly dropped `size` below the fold-consistency bar. Two candidates (`altman_z`, `rank_average_ensemble`) reach `evidence=CANDIDATE` at the corrected breadth, but both show strongly negative held-out TEST results (-25.80%/-15.19% net), so neither should be read as "found a validated strategy." **UPDATED (Session 36 continued further, ADR-0057)**: 2 more candidates (`combined_factor`, `idiosyncratic_volatility`) were wired in and the pool re-run against the wider 87-symbol `RESEARCH_UNIVERSE_STAGE4` (30 candidates total, PBO=7.14%). `altman_z`/`rank_average_ensemble` remain the only 2 reaching `CANDIDATE`, with materially unchanged TEST-negative results -- reproducing under an independently-expanded universe strengthens the "hold, do not promote" conclusion. Neither new candidate reached `CANDIDATE`; `combined_factor` in particular showed the worst fold-consistency of all 30 (20% positive folds) alongside a positive TEST result and almost no trading activity (8 trades) -- read as a sample-sparsity artifact from its own 9-leg all-or-nothing coverage requirement, not a genuine signal, per `docs/research/STRATEGY-VALIDATION-REPORT.md`'s Phase 33 Addendum Section H. **UPDATED (Session 36, ADR-0045)**: the "should CANDIDATE be required before Live" question is now resolved -- `broker.live.approval.LiveActivationApproval.strategy_evidence_reviewed` (new required field) structurally requires the human activator to attest the strategy reached CANDIDATE-or-better AND that its TEST result specifically (not just the label) was reviewed, directly motivated by this exact class of divergence | `src/strategy_research/pbo_dsr.py`; `src/strategy_research/factor_strategy.py`; `src/broker/live/approval.py`; `docs/research/walk-forward-pbo-deflated-sharpe.md` section 9; `docs/decisions/ADR-0043-ml-first-model.md` Decision 7; `docs/decisions/ADR-0045`; `docs/decisions/ADR-0051`; `docs/decisions/ADR-0052`; `docs/decisions/ADR-0057`; `docs/research/STRATEGY-VALIDATION-REPORT.md` Section G and "Phase 33 Addendum" | **RESEARCHED, IMPLEMENTED, RUN AGAINST REAL DATA (30 candidates). Zero candidates VALIDATED (a distinct, higher bar than CANDIDATE that requires explicit human review, not automated)** | No (not independently blocking Live, since it gates model *quality* confidence, not a hard safety boundary) | No -- resolved as a structural attestation requirement (like `checklist_completed`, this is not a computationally-verified gate, but skipping it now requires deliberately lying on the field rather than merely forgetting a step) | Continue running `scripts/run_long_horizon_validation.py` against real data as the universe/feature set evolves; a human must still explicitly review any candidate before treating it as VALIDATED -- no code path does this automatically |

## Overall

No row above claims `CapabilityStatus.ENABLED` for a capability this
review could not verify against official documentation, and no row
was marked PASS on the strength of an automated test alone without a
cited file. Four rows are independently **Blocking** (Toss API,
Account, Positions, Cancellation) -- Live activation is blocked by
Toss's own capability gaps regardless of how every other row scores,
per `docs/decisions/ADR-0022-live-trading.md` decision 2 and reconfirmed
structurally this phase.

**Phase 20 update**: those four rows' evidence improved from Tier 2 to
Tier 1 (the user provided the official Toss OpenAPI spec directly).
Separately, Phase 20 built a real (if network-access-unverified) market
data foundation (`ADR-0025`/`ADR-0026`, `src/data_infra/providers/tiingo.py`,
`src/backtest/total_return.py`) and proved the Paper Trading pipeline
can structurally consume it end to end
(`tests/integration/test_paper_trading_real_market_data.py`).

**Phase 21 update**: all four capabilities are now implemented in code
against that Tier 1 schema and covered by 63 new tests, including a
real `TossBrokerAdapter` (stub transport, never the network) driven
through `LiveTradingSession.reconcile_order`/`compare_account`/
`compare_positions` producing correct MATCHED/MISMATCH/UNKNOWN outcomes
(`tests/integration/test_toss_live_reconciliation_integration.py`).
**None of this changes any row's Blocking status.**
`get_capabilities()` still reports all four `UNKNOWN` by design
(`docs/decisions/ADR-0027` decision 5) -- code completeness is not
operational verification, and this project's own discipline forbids
any automated test from calling the real Toss API. Live activation
remains exactly as blocked as it was before this phase, for the same
underlying reason (Toss capability status), now for a more precise
reason than either Phase 13 or Phase 20 could state.

**Phase 22 update**: real-market-data-shaped Paper Trading hardened
further -- Stooq added as a credential-free fallback provider
(`ADR-0028`), the 16-symbol US long-term universe fixed, a USD-denominated
Paper account adopted in place of a fabricated FX rate, a Buy & Hold
reference strategy wired through the full Provider→Ingestion→DuckDB→
Paper Trading→Journal→Monitoring→Performance lineage (including a real
engine restart), and more conservative risk defaults
(`max_daily_loss=0.02`/`max_turnover=2.0`/`max_order_frequency_per_hour=6`)
recorded with `evaluate_safety_gate` now fail-closed on two of the three
being unset. **Toss rows unchanged; Live activation still Blocked for
the same reason.**

**Phase 23 update**: re-verified (not assumed) that real market-data
provider access remains network-BLOCKED from this environment --
`api.tiingo.com`/`stooq.com`/`openapi.tossinvest.com` all still return a
403 CONNECT rejection at the egress proxy. Added
`scripts/ingest_real_market_data.py` (never run by this repo's own
tests) as the concrete path to real ingestion once network access
exists elsewhere. Added a strategy research framework
(`src/strategy_research/`, `ADR-0029`) with three new long-term
candidates (Long-Term Momentum, Trend+Volatility, Risk-Controlled
Momentum), all reusing the existing `BacktestEngine`/cost models/
benchmark engine unchanged. Every candidate's real-data classification
is **INCONCLUSIVE** (`docs/research/STRATEGY-RESEARCH-REPORT.md`) --
this phase produced no real backtest performance evidence, only a
pipeline proven correct against a clearly-labeled synthetic fixture.
**No change to any Toss/Live row; Live activation still Blocked for the
same, unchanged reason.**

**Phase 24 update**: re-verified real market-data provider access a
third time, via two independent paths (`curl` through the egress proxy
and `WebFetch`, a separate fetch mechanism) -- both still
`EGRESS_BLOCKED` for every Tiingo/Stooq domain tried. **REAL DATA
INGESTION: BLOCKED BY EXECUTION ENVIRONMENT**, unchanged. Built an
expandable Universe architecture (`src/data_infra/universe.py`,
`ADR-0030`): named, versioned `UniverseDefinition`s (`PILOT_UNIVERSE`
v1 = the existing 15 tradeable symbols, `RESEARCH_UNIVERSE` stage1 =
currently identical, a documented expansion point) with
`SymbolMetadata` that defaults every field beyond the bare symbol to
unconfirmed rather than guessed, and converters into Phase 1's existing
`UniverseMembership`/`SecurityMaster` persistence (previously never
populated by any code in `src/`). `scripts/ingest_real_market_data.py`
now selects a universe via `--universe` instead of a script-local
hardcoded list, and also persists `SecurityMaster`/`UniverseMembership`
records and a content checksum (previously bars only, no checksum).
`strategy_research` required zero code changes -- its `security_ids`
parameter already accepted any symbol sequence; a new test statically
confirms no `PILOT_UNIVERSE` symbol is hardcoded anywhere in
`src/strategy_research/`. `RESEARCH_UNIVERSE` was NOT expanded beyond
16 symbols this phase -- Tiingo/Stooq free-tier request/symbol/rate
limits remain UNKNOWN (unverifiable from this environment), and this
project's own discipline forbids assuming a limit. **No change to any
Toss/Live row; Live activation still Blocked for the same, unchanged
reason.**

**Phase 25 update**: re-verified real market-data provider access a
fourth time via `curl` through the egress proxy -- still CONNECT 403
for `api.tiingo.com`/`stooq.com`/`openapi.tossinvest.com`. This session
has no real data locally (`data/` empty, gitignored); note the real
2023-2024 Tiingo data a user obtained externally after Phase 24
(`STRATEGY-RESEARCH-REPORT.md` Addendum) still exists only in that
user's own environment, not here. Built chronological Train/Validation/
Test + Walk-Forward evaluation infrastructure
(`src/strategy_research/walk_forward_evaluation.py`,
`src/strategy_research/evidence.py`,
`scripts/run_long_horizon_validation.py`, `ADR-0031`) without any change
to `backtest.engine` -- each walk-forward fold's own TEST window is run
as the backtest's `start_date`/`end_date`, relying on the existing
point-in-time `AsOfDataView.get_bars` to supply prior history for a
strategy's own lookback. Added a 5-level `EvidenceLevel` vocabulary
(`INSUFFICIENT_EVIDENCE`/`PRELIMINARY`/`ROBUSTNESS_PENDING`/`CANDIDATE`/
`VALIDATED`) where `classify_evidence_level` is structurally incapable
of ever returning `VALIDATED` -- the highest level reachable by this
project's own code is `CANDIDATE`, gated on real data, minimum fold
counts, PBO/DSR having actually been applied (still deferred -- see the
Walk Forward row below), a positive-fold-ratio threshold, and evidence
spanning >= 2 distinct market regimes. **No real walk-forward evaluation
was run against real data this session** (network still BLOCKED); a
synthetic, realistic-scale dry run (PILOT_UNIVERSE's real 15 tickers
with synthetic deterministic prices, explicitly a pipeline check) did
confirm the full CLI end-to-end (benchmark construction, 4 strategies x
7 windows each, PBO/DSR applicability check) runs correctly.
`docs/research/STRATEGY-VALIDATION-REPORT.md` records the exact external
command needed to run this against the real 2023-2024 catalog and what
each of its 19 sections currently says. **No change to any Toss/Live
row; Live activation still Blocked for the same, unchanged reason.**

**Phase 26 update**: attempted to extend real data range and run actual
Walk-Forward against real data (this phase's stated goal) -- still
BLOCKED, but this session ran a three-layer independent diagnosis (DNS
resolution, a raw TCP connect bypassing the configured proxy, and a
direct HTTPS request also bypassing the proxy) instead of re-citing the
prior CONNECT-403 finding. DNS resolves correctly and the TCP handshake
succeeds; only the HTTP request itself is denied, with response header
`x-deny-reason: host_not_allowed` and a body naming the exact host and
remedy ("Add this host to your network egress settings to allow
access"), identical for `api.tiingo.com`/`stooq.com`/
`openapi.tossinvest.com`. This conclusively identifies the block as this
environment's own network egress allowlist -- not a provider-side
rejection, not DNS failure, not an authentication failure -- and names
the exact fix (add the host to the environment's egress allowlist),
though making that change is outside this session's own permissions.
No `MARKET_DATA_API_KEY` is set in this session either (checked).
Audited (not assumed) the point-in-time CASE 1-5 checklist and the
8-question corporate-action checklist from this phase's instruction:
CASE 1-4 and all 8 corporate-action questions were already correctly
covered by existing Phase 1/2/20 code and tests; CASE 5 (re-running real
ingestion must not retroactively change an already-established
point-in-time query result) had no direct existing test and was added
(`tests/data/test_phase26_point_in_time_cases.py`, 2 new tests, against
the real `IngestionRunner`/`DuckDBDataRepository` path). Added
`experiment_id`/`data_version` reproducibility fields to
`scripts/run_long_horizon_validation.py`'s JSON report, reusing
`data_infra.versioning.compute_data_version` exactly as
`scripts/ingest_real_market_data.py` already does. **No real
Walk-Forward evaluation was run against real data this session** (same
root cause as Phase 25, now precisely diagnosed rather than merely
re-confirmed). **No change to any Toss/Live row; Live activation still
Blocked for the same, unchanged reason.**

**Phase 27 update**: re-verified the same environment egress block
(identical `x-deny-reason: host_not_allowed`, no change) and attempted
to actually run real-data Walk-Forward -- still not possible from this
session. This phase's own audit (checking that real/synthetic status is
never confused in a report, per its own instruction) found a real bug:
`scripts/run_long_horizon_validation.py` had `classify_evidence_level(...,
is_real_data=True, ...)` hardcoded regardless of what `--db-path`
actually contained -- every synthetic dry run this script had ever been
used for (Phase 25's and Phase 26's own smoke tests included) was
therefore classified using real-data evidence thresholds, with no field
in the report even distinguishing the two. Fixed by adding a required
`--data-status {REAL,SYNTHETIC}` argument that gates `is_real_data`
directly, is folded into `experiment_id` (so REAL and SYNTHETIC runs of
an identical configuration can never collide into the same id), and is
written into the report's new `data_status` field. Verified end-to-end
against the same synthetic-scale dry-run catalog Phase 25/26 used: with
`--data-status SYNTHETIC` the evidence level now correctly reads
`INSUFFICIENT_EVIDENCE` (previously it would have read
`ROBUSTNESS_PENDING`, the real-data-only tier). Added 9 static AST/
source-based regression tests (the script itself is still never
imported or executed by the automated suite) covering this fix plus
several other structural properties this phase's instruction required
(no TEST-region leakage into the walk-forward call's own boundaries, all
strategies sharing one benchmark_id, no fabricated benchmark fallback,
no wall-clock/random usage). **No change to any Toss/Live row; Live
activation still Blocked for the same, unchanged reason.**

**Phase 28 update**: re-verified the environment egress block (identical
`x-deny-reason: host_not_allowed`, unchanged) and, going further than
prior phases, ran an exhaustive filesystem search for a real data
location -- project docs, ingestion manifests, DuckDB/Parquet files
anywhere, environment variables, existing scripts -- finding nothing.
`BLOCKED_BY_ENVIRONMENT` and `BLOCKED_BY_DATA` both apply. This phase's
own verification effort found a real gap: `--data-status REAL` was
previously accepted purely on the caller's word, with nothing checking
it against the data's own recorded provenance. Fixed by adding a
plausibility check -- every bar's `Provenance.source` must be `"tiingo"`
or `"stooq"` (verified directly against those providers' own source
code) whenever `--data-status REAL` is passed, or the script refuses to
proceed (exit code 1, before any strategy evaluation starts). Verified
at runtime, not just statically: the same synthetic-fixture catalog
construction Phase 25-27 used for dry runs is now correctly refused
under `--data-status REAL` and still runs correctly under
`--data-status SYNTHETIC` against the identical catalog. Added 3 static
AST-based regression tests. **No change to any Toss/Live row; Live
activation still Blocked for the same, unchanged reason.**

**Phase 29 update**: goal was a 2010 -> latest, broad,
survivorship-aware US equity Walk-Forward run -- **REAL WALK-FORWARD
EXECUTION: NOT COMPLETED**, network/data status unchanged (re-verified,
identical `x-deny-reason: host_not_allowed`, exhaustive filesystem
search again found nothing). Audited `src/data_infra/models.py`/
`repository.py` directly and found the survivorship-aware,
point-in-time-safe architecture the instruction asks for
(`SecurityMaster.security_id` as a permanent identifier independent of
ticker, `valid_from`/`valid_to` on both `SecurityMaster` and
`UniverseMembership`, `SecurityStatus.DELISTED`, and
`get_universe(as_of_time=...)`'s correct point-in-time filtering)
already existed, unmodified, since Phase 1 -- the real gap was that
`build_security_masters`/`build_universe_memberships` (Phase 24) never
used `SymbolMetadata.listed_from`/`listed_to`, so this mechanism had no
path to ever receive real per-symbol historical dates. Fixed
additively (byte-for-byte unchanged output for every existing
`SymbolMetadata` entry). Added `detect_ticker_collisions`
(distinguishes legitimate ticker reuse from a genuine same-time
collision) and `TiingoDataProvider.fetch_symbol_metadata`/
`normalize_symbol_metadata` (Tier 2 documentation, never exercised
against a live response -- broad-universe discovery groundwork).
Proved, against both `InMemoryDataRepository` and a real on-disk
`DuckDBDataRepository` restart (synthetic fixtures only): a delisted
security is correctly excluded from a post-delisting query and
included before it; a "current survivors only" query and a real
historical-point-in-time query genuinely differ. 19 new tests.
Full rationale: `docs/decisions/ADR-0032-security-identity-and-survivorship-aware-universe.md`.
**No change to any Toss/Live row; Live activation still Blocked for the
same, unchanged reason.**

**Phase 30 update**: goal was to move from "survivorship-aware
architecture exists" to "a real dataset has been acquired and
validated" -- **VALIDATION BLOCKED -- ENVIRONMENT**, root cause
unchanged. Re-verified network against a broader host set than any
prior phase: Tiingo/Stooq/Toss plus four additional candidate provider
hosts (Nasdaq Data Link, Polygon, Alpha Vantage, Financial Modeling
Prep, CRSP) all return the identical `403`/`host_not_allowed`, while
two control hosts (github.com, pypi.org) succeed in the same run --
confirms a scoped market-data-provider allowlist, not a general
outage. Found and fixed a genuine gap in
`scripts/ingest_real_market_data.py`'s manifest (instruction section
16): it previously reported only the *requested* start/end, never the
*actual* observed data range, risking a false "covers 2010-latest"
claim on a future real run. Now reports `actual_data_start`/
`actual_data_end` (computed from real persisted bars),
`delisted_count`, and `data_status`. Added 8 CASE-A-G survivorship
regression tests literally traceable to the instruction's own case
labels (no new mechanism -- Phase 1/29's machinery, reused). Added
ADR-0033: a data-source decision tree classifying 7 candidate
providers across the instruction's 6 required capability dimensions,
sourced from public documentation (never live-verified). 16 new tests.
**No change to any Toss/Live row; Live activation still Blocked for the
same, unchanged reason.**

**Phase 31 update**: primary objective was to determine how this
project can obtain real, survivorship-aware US equity data, and build
the infrastructure to ingest it -- not to invent/tune a strategy, not
to declare success. Network re-verified with a distinct-layer
diagnosis (DNS/TCP/HTTP separated, confirming `ENVIRONMENT_BLOCKED`
specifically, not auth/provider/dataset-absence) against 8 total
provider hosts, unchanged result. Built an actually-runnable external
data-acquisition pathway (instruction section 21): a new
`LocalFileDataProvider` (`src/data_infra/providers/file_import.py`)
reading pre-downloaded, normalized CSV files -- no network call, ever
-- wired through the same validated `IngestionRunner`/
`DataQualityFramework`/`DuckDBDataRepository` pipeline via
`scripts/import_external_market_data.py`; because this path makes no
network call it is directly exercised end-to-end by the automated
suite (unlike `ingest_real_market_data.py`). Extended the ingestion
manifest further (`providers_used`/`missing_symbols`/`active_count`/
`historical_universe_membership_available`). Added `audit_survivorship`
(`src/data_infra/universe.py`) -- an honest
FULLY_SUPPORTED/PARTIALLY_MITIGATED/CURRENT-UNIVERSE-ONLY/UNKNOWN
classifier, never overclaiming "survivorship bias solved." Added
ADR-0034: re-labels the provider matrix under this phase's required
VERIFIED_BY_DOCUMENTATION/VERIFIED_BY_ACTUAL_ACCESS/UNKNOWN/
NOT_AVAILABLE/ENVIRONMENT_BLOCKED vocabulary and commits to a decision
(both EXTERNAL_DATASET_REQUIRED and ENVIRONMENT_BLOCKED apply
simultaneously). 30 new tests. **No change to any Toss/Live row; Live
activation still Blocked for the same, unchanged reason.**

**Session 36 update (Phase 33 continued)**: the environment-blocked
premise underlying several rows above (this session's own network
access, Phase 24-31) no longer describes this project's actual current
state -- the user has since run real ingestion, real walk-forward
evaluation, and real PBO/DSR computation from their own network-
enabled environment, repeatedly, across many real symbols (most
recently a 63-symbol `RESEARCH_UNIVERSE_STAGE3` run). The Benchmark and
Walk Forward rows above have been corrected in place to reflect this;
the narrative Phase 24-31 entries above are left unchanged as an
accurate record of what THIS repository's own sandboxed session could
verify at each of those times, not a claim about what is true today.

**Session 36 further update (same phase, 20 more literature candidates
raw-IC-screened and wired into the same pool, `ADR-0051`/`ADR-0052`,
full account in `docs/research/STRATEGY-VALIDATION-REPORT.md`'s "Phase
33 Addendum")**: the candidate pool grew from 8 to 28. `size` briefly
reached `CANDIDATE` before a concentration-report check traced its
held-out TEST return to a single security (76.3% of TEST PnL during a
real oil-price-supercycle window) -- a real research-methodology gap
(portfolio breadth too narrow, `top_n=5`) was found and fixed
(`top_n=10`, applied uniformly to all 28 candidates, not tuned to favor
any one of them), and re-verification correctly dropped `size` below
the fold-consistency bar. Two candidates (`altman_z`,
`rank_average_ensemble`) still reach `CANDIDATE` at the corrected
breadth but both show strongly negative held-out TEST performance and
are held, not promoted. **Real result to date: zero candidates
VALIDATED across all 28 -- no change to any Toss/Live row; Live
activation still Blocked, and would remain blocked even absent every
other open row, since no strategy has been validated by a human.**

**Session 36 further update (same phase, the user's explicit "전부 다
진행하는건?" 3-part request -- `ADR-0054`/`ADR-0055`/`ADR-0056`)**:
(1) `combined_factor_score`, a 9-leg rank-averaged combination of every
sign-matching candidate from the 20-candidate screen, added to
`factor_scores.py` and wired for raw IC via `--score combined_factor`
-- deliberately NOT yet in the 28-candidate walk-forward pool, raw IC
comes first (ADR-0053's own precedent). (2) A real sector data path
(`SecEdgarFundamentalsProvider.fetch_submissions`/`normalize_
submissions`, SEC EDGAR's SIC classification) and an opt-in sector-
neutralization cap (`factor_strategy._select_target`,
`FactorStrategyParameters.sector_by_security`/`max_per_sector`) were
built specifically to prevent the `size` concentration artifact
described above structurally rather than only detect it after the
fact -- **not yet populated with real data (no network access in this
environment) and not yet activated for any pool candidate**, both
opt-in with `None` defaults so no existing candidate's behavior
changed. (3) `RESEARCH_UNIVERSE_STAGE4` (87 symbols) defined, deepening
the 5 sectors (Energy, Industrials, Utilities, Real Estate, Materials)
tied thinnest after Stage 3 -- Energy specifically because it was the
diagnosed root cause of the `size` concentration finding. All 9 CLI
scripts' `RESEARCH_UNIVERSE` alias repointed to Stage 4, but **no real
data has been ingested for its 24 new symbols** -- same "define now,
ingest later" sequencing Stage 3 itself followed (`ADR-0044`). No
change to any Toss/Live row from any of the three; full suite: 2249
passed.

**Session 36 further update (real Stage 4 ingestion completed by the
user, 2 real bugs found and fixed, both new candidates wired in --
`ADR-0057`)**: the user ran real ingestion for Stage 4's 24 new
symbols, surfacing 2 genuine bugs -- a real SEC EDGAR entry (LMT) whose
`filed` date preceded its `end` date crashed `FundamentalRecord`'s own
construction-time safety guard and, because the per-symbol loop only
caught provider errors (not `ValueError`), took down the entire
24-symbol run; both are fixed (the malformed entry is now skipped,
and the loop degrades to "this one symbol failed" for any per-symbol
data problem). Full suite: 2253 passed. With real Stage 4 data
available, `combined_factor` (mean_ic=-0.0530, `observations=43` vs.
79-80 for every other candidate -- a structural consequence of its own
9-leg all-or-nothing coverage requirement) and `idiosyncratic_
volatility` (mean_ic=-0.0151, near-zero) raw IC came back, both
negative/wrong-signed. Consistent with `ADR-0051`'s own "no post-hoc
filtering by raw IC sign" precedent, both were wired into the
walk-forward pool anyway (30 candidates now, up from 28) rather than
excluded for looking unfavorable -- excluding them now would itself
have been the post-hoc selection RULE 0.8 exists to prevent. No change
to any Toss/Live row.

**Session 36 final update (real 30-candidate walk-forward/PBO/DSR run
against Stage 4, 87 symbols)**: PBO=7.14% across 70 CSCV splits (down
from 14.29% at Stage 3's 63 symbols -- a wider universe, not a
methodology change). `idiosyncratic_volatility` is an unremarkable null
(58% positive folds, DSR=0.83, TEST=+3.61%). `combined_factor` shows
the worst fold-consistency of all 30 candidates (20% positive folds,
DSR=0.10) alongside only 8 TEST-window trades and a positive TEST
result (+52.98%) -- the exact signature `ADR-0057` predicted from its
own low `observations` count: too few securities pass its 9-leg
all-or-nothing filter to meaningfully test the "combining reduces
noise" hypothesis at scale, read as a sample-sparsity artifact rather
than evidence against the hypothesis. `altman_z`/`rank_average_
ensemble` remain the only 2 candidates reaching `CANDIDATE`, with
materially unchanged TEST-negative results from the Stage 3 run --
reproducing under an independently-widened universe strengthens,
rather than weakens, the "hold, do not promote" conclusion. **Zero of
30 candidates VALIDATED.** Full account:
`docs/research/STRATEGY-VALIDATION-REPORT.md`'s "Phase 33 Addendum"
Section H. No change to any Toss/Live row.
