# ADR-0218: Rebalance sizing uses sell proceeds and an equal-weight cap

**Status:** Accepted
**Date:** 2026-09-26
**Deciders:** account owner, Claude Code session

**Related documents:** `docs/decisions/ADR-0216` (the re-run that surfaced
this), `docs/decisions/ADR-0194` addendum (contribution report replays
fills plus corporate actions), `docs/decisions/ADR-0051` (generic factor
strategies).

## Context

In `docs/research/reports/full-validation-20260926T183155Z.json`,
`sloan_accruals` showed a held-out (2018-07-11..2020-08-28) net return of
**+306%** against SPY's +30.9%. Its own concentration report claimed a
total P&L of **-$2,418** on the same trades. Reproducing the run locally
(same catalogs, `--initial-capital` default of $10,000) gave +307%
exactly. The fills showed two bugs.

1. **Sizing ignored this rebalance's own sell proceeds.** Every
   equal-weight strategy (`factor_strategy._orders_from_target`,
   `LongTermMomentumStrategy`, `RankAverageEnsembleStrategy`,
   `TrendVolatilityStrategy`, `MLStrategy`) sized new buys as
   `portfolio.cash / len(to_buy)`. The engine fills sells before buys,
   but the sell proceeds were never counted. So they sat idle until the
   next rebalance, which then split all of the accumulated cash across
   however few names were new. In 2019-04, sloan_accruals sold about
   $6,000 but bought only about $1,100. In 2019-07, the ~$6,900 of idle
   cash went into two names: TSLA got 14 shares ($3,431, **34% of the
   book**) and AMZN got 1 share ($2,011). TSLA's ~9x run to 2020-08
   produced nearly the whole +306%. That is a sizing artifact, not a
   factor signal.
2. **The concentration report valued open positions at `adjusted_close`.**
   Tiingo restates that price for every split up to today (TSLA
   2020/2022, AMZN 2022), while the report replays raw-price fills. TSLA's
   +$27k gain read as a loss, and AMZN read -$1,842. The report built to
   flag single-name concentration hid it instead.

## Decision

1. `backtest.strategy.new_position_cash`. Each new position gets
   `min((cash + this rebalance's sell proceeds at latest close) × (1 −
   margin) / new_names, portfolio_value × (1 − margin) / len(target))`.
   All five strategies above use it. Positions already held are still
   not resized, same as before.
2. `run_long_horizon_validation.py`'s `final_prices` uses the raw close,
   consistent with the fills and with `BacktestEngine`'s own marks.

Local check of the same held-out run after the fix: +91% gross, max
drawdown -29%, and no single buy above ~$1,000 (10% of the book). TSLA
still dominates that window because a 10% position that rises 9x is
real, so the corrected concentration report now shows it. This is a
harness correctness fix, not a parameter change after seeing results
(RULE 0.8). `top_n`, rebalance cadence and scores are untouched.

## Results (post-fix re-run)

_Filled in below after the re-run._
