# ADR-0230: Two new price-only candidates in place of the held-back short_interest, guru_consensus and alpha101

**Status:** Accepted
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
