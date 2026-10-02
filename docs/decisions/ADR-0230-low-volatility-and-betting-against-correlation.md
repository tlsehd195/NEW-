# ADR-0230: Two new price-only candidates in place of the held-back short_interest, guru_consensus and alpha101

**Status:** Accepted (done 2026-10-02: low_volatility FAIL on its held-out TEST; window locked as TEST_5)
**Date:** 2026-10-02
**Deciders:** account owner (asked for a new candidate test, then picked "two new price factors" on a decision card, 2026-10-02), Claude Code session

## Context

ADR-0228 ended with no candidate beating a same-names buy-and-hold out of
sample. The account owner asked to test new candidates. The 2026-10-01
ADR sweep had listed three built-but-never-validated ones, and none of
them can be tested meaningfully in the open research window
(2000-01-01..2013-03-21, ADR-0228):

- **short_interest** (ADR-0099/0125): the only real short-interest data
  this project has seen is FINRA's API, with a 2018 sample. No free
  source for 2000-2013 is known (inferred, not exhaustively checked).
- **guru_consensus** (ADR-0194): SEC's structured Form 13F data sets
  start with 2013 Q3, so they barely overlap the window.
- **alpha101** (ADR-0190): the ten Kakushadze alphas are day-scale
  signals. `factor_strategy` rebalances every 1-3 months, so the signal
  is gone long before a rebalance. Trading them daily with $10,000 and
  $1 per order would cost roughly half the capital a year (rough
  estimate: about 20 orders a day).

## Decision

Two price-only candidates from the low-risk literature, both untested in
any validation report, are added to `_PRICE_FACTOR_CANDIDATES` in
`scripts/run_long_horizon_validation.py`:

1. **low_volatility**: the existing `factor_scores.low_volatility_score`
   (negative 6-month daily volatility; Ang, Hodrick, Xing & Zhang 2006;
   Blitz & van Vliet 2007). It already existed but was never wired in.
2. **betting_against_correlation**: new
   `factor_scores.betting_against_correlation_score`, from Asness,
   Frazzini, Gormsen & Pedersen (2020). The score is the negative
   correlation with SPY of overlapping 3-day log returns over up to 5
   years, with at least 3 years required. The paper's volatility-quintile
   double sort needs the whole universe at once, so it is not
   reproduced; the docstring says so.

Both were fixed before any result was seen (RULE 0.8). They run with the
other 22 price candidates, so PBO/DSR count 24 trials.

Test plan, fixed now:

- Screen: point-in-time S&P 500 (release
  `research-price-catalog-sp500-pit-2000`), 2000-01-01..2013-03-21,
  walk-forward only (`--skip-held-out`).
- A new candidate becomes a finalist only by the ADR-0228 rule:
  against the cost-free same-names buy-and-hold, (a) median fold lead
  above 0, (b) more than half the folds ahead, (c) chained folds
  compounding above it.
- A finalist then takes the held-out TEST of this range once
  (`final_exam_candidates`), judged by `verdict_vs_buy_and_hold`. If it
  passes, it takes one of the unused ADR-0225 unseen-names exams
  (TEST-2, then TEST-1).

## Consequences

- If neither new candidate clears the finalist rule, no held-out window
  is spent.
- `short_interest`, `guru_consensus` and the `alpha101` module stay in
  the code, unwired.
- Tests: `tests/strategy_research/test_factor_scores.py::TestBettingAgainstCorrelationScore`.

## Result (2026-10-02)

- Screen (24 candidates, 522 point-in-time names with prices,
  2000-01..2013-03-21, held-out skipped, PBO 0.386):
  `low_volatility` cleared the finalist rule (median fold lead +0.32%,
  53% of folds ahead, chained folds 7.7% vs buy-and-hold 5.0%, DSR
  0.62). `betting_against_correlation` did not (exactly 50% of folds
  ahead).
- Held-out TEST, run once for `low_volatility` only (run 36959031646,
  `docs/research/reports/full-validation-20261002T041800Z.json`,
  2010-07-29..2013-03-21): **FAIL**. Net CAGR 13.3% vs the same-names
  cost-free buy-and-hold's 16.1%. Its net Sharpe was higher (1.28 vs
  0.94, max drawdown -9.8% vs -20.4%), but a pass needs both higher.
  SPY CAGR over the window was 16.5%.
- The window is locked as `TEST_5`. The open research window is now
  2000-01-01..2010-07-29, which leaves no room for fundamentals-based
  candidates (their catalog starts in 2010). The workflow's default
  range is now 2000-01-01..2010-07-29. TEST-2 and TEST-1 unseen-names
  exams stay unused.
