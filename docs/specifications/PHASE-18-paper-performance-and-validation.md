# Phase 18: Production Safety Follow-up + Paper Trading Validation

## 0. Purpose

Follow-up to Phase 17's Production Safety Review, closing its
highest-priority BLOCKED/PARTIAL items. Not Live Trading activation --
`LIVE_TRADING_ENABLED` was never touched, no real Toss API call was
made, no `LiveActivationApproval` was constructed for a real purpose.
The core deliverable is a Paper Trading Performance Report so Paper
results can be evaluated on more than raw return, plus a set of
regression tests re-verifying Phase 17's fixes hold under the full
pipeline and re-verifying the Live Safety Gate's nine required
blocking dimensions.

## 1. Repository Integrity (verified via git, not assumed)

- Branch: `claude/phase-18-paper-performance-and-validation`, created
  directly from `claude/phase-17-production-safety-review` at commit
  `c1d738e843398ad62fe2ceaa5ebf90846e6428d6` (parent
  `3302e6ac9f70a055629b967b2a1a8bb7b898f309`) -- both hashes
  independently confirmed via `git log`, not assumed from the
  instruction's own quoted values.
- `origin/main` confirmed a non-diverged ancestor.
- 0 merge commits across all 21 pre-Phase-18 commits; single linear
  history confirmed (`git log --format='%H %P'` -- every commit has
  exactly one parent except the root).
- Working tree clean before this phase's first edit; local HEAD ==
  remote HEAD for the Phase 17 branch before branching.

## 2. Baseline Tests

`python -m pytest tests/ -q` before any Phase 18 edit: **1345 passed,
0 failed, 0 skipped, 0 warnings** -- matches Phase 17's own final count
exactly, confirming no drift between sessions.

## 3. What This Phase Built

### 3.1 `broker.paper.performance` -- Paper Trading Performance Report

New module computing `total_return`/`cagr`/`volatility`/`sharpe_ratio`/
`sortino_ratio`/`calmar_ratio`/`max_drawdown`/`turnover`/
`total_transaction_cost`/`total_slippage`/`num_trades`/`win_rate`/
`avg_trade_return`/`realized_pnl`, plus a `BenchmarkComparison`. See
`docs/decisions/ADR-0024-paper-performance-and-validation.md` for the
full design rationale (why a new module rather than modifying
`backtest.metrics`, why `PortfolioAccounting`/Trade Journal are reused
rather than duplicated, why no S&P 500 data was fabricated).

Explicit definitions, per instruction section 4:

- **Return frequency**: whatever the caller's `equity_history` actually
  is; stated as `PaperPerformanceConfig.return_frequency` (default
  `"DAILY"`) -- this module never resamples.
- **Annualization factor**: `PaperPerformanceConfig.periods_per_year`
  (default `252`, matching `backtest.metrics`'s own existing default
  for a daily series).
