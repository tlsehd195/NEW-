# Production Readiness Matrix

Phase 17 Production Safety Review, updated in Phase 18 (Paper
Trading Performance Report), Phase 20 (Real Market Data Foundation
& Documentation Sync), Phase 21 (Toss Broker Adapter Completion),
Phase 22 (Real-Data Paper Trading / US Long-Term System Hardening),
and Phase 23 (Strategy Research & Real Market Data Validation).
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
| Risk (policy completeness) | Every named risk limit DEFINED or explicitly deferred with a human decision on file | 1 DEFINED, 6 INHERITED (never re-approved for real capital specifically), 3 UNDEFINED, 3 BLOCKING (no field exists). `evaluate_safety_gate` does not itself read any of the three UNDEFINED fields at all -- `None` means "not enforced," never "blocked," by Phase 16's own deliberate design. Phase 20 added reasoned *proposed* values for the 3 UNDEFINED fields (`max_daily_loss` = 2% of eventual initial capital, `max_turnover` = 3.0, `max_order_frequency_per_hour` = 30) -- proposals only, not ratified | `docs/operations/LIVE-RISK-POLICY.md` ("Phase 20 -- Proposed initial values" section); `docs/specifications/PHASE-18-paper-performance-and-validation.md` section 5 | **PARTIAL** | **Yes** (daily loss / order frequency limits still unset in config) | **Yes** -- ratify or revise the 3 Phase 20 proposed values in `LIVE-RISK-POLICY.md`, plus the still-open design-level `DECISION REQUIRED` (should `None` block Live outright?) | Human ratifies/revises the 3 proposed values and decides whether their absence should structurally block Live |
| Kill Switch | Auto-engage on critical conditions; AI cannot release | Implemented; `data_health` trigger added this phase | `tests/broker/live/test_live_kill_switch.py` | **PASS** | No | No | None |
| Monitoring | Portfolio/broker/data/model health collected, persisted, alertable | Phase 15 equity/PnL/drawdown gap closed in Phase 17; Paper performance-report metrics (Sharpe/Sortino/etc.) built in Phase 18 but deliberately not fed into Monitoring (a periodic report, not a component-health signal -- ADR-0024 decision, `docs/specifications/PHASE-18-paper-performance-and-validation.md` section 6) | `tests/integration/test_paper_monitoring_integration.py` | **PASS** | No | No | None |
| Drift | Feature/prediction drift detected and recorded | Implemented, unmodified this phase | `src/monitoring/drift.py`; Phase 14 tests | **PASS** | No | No | None |
| Paper Trading | Order->Fill->Journal->Experience traced with real code; performance evaluated beyond raw return | Lineage traced in Phase 17 (5 scenarios A-E); Phase 18 built `broker.paper.performance` (Sharpe/Sortino/Calmar/drawdown/turnover/cost/slippage/win-rate/benchmark) and re-verified the lineage under 8 further scenarios (A-H) including partial fill, insufficient cash/position, duplicate order id, broker failure, and drawdown | `tests/broker/paper/test_paper_performance.py`; `tests/integration/test_paper_performance_scenarios.py` | **PASS** | No | No | None |
| Learning | Experience -> Training Dataset provenance-safe; PAPER cannot become LIVE | Re-verified this phase, including a bypass-the-filter defense-in-depth test | `tests/integration/test_paper_learning_readiness_lineage.py::TestPaperToLearningProvenanceSafety` | **PASS** | No | No | None |
| Model Validation | No automatic Candidate->APPROVED/DEPLOYED path anywhere | Re-verified repo-wide (not just `evolution.*`) this phase | `tests/evolution/test_production_safety_candidate_boundary.py` | **PASS** | No | No | None |
| Rollback | Emergency halt and recovery procedure exists and matches code | Kill switch + Runbook exist; cancel-on-shutdown is a deliberate non-automatic choice | `docs/operations/LIVE-TRADING-RUNBOOK.md`; `docs/decisions/ADR-0022` decision 8 | **PASS** (as designed) | No | **Yes** -- whether to ever automate cancel-on-shutdown | Human decides if/when automated cancellation should be built |
| Audit | Every critical event leaves a persisted record | Confirmed for broker/data/reconciliation/kill-switch/model/provider failures | `docs/specifications/PHASE-17-production-safety-review.md` section 6 | **PASS** | No | No | None |
| Secrets | Credential access confined to one file, never persisted | Re-verified repo-wide this phase (broader than Phase 13's package-scoped check) | `tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree` | **PASS** | No | No | None |
| Runbook | Procedures match actual code; no secret values stored in it | Re-read and mechanically verified this phase | `tests/broker/live/test_production_safety_cross_cutting.py::TestRunbookReferencesStillResolveInCode` | **PASS** | No | No | None |
| Benchmark | S&P 500 Buy & Hold uses the same period/capital/cost assumptions as the run it's compared against | True for the historical Backtest engine (`backtest.benchmark.BenchmarkResult` shares `initial_capital`/cost model by construction); Phase 18 built `broker.paper.performance.BenchmarkComparison` reusing the same `BenchmarkEngine` for Paper. Phase 20 resolved the long-open PRICE_RETURN vs TOTAL_RETURN `DECISION REQUIRED` (ADR-0026: SPY as proxy, TOTAL_RETURN target) and implemented `backtest.total_return.build_total_return_benchmark_points` to construct it, but **no real SPY price/dividend data has been ingested** (Tiingo access unverified from this environment, ADR-0025) -- every report's `benchmark.status` will still read `BENCHMARK_UNAVAILABLE` until real data is ingested | `src/backtest/benchmark.py`; `src/backtest/total_return.py`; `src/broker/paper/performance.py`; `docs/decisions/ADR-0026-benchmark-return-type.md` | **PASS (structure)** / **BENCHMARK_UNAVAILABLE (data)** | No (not independently blocking) | No (return-type decision made; only data ingestion remains, an access problem not a policy choice) | Obtain real Tiingo access, ingest SPY price + dividend history, run `build_total_return_benchmark_points`, persist via `DataRepository.add_benchmark_point` |
| Transaction Cost | Modeled and attributed | Implemented in Backtest (`backtest.metrics`) and Paper (`Fill.commission`/`spread_cost`), per-fill and now aggregated into a Paper-level report (`total_transaction_cost`, summed from `TradeRecord.transaction_cost`) | `src/broker/paper/journal.py`; `src/broker/paper/performance.py`; `tests/integration/test_paper_performance_scenarios.py::TestScenarioG_TransactionCostAndSlippageFlowIntoTheReport` | **PASS** | No | No | None |
| Slippage | Modeled and attributed | Implemented per-fill in both Backtest and Paper (`Fill.slippage_cost`); **not computed at all for Live** (`broker.live.journal.build_fill_from_broker_response` sets `slippage_cost=0.0`, documented as an honest limitation, no independent quote to compare against) | `src/broker/live/journal.py`; `docs/decisions/ADR-0022` decision 9 | **PASS** (Backtest/Paper); **KNOWN LIMITATION** (Live) | No | No | Unchanged from Phase 16 -- would require an independently-sourced quote feed |
| OOS (Out-of-Sample) | Validation split distinct from training | `learning.config.SplitConfig` (train/validation/test), chronological | `src/learning/config.py`; `src/learning/dataset.py` | **PASS** (split exists) | No | No | None -- statistical robustness (PBO/overfitting) remains explicitly deferred, see next row |
| Walk Forward | Rolling-window re-validation / PBO / Deflated Sharpe | **Explicitly deferred since Phase 9**; Phase 18 researched all three techniques with primary-source citations; Phase 20 added concrete trigger conditions for ending DEFER (a skill-claiming trainer is introduced; multiple candidates compared for one promotion; a human is about to approve a candidate for Live capital) and confirmed none has fired yet. Phase 23 added a strategy-level (not model-evolution-level) walk-forward window *generation mechanism* (`strategy_research.splits.generate_walk_forward_windows`, tested against synthetic dates only) and confirmed no real walk-forward *evaluation* was possible this session (no real historical data obtained) | `docs/research/walk-forward-pbo-deflated-sharpe.md` section 9; `docs/decisions/ADR-0017-model-evolution.md` decision 3; `docs/decisions/ADR-0029-strategy-research-framework.md` decision 5 | **RESEARCHED, MECHANISM IMPLEMENTED, NO REAL EVALUATION RUN** | No (not independently blocking Live, since it gates model *quality* confidence, not a hard safety boundary) | **Yes** -- whether Live activation should ever require this before deploying a non-trivial model | Re-evaluate the instant any Phase 20 §9.1 trigger condition becomes true, or the instant real market data becomes obtainable (whichever the strategy-research track needs first); until then, no action needed |

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
