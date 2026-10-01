# ADR-0227: Risk-free rate from 3-month T-bills; learning rejects fills priced on the decision bar

**Status:** Accepted
**Date:** 2026-10-01
**Deciders:** account owner (asked Claude to pick the risk-free rate, 2026-10-01), Claude Code session

## Context

Leftovers from the 2026-10-01 ADR sweep.

1. Every Sharpe and Sortino ratio in this project used a 0% risk-free
   rate (`BacktestConfig.risk_free_rate`, `PaperPerformanceConfig.
   risk_free_rate`, both `0.0`). ADR-0208 built a FRED adapter and left
   the choice of series and missing-day handling open. The account owner
   asked Claude to choose. Yields moved from about 0% (2010-2015) to
   about 5% (2023-2024), so no single constant is right for both a
   2000-2016 research run and the 2024- paper run.
2. The learning `DataCleaner` checked provenance, duplicates, missing
   decisions and non-finite values, but nothing caught a fill priced on
   the bar the decision was made on. ADR-0226 found that every daily
   paper fill had that problem, and the 2026-09-19 and 2026-09-26
   learning runs trained on such trades (no effect, nothing reads the
   candidates).

## Decision 1: the risk-free rate is the window-average 3-month T-bill yield

- Series: FRED `DGS3MO` (3-month Treasury constant maturity, daily,
  percent). It is the textbook short-term risk-free proxy, is never
  revised, and is already in the ALFRED macro store (ADR-0217, Release
  `fred-macro-vintages-v1`, 9,189 observations 1990-01-02..2026-09-24).
- Each evaluated window uses the mean of its daily yields as its annual
  rate (`backtest.risk_free.RiskFreeRates.average_annual_rate`). Sharpe's
  numerator is mean(r - rf), which equals mean(r) - mean(rf), so this is
  exact for the numerator. FRED "." days are skipped. A window with no
  observation raises instead of becoming 0%. The rate only scores a
  finished window and never reaches a strategy, so using the window's
  own yields is not look-ahead.
- Measured on the real store: 2000-01-01..2016-07-11 averages 1.71%,
  2010..2015 0.07%, TEST_3 (2016-07..2020-08) 1.33%, 2024-01-02..
  2026-09-25 4.45%.

Wiring:

- `strategy_research.runner.run_gross_and_net` and
  `run_walk_forward_evaluation` take `risk_free`; each fold, the held-out
  TEST and the ADR-0225 exam use their own window's average.
- `run_long_horizon_validation.py --risk-free-db-path` loads it from the
  macro store; `run_full_validation.yml` always downloads the store
  (required, no 0% fallback). Reports carry a `risk_free_rate` block.
- `run_paper_trading_cycle.py --risk-free-from-fred` fetches DGS3MO for
  the reported equity history from the FRED API (`FRED_API_KEY`,
  already an Actions secret). This is a report-only input, so a FRED
  failure prints a warning, uses 0%, and the report's `risk_free_rate`
  block says so; the trading cycle never depends on it.
  `paper_trading_cycle.yml` turns it on.

Not changed, on purpose:

- **DSR/PBO** read raw fold returns (`compute_dsr_for_all_candidates`),
  not Sharpe ratios, so the evidence gate and all earlier DSR numbers are
  unchanged and still comparable.
- **Cash does not earn interest** in the backtest engine. The real
  account is not known to pay interest on idle USD, so crediting it
  would flatter cash-heavy strategies. The macro filter's note ("cash
  earns 0%") stands.
- **`run_macro_filter_validation.py`** keeps 0%: its rules and pass rule
  are pre-registered as `macro_filter_config_v1` (ADR-0220). A v2 would
  have to pre-register the rate.

Effect on comparability: Sharpe/Sortino in reports produced after this
change are not comparable with earlier reports (lower by roughly
rf / volatility). The ADR-0225 unseen-names exam compares net Sharpe of
a candidate with the same-names buy-and-hold over the same window; it
has not been taken yet, so it now uses the excess-return Sharpe from the
start. This changes no result already seen (RULE 0.8).

## Decision 2: fills priced on the decision bar are rejected for learning

`backtest.fills.Fill` gains `reference_bar_available_time` (when the
pricing bar became available), set by both fill simulators
(`backtest.fills`, `broker.paper.execution`) and carried through both
journal payload serializers (additive, `None` when absent).
`DataCleaner` marks a sample `INVALID` with reason
`fill_priced_on_decision_bar` when that time is at or before the
decision's `decision_time`. Fills recorded before this field existed
cannot be checked and pass; the paper ledger is being rebuilt from
2024-01-02 with ADR-0226's fix (this field included), so the rebuilt
ledger is checked end to end.

## Decision 3: the two open R2 findings from ADR-0187

**Delisting gate.** `BacktestEngine` asked `get_security(sid, checkpoint)`
whether a held, price-less name was DELISTED. A real delisted record ends
at its `valid_to`, so after the delisting that call returns None and the
ERROR gate (ADR-0179) never fired. The engine now remembers the last
SecurityMaster it saw for each held name and uses it. The gate also now
applies only to names actually valued at average cost: a name ADR-0224
marks at its last close and settles is not "marked at cost", and before
this change it would have been flagged ERROR (invalidating the run) if
its record still said DELISTED. The 2026-10-01 point-in-time run
(`full-validation-20261001T122226Z.json`) had 76/76 valid folds for
every candidate, so it was not affected.

**Wayback ingestion timeout.** `ingest_stockanalysis_wayback_delisted_
prices.py` wrote every bar and the manifest only at the end, and a full
run (~142 symbols) is longer than the 60-minute job, so a timeout lost
everything. `--max-runtime-minutes` (45 in the workflow) stops starting
new symbols, saves what was fetched, and lists the rest under
`not_attempted` in the manifest for the next run. The pipeline has never
had a full run and nothing reads its output today (ADR-0224 uses Tiingo
for removed names).

## Consequences

- Sharpe/Sortino now mean excess return per unit of risk, as they do
  everywhere else.
- A regression of ADR-0154/ADR-0226 can no longer feed a model silently.
- Tests: `tests/backtest/test_risk_free.py`,
  `tests/strategy_research/test_runner_gross_net_and_benchmark.py::TestRiskFreeRate`,
  `tests/strategy_research/test_run_long_horizon_validation_wiring.py::TestRiskFreeRateWiring`,
  `tests/orchestration/test_run_paper_trading_cycle_cli.py::TestRiskFreeRateForThePerformanceReport`,
  the two workflow tests, `tests/learning/test_cleaning.py::TestFillPricedOnDecisionBar`,
  `tests/storage/test_trade_journal_persistence.py` (field survives restart),
  `tests/broker/paper/test_paper_accounting_invariants.py::TestFillRecordsItsPricingBar`,
  `tests/backtest/test_integrity.py` (two new engine-level gate tests, both
  fail on the old engine), `tests/scripts/test_ingest_stockanalysis_
  wayback_delisted_prices.py::TestRuntimeBudget`.