- **Risk-free rate**: `PaperPerformanceConfig.risk_free_rate` (default
  `0.0`, matching `backtest.metrics.sharpe_ratio`'s existing default).
- **Downside deviation**: population (ddof=0) standard deviation of
  `min(0.0, excess_return)` -- matches `backtest.metrics.sortino_ratio`'s
  existing convention exactly (an intentional ddof asymmetry against
  Sharpe's ddof=1 that already existed in Phase 2, not introduced here).
- **Drawdown**: `backtest.metrics.compute_max_drawdown` (Phase 2,
  reused unchanged).
- **Zero volatility** -> Sharpe `None`, reason `"zero_volatility"`.
- **Zero downside deviation** -> Sortino `None`, reason
  `"zero_downside_deviation"`.
- **Zero max drawdown** -> Calmar `None`, reason `"zero_drawdown"`.
- **Fewer than `min_periods_for_ratios` (default 5, reusing the exact
  precedent `risk.config.RiskConfig.min_history_for_volatility`
  already established in this codebase) equity points** -> every
  equity-curve metric `None`, reason `"insufficient_data"`.
- **Zero closed trades** -> `win_rate`/`avg_trade_return` `None`,
  reason `"insufficient_data"`.
- **Turnover not supplied by the caller** -> `None`, reason
  `"not_supplied"` (distinct from a genuine, caller-computed `0.0`).

Deterministic: no `random`, no `datetime.now()`/`utcnow()` anywhere in
the module (`tests/broker/paper/test_paper_performance.py::
TestNoRandomnessUsed`, an AST scan); the same inputs always produce an
equal `PaperPerformanceReport`
(`tests/broker/paper/test_paper_performance.py::TestDeterminism`).

### 3.2 `PaperBrokerAdapter.accounting` (additive)

A one-line read-only property exposing the `PortfolioAccounting`
instance the adapter already constructs internally (Phase 2,
unmodified) -- see ADR-0024 decision 2. Zero behavior change for any
existing caller; the full pre-existing Paper Trading test suite passes
unchanged.

### 3.3 Persistence: `paper_performance_reports`

New DuckDB table + `storage.paper_performance_repository.
DuckDBPaperPerformanceReportRepository`/`InMemoryPaperPerformanceReportRepository`,
following `storage.live_repository`'s exact existing pattern (natural-
key idempotency on `report_id`, append-only, `payload_json` blob).
Purely additive to `storage/schema.py`.

### 3.4 Bug-fix re-verification (instruction sections 8-9)

`tests/broker/live/test_live_partial_fill_and_5xx_regression.py` --
re-proves, through `broker.live.journal.build_fill_from_broker_response`
+ `TradeJournalRepository.record_trade` specifically (not just Paper's
path, already covered by Phase 17), that two `BrokerOrderResponse`s for
the same `client_order_id` at two different `responded_at` times both
reach the Trade Journal, and that a Toss 5xx response, run through the
real `TossBrokerAdapter` + `LiveTradingSession.submit`, produces
`UNKNOWN` + `RECONCILIATION_REQUIRED` with exactly one transport call
(no blind retry), and that a second submission attempt is blocked
before ever reaching the broker again.

### 3.5 Live Safety Gate -- nine-dimension regression (instruction
    section 11)

Investigated whether `evaluate_safety_gate` (or its surrounding
structure) blocks a new Live order whenever any of account/positions/
order status/broker capability/reconciliation/model status/risk
status/data health/monitoring health is UNKNOWN. Found: six of nine
are direct `SafetyGateContext` fields; the remaining three
(reconciliation, data health, monitoring health) are enforced one
layer up, in `LiveTradingSession`'s own operational-state machine and
the kill-switch trigger chain (Phase 17) respectively.
`evaluate_safety_gate` has exactly two production call sites, both of
which already independently apply those checks -- confirmed by reading
`broker/live/session.py`, not assumed. No new fields were added (see
ADR-0024 decision 6); instead,
`tests/broker/live/test_live_safety_gate_nine_dimensions.py` proves
each dimension's actual enforcement path blocks.

### 3.6 Walk-Forward / PBO / Deflated Sharpe -- research only

