# ADR-0067: `orchestration.paper_runner` -- the first real Regime->...->Order pipeline

**Status:** Accepted
**Session:** 36

## Context

Continuing directly from ADR-0062/ADR-0063 (sector exposure limit,
order notional cap), the user asked to actually wire those new
`PortfolioRiskEngine.assess` parameters into a real Paper/Live order
flow. Investigating where to add that wiring surfaced a much larger,
pre-existing gap than "two unwired parameters": **no code anywhere in
`src/` calls `PortfolioRiskEngine.assess` at all** (a repo-wide grep
found zero references outside `risk/engine.py` itself and its own
tests), and `backtest.engine.BacktestEngine` does not call `risk.sizing`/
`risk.engine` either -- `strategy_research`'s own strategies compute
target weights directly, bypassing the Phase 8 risk/sizing layer
entirely. The user was told this plainly (a much bigger task than
"wire two new checks") and, given the choice to defer or build the
pipeline now, explicitly chose to build it now.

This is not a bug or an oversight: `docs/specifications/
PHASE-15-paper-trading.md` section 1.1 explicitly named "a real,
running Trading Engine loop... wiring [Regime/Prediction/Decision/
Sizing/Risk] into an always-on scheduled process" as **out of scope**
for that phase, deferred to "a later phase." This ADR is that later
phase's first increment, done with the user's explicit, informed
consent to take on the larger scope.

## Decision

New top-level package `src/orchestration/` (deliberately NOT inside
`broker.paper.*`, which structurally forbids importing `data_infra.
repository`/`backtest.asof` per `tests/broker/paper/
test_paper_boundary.py` -- Regime/Prediction need an `AsOfDataView`, so
this composition point must live one layer above both). Its one
function so far, `paper_runner.run_cycle`, chains, for each requested
security at one `as_of_time`:

1. `Predictor.predict` (e.g. `DriftPredictor`)
2. `RegimeDetector.compute_composite`
3. `DecisionAgent.decide` (e.g. `BaselineRuleDecisionAgent`)
4. `PositionSizer.size` (e.g. `DeterministicPositionSizer`)
5. `PortfolioRiskEngine.assess` -- **with `sector_by_security` and
   whatever `RiskConfig` (including `max_order_notional`) the caller's
   `risk_engine` was built with** -- ADR-0062/ADR-0063's own parameters
   now actually reachable from a real order flow, not just tested in
   isolation
6. `broker.validation.build_validated_order` (already-existing, Phase
   13, previously unused by anything in this flow)
7. `PaperTradingSession.submit`, when validation produces a real order

Every intermediate stage's output is returned in a `CycleOutcome`
tuple -- nothing is silently discarded; persisting any of it (the same
five-repository pattern `tests/integration/test_risk_lineage.py`
already demonstrates) is left to the caller, matching `broker.
pipeline.submit_validated_order`'s own "return objects, caller decides
what to keep" precedent.

`_portfolio_view` builds the `PortfolioView` every stage needs from
`PaperTradingSession.account_summary()`'s real `BrokerPosition`
records (never fabricated), marking each held position to market using
the same "latest available bar" `AsOfDataView.get_bars` lookup
`backtest.engine.BacktestEngine.run()` already uses for its own
reference prices (5-day lookback here, slightly wider than that
engine's own 1-day window, to tolerate Paper's own real-world data
gaps) -- falling back to the position's own cost basis, never a
guessed market price, when no bar is available.

## What this deliberately does NOT do

- **Does not build a scheduler/timer/always-on process.** `run_cycle`
  is called once per checkpoint by whatever drives it -- still no code
  in this repository loops on a clock of its own. That remains a
  separate, still-open piece of "a later phase's concern."
- **Does not touch `broker.live.*` at all** (regression-tested,
  `tests/orchestration/test_orchestration_boundary.py`) -- this
  increment targets Paper Trading only, matching this project's
  established "validate in Paper before Live" precedent. Live wiring
  is a distinct future decision.
- **Does not source `value_history`** (past portfolio values) for
  `risk_engine.assess`. Documented plainly in the module's own
  docstring, found while writing this module's own tests: a caller
  using `RiskConfig`'s real `max_drawdown=0.20`/
  `max_portfolio_volatility=0.30` defaults will see every BUY REJECTed
  (`drawdown_unknown`/`portfolio_volatility_unknown`, per
  `PortfolioRiskEngine`'s own fail-closed design) until either those
  two fields are explicitly set to `None` or a future increment adds
  real historical-value sourcing. Every other risk check (position/
  gross-exposure/concentration/sector/notional/cash-minimum) is
  unaffected.
- **Does not touch `backtest.engine.BacktestEngine`** or any
  `strategy_research` strategy -- their own target-weight generation
  is unchanged; this is a new, separate composition path for Paper
  Trading specifically, not a replacement for backtest's existing
  (different) mechanism.
- **Does not persist anything itself** -- no repository writes happen
  inside `run_cycle`; a future increment that wants the full
  five-repository lineage persisted (matching `tests/integration/
  test_risk_lineage.py`'s own pattern) would add that at the call
  site, not inside this module.

## Tests

9 new: 6 integration (`tests/orchestration/test_paper_runner.py`,
against a real synthetic drifting-price scenario reusing this
project's own existing `backtest_helpers`/`predict_helpers`/
`paper_helpers` fixtures) covering full-chain lineage consistency, a
real BUY actually submitting and filling, a second cycle correctly
seeing the first cycle's real fill via `account_summary` (not a stale
or fabricated state), a configured sector limit without a mapping
rejecting the whole order end-to-end, a configured sector limit with a
mapping still submitting normally, and a tight `max_order_notional`
clamping the actually-submitted quantity versus an unclamped control.
3 new boundary tests (`tests/orchestration/test_orchestration_boundary.py`)
confirm no `broker.live`/`broker.toss` import or reference, and no
`CandidateModelStatus.APPROVED`/`DEPLOYED` reference. Full suite: 2306
passed (up from 2297).
