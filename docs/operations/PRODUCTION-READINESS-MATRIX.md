# Production Readiness Matrix

Phase 17 Production Safety Review, updated in Phase 18 (Paper
Trading Performance Report) and Phase 20 (Real Market Data Foundation
& Documentation Sync). One row per area the review instruction
names. "Status" is one of PASS / FAIL / BLOCKED / UNKNOWN / PARTIAL.
"Blocking?" answers "does this alone prevent Live activation today"
independent of every other row. "Human Decision Required?" names the
specific decision, or "No" if none remains.

**Phase 20 note on the four Toss-related BLOCKING rows below**: the
user provided the official Toss Securities OpenAPI 3.1.0 specification
directly this session, upgrading the evidence tier for all four
UNKNOWN capabilities from Tier 2 (secondary sources) to **Tier 1
(official, read directly)** — see `docs/operations/
TOSS-API-GAP-ANALYSIS.md` Phase 20 addendum for the extracted
endpoints/schemas. **This does not change any row's Status or Blocking
column**: `TossBrokerAdapter`/`endpoints.py`/`BrokerOrderStatus` were
deliberately left unimplemented this phase (Phase 20's own instruction:
analyze the spec, do not implement inline; propose a dedicated
implementation phase instead). The rows are still BLOCKED, but for a
different, better reason than before — "endpoint unconfirmed" has
become "endpoint confirmed, implementation not yet built."

| Area | Requirement | Current State | Evidence | Status | Blocking? | Human Decision Required? | Next Action |
|---|---|---|---|---|---|---|---|
| Toss API (general) | Endpoints confirmed against official documentation before use | All 4 previously-UNKNOWN capabilities now have Tier 1 (official OpenAPI spec, provided by the user in-session, Phase 20) endpoint/schema documentation; `TossBrokerAdapter` code itself deliberately not yet updated to use them | `docs/operations/TOSS-API-GAP-ANALYSIS.md` Phase 20 addendum | **DOCUMENTED, NOT IMPLEMENTED** | **Yes** (code still reports UNKNOWN) | No (an implementation-scheduling matter, not a policy choice) | Dedicated Phase to implement `TossBrokerAdapter`/`endpoints.py`/`BrokerOrderStatus` against the now-confirmed spec |
| Authentication | OAuth2 Client Credentials, credentials never logged/persisted | Implemented, confined to `broker/toss/auth.py` | `tests/broker/toss/test_toss_auth.py`; repo-wide scan `tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree` | **PASS** | No | No | None |
| Account (balance query) | `get_account` against a confirmed endpoint | Raises `BrokerCapabilityError`; endpoint now confirmed (Tier 1, Phase 20: `GET /api/v1/accounts` + `GET /api/v1/buying-power`) but not yet implemented in code | `src/broker/toss/adapter.py`; `docs/operations/TOSS-API-GAP-ANALYSIS.md` | **BLOCKED** | **Yes** | No | Same as Toss API row |
| Positions | `get_positions` against a confirmed endpoint | Raises `BrokerCapabilityError`; endpoint now confirmed (Tier 1, Phase 20) but not yet implemented in code | same | **BLOCKED** | **Yes** | No | Same as Toss API row |
| Orders (creation) | Submit order against a confirmed endpoint, correctly mapped responses | Implemented and confirmed; 5xx handling fixed this phase | `tests/broker/toss/test_toss_production_safety_contract.py` | **PASS** | No | No | None |
| Cancellation | `cancel_order` against a confirmed endpoint | Raises `BrokerCapabilityError`; endpoint now confirmed (Tier 1, Phase 20: `POST /api/v1/orders/{orderId}/cancel`, note the response's `orderId` is a newly issued id, not the original) but not yet implemented in code | `docs/operations/TOSS-API-GAP-ANALYSIS.md` | **BLOCKED** | **Yes** | No | Same as Toss API row; also blocks Runbook's automated-cancellation step |
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
| Walk Forward | Rolling-window re-validation / PBO / Deflated Sharpe | **Explicitly deferred since Phase 9**; Phase 18 researched all three techniques with primary-source citations; Phase 20 added concrete trigger conditions for ending DEFER (a skill-claiming trainer is introduced; multiple candidates compared for one promotion; a human is about to approve a candidate for Live capital) and confirmed none has fired yet, still not implemented | `docs/research/walk-forward-pbo-deflated-sharpe.md` section 9; `docs/decisions/ADR-0017-model-evolution.md` decision 3 | **RESEARCHED, TRIGGER CONDITIONS DEFINED, NOT IMPLEMENTED** | No (not independently blocking Live, since it gates model *quality* confidence, not a hard safety boundary) | **Yes** -- whether Live activation should ever require this before deploying a non-trivial model | Re-evaluate the instant any Phase 20 §9.1 trigger condition becomes true; until then, no action needed |

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
Tier 1 this session (the user provided the official Toss OpenAPI spec
directly), but their Status/Blocking columns are unchanged on purpose
-- `CapabilityStatus` in code still reports `UNKNOWN` because
implementation was deliberately deferred to a dedicated future phase,
not because the documentation gap reopened. Separately, Phase 20 built
a real (if network-access-unverified) market data foundation
(`ADR-0025`/`ADR-0026`, `src/data_infra/providers/tiingo.py`,
`src/backtest/total_return.py`) and proved the Paper Trading pipeline
can structurally consume it end to end
(`tests/integration/test_paper_trading_real_market_data.py`) -- neither
of these changes any row's Blocking status, since Live activation was
already, and remains, independently blocked by the four Toss rows
above regardless of market-data or Paper Trading readiness.