`docs/research/walk-forward-pbo-deflated-sharpe.md` -- defines the
design decision these techniques would inform, documents each
technique with primary-source citations (Bailey/Borwein/López de
Prado/Zhu 2015 for PBO; Bailey/López de Prado 2014 for the Deflated
Sharpe Ratio; López de Prado's purging/embargo method), maps each to
this project's current architecture, and ends in a `DECISION REQUIRED`
rather than an implementation or a unilateral recommendation.

## 4. Review Areas -- Verdicts

| # | Area | Verdict | Evidence |
|---|---|---|---|
| 1 | Paper Trading Performance Report | **PASS** | `src/broker/paper/performance.py`; `tests/broker/paper/test_paper_performance.py` (20 tests) |
| 2 | Sharpe/Sortino/Calmar/Drawdown/Turnover integrity | **PASS** | Every zero-denominator/insufficient-data case explicit, never fabricated (`TestZeroDenominatorCases`, `TestInsufficientData`) |
| 3 | Benchmark comparison structure | **PASS** | `BenchmarkComparison`, reusing `backtest.benchmark.BenchmarkEngine` unchanged |
| 4 | Benchmark unavailable handling | **PASS** | No S&P 500 data exists in this repository (confirmed by search); `BENCHMARK_UNAVAILABLE` is the explicit, structurally-enforced default |
| 5 | Partial-fill journal regression (Paper + Live) | **PASS** | `tests/integration/test_paper_performance_scenarios.py` (Scenario B), `tests/broker/live/test_live_partial_fill_and_5xx_regression.py` |
| 6 | Toss 5xx -> UNKNOWN regression | **PASS** | `tests/broker/live/test_live_partial_fill_and_5xx_regression.py` (full `LiveTradingSession` pipeline, real `TossBrokerAdapter`) |
| 7 | Paper -> Journal -> Experience lineage | **PASS (re-confirmed)** | Phase 17's own tests re-run unchanged and passing; no code touched this path |
| 8 | Risk policy undefined -> Live safely blocked | **PARTIAL -- DECISION REQUIRED** | See section 5 below; `None` currently means "not enforced," not "blocked," by Phase 16's own deliberate design |
| 9 | Monitoring connection verification | **PASS** | `tests/integration/test_paper_monitoring_integration.py`; deliberately did not add a new collector for Sharpe/etc. (see section 6) |
| 10 | Security scan | **PASS** | Full repo-wide scan re-run, unchanged pass (`tests/broker/live/test_production_safety_cross_cutting.py::TestSecretAccessIsConfinedToOneFileAcrossTheWholeSrcTree`) |
| 11 | Leakage / point-in-time | **PASS** | Full suite re-run unchanged; new module takes no wall-clock time internally |
| 12 | Reproducibility | **PASS** | `tests/broker/paper/test_paper_performance.py::TestDeterminism`, `TestNoRandomnessUsed` |
| 13 | Persistence + restart | **PASS** | `tests/storage/test_paper_performance_repository.py` (7 tests) |
| 14 | Candidate approval boundary | **PASS (re-confirmed)** | `tests/broker/paper/test_paper_performance_boundary.py`; repo-wide scan re-run unchanged |
| 15 | Live Trading Gate strengthening | **PASS (via existing structure, not duplicated)** | `tests/broker/live/test_live_safety_gate_nine_dimensions.py` |
| 16 | Walk-Forward/PBO/Deflated Sharpe | **RESEARCHED, NOT IMPLEMENTED -- DECISION REQUIRED** | `docs/research/walk-forward-pbo-deflated-sharpe.md` |

## 5. Risk Policy DECISION REQUIRED (instruction section 12)

```
DECISION REQUIRED
Problem: LiveTradingConfig.max_daily_loss / RiskConfig.max_turnover /
LiveTradingConfig.max_order_frequency_per_hour all default to None.
Phase 16's own design (docs/decisions/ADR-0022, LiveTradingConfig's own
comment) treats None as "not enforced" -- the kill switch simply never
triggers on that dimension. Instruction section 12 raises "None ->
LIVE BLOCKED" as a possible stricter alternative.
Current Design: None = not enforced (an operator must set a value
explicitly for it to have any effect). evaluate_safety_gate does not
read any of these three fields at all -- they only feed
evaluate_kill_switch_triggers, an entirely separate mechanism.
Option A: Keep the current design (None = not enforced). An operator
can activate Live with no daily-loss/turnover/order-frequency cap at
all, relying solely on the other 11 safety-gate conditions and manual
oversight.
Option B: Change the design so that any of the three being None
structurally blocks evaluate_safety_gate itself (a new,
always-required condition: "every configured risk-policy threshold
must have an explicit value before Live can activate at all").
Recommendation: No recommendation is made between A and B -- this is
the same category of financial-policy decision as the individual
threshold values themselves (docs/operations/LIVE-RISK-POLICY.md), not
a technical implementation detail, and changing Phase 16's own
documented design unilaterally is exactly what this phase's
instructions forbid ("AI가 risk policy를 결정하거나 변경하지 못하게
할 것").
Impact: Under Option A (current), Live could activate today with zero
automatic loss/turnover/frequency circuit breakers if an operator never
sets these three values -- the only backstops would be the other gate
conditions (which already independently block Live via the Toss
capability gap) and human oversight. Under Option B, Live could never
activate until an operator makes all three decisions explicitly, even
if they judge manual oversight sufficient for an initial small-capital
activation.
```

This is carried forward as an open decision, not resolved by this
phase's code. No code change was made to `evaluate_safety_gate` or
`LiveTradingConfig` as a result.

## 6. Monitoring Connection -- Evaluated, Not Extended

Instruction section 17 asks whether the Performance Report's own
metrics (Sharpe/Sortino/Calmar/turnover/transaction cost/slippage)
should connect to Monitoring. Evaluated and **not implemented**:
`monitoring.models.ComponentHealth`'s model is a point-in-time
health-status verdict (HEALTHY/DEGRADED/UNAVAILABLE/UNKNOWN) about a
continuously-running component, not a periodic evaluation-report
number. Forcing a Sharpe ratio into that model would require inventing
a new "is this Sharpe ratio healthy" threshold -- exactly the kind of
unilateral policy invention this project's discipline forbids. Phase
17's `MonitoringComponent.ACCOUNT` (equity/PnL/drawdown) remains the
right fit for Monitoring, because those *are* continuously-observable
account-state facts; nothing new was added here.
`tests/integration/test_paper_monitoring_integration.py` confirms Paper
Trading still reaches both the pre-existing broker collector and
Phase 17's account collector together, unchanged by this phase.

## 7. Test Strategy (Phase 18 additions)

| Category | File |
|---|---|
| Performance metrics (all required categories: insufficient data, zero volatility, zero downside deviation, zero drawdown, determinism, no randomness, validation) | `tests/broker/paper/test_paper_performance.py` |
| Performance module boundary (no learning/evolution touch) | `tests/broker/paper/test_paper_performance_boundary.py` |
| Persistence + restart | `tests/storage/test_paper_performance_repository.py` |
| Scenario validation A-H (real pipeline) | `tests/integration/test_paper_performance_scenarios.py` |
| Live partial-fill + Toss 5xx regression (full pipeline) | `tests/broker/live/test_live_partial_fill_and_5xx_regression.py` |
| Live Safety Gate nine-dimension regression | `tests/broker/live/test_live_safety_gate_nine_dimensions.py` |
| Monitoring integration (Paper -> collectors) | `tests/integration/test_paper_monitoring_integration.py` |

## 8. Known Issues / Not Implemented

- Risk-policy `None` semantics DECISION REQUIRED (section 5) --
  unresolved by design.
- Walk-Forward/PBO/Deflated Sharpe DECISION REQUIRED (section 3.6) --
  researched, not implemented.
- `backtest.metrics` and `broker.paper.performance` now have two
  different Sharpe/Sortino/Calmar conventions (zero-fallback vs.
  Optional+reason) -- a deliberate, documented asymmetry (ADR-0024
  decision 1), not unified this phase.
- No new S&P 500 (or any real benchmark) data was added to this
  repository -- `BENCHMARK_UNAVAILABLE` will be every Paper
  Performance Report's benchmark status until real benchmark data is
  ingested (ADR-0005, still deferred).
- Toss `cancel_order`/`get_order_status`/`get_account`/`get_positions`
  remain `CapabilityStatus.UNKNOWN` -- no endpoint was guessed; no new
  research was attempted this phase beyond re-confirming Phase 17's
  findings still hold (network access to the official docs remains
  unavailable in this environment).

## 9. Phase Boundary

This phase changed: `src/broker/paper/adapter.py` (one new read-only
property), `src/storage/schema.py`/`src/storage/serialization.py`
(additive), and added `src/broker/paper/performance.py`,
`src/storage/paper_performance_repository.py`. It did **not** change
`src/backtest/metrics.py`, `src/backtest/benchmark.py`,
`src/backtest/portfolio.py`, `src/broker/live/safety_gate.py`,
`src/broker/live/kill_switch.py`, `src/broker/live/config.py`,
`src/risk/config.py`, `src/broker/toss/adapter.py`'s capability
report, or any Phase 0-17 test's assertions (only additions).

## 10. Definition of Done

- [x] Paper Trading performance report implemented.
- [x] Sharpe/Sortino/Calmar/Drawdown/Turnover integrity verified.
- [x] Benchmark comparison structure implemented.
- [x] Benchmark-unavailable explicit handling verified.
- [x] Partial-fill journal regression PASS (Paper and Live).
- [x] Toss 5xx -> UNKNOWN regression PASS.
- [x] Paper -> Journal -> Experience lineage PASS (re-confirmed).
- [x] Risk-policy-undefined Live-blocking behavior verified and
      documented (DECISION REQUIRED where the existing design does not
      already block).
- [x] Monitoring connection verified (and evaluated, not extended).
- [x] Security scan PASS.
- [x] Leakage tests PASS.
- [x] Reproducibility PASS.
- [x] Persistence + restart PASS.
- [x] All pre-existing tests still pass (1345 -> see completion
      report for the final count).
- [x] Documentation updated.
- [x] Git integrity PASS.
- [x] Live Trading remains BLOCKED pending Toss capability
      verification.
