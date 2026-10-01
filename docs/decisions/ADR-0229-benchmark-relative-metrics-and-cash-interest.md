# ADR-0229: SPY 대비 베타·추적오차·정보비율과 현금 이자 옵션

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** account owner (approved the proposal from the Goldman Sachs gs-quant comparison, 2026-10-02 07:12 KST), Claude Code session

## Context

A comparison against Goldman Sachs' open-source `gs-quant` (PyPI
`gs_quant-2.1.18`, report in the project's shared files
`reports/goldman-sachs-github-comparison-2026-10-02.md`) found two gaps:

1. `PerformanceReport` compared the portfolio with the benchmark only by
   cumulative return, CAGR and max drawdown. A strategy with beta 1.3
   that beats SPY in a bull market shows positive excess return without
   any alpha. gs-quant ships `timeseries.econometrics.beta`.
2. Idle cash earned 0%. gs-quant accrues interest on cash
   (`backtests/backtest_objects.py`, `ConstantCashAccrualModel`,
   `DataCashAccrualModel`, `OisFixingCashAccrualModel`). ADR-0227 already
   scores Sharpe/Sortino against the window-average `DGS3MO` yield, but
   the cash balance itself never grew, so every macro-filter rule
   (ADR-0220) that steps into cash was compared against SPY while
   forfeiting roughly 1.7%/year (the 2000-2016 `DGS3MO` average measured
   in ADR-0227).

## Decision

1. `PerformanceReport` gains `beta`, `tracking_error` (annualized),
   `information_ratio` and `jensen_alpha` (annualized, against the
   report's `risk_free_rate`), computed by
   `backtest.metrics.benchmark_relative_metrics` from daily portfolio and
   benchmark values matched by calendar date. They are `None` without a
   benchmark or with fewer than two common return days. The fields
   are additive with defaults, like the earlier pyfolio/quantstats ones.
2. `BacktestConfig.cash_interest: Optional[RiskFreeRates] = None`. When
   set, at each checkpoint after the first, positive cash is multiplied
   by `(1 + r/365) ** days`, where `days` is the calendar-day gap since
   the previous checkpoint and `r` is
   `RiskFreeRates.latest_annual_rate_before(checkpoint date)`: the latest
   `DGS3MO` observation dated strictly before that day, carried for at
   most 10 days. A longer gap earns nothing and records a
   `cash_interest_rate_missing` integrity WARNING. Interest is a
   `CashFlowRecord(reason="cash_interest")`. Negative cash is not charged.
   The rate source's `describe()` enters `configuration_version` only
   when set, so existing runs keep their hash.
3. Default stays off (owner's choice): only callers that pass the rates
   use it. `run_gross_and_net` / `run_walk_forward_evaluation` take
   `cash_interest`; `scripts/run_macro_filter_validation.py --cash-interest`
   turns on both cash interest and the ADR-0227 Sharpe rate from the same
   macro store, and its workflow input `cash_interest` defaults to true.
   `run_long_horizon_validation.py` is unchanged.

## Consequences

- Beta/IR separate leverage from alpha in every report from now on; old
  stored reports simply lack the fields.
- The macro filter can be re-graded with cash earning the T-bill yield.
  Its earlier all-INCONCLUSIVE result (2026-09-27) was produced with 0%
  cash and is not overwritten.
- A one-day lag (yesterday's yield for today's accrual) and actual/365
  compounding are approximations; at 2000-2016 yields the difference
  from exact T-bill returns is far below transaction costs.
- Not done: charging interest on negative cash (margin), and wiring cash
  interest into paper trading or the factor validation runs.
