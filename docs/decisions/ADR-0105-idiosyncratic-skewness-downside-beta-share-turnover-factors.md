# ADR-0105: Idiosyncratic Skewness, Downside Beta and Share Turnover factors

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner asked to expand this project's factor pool as broadly
as possible ("일단 우리 전략을 최대한 늘리자"), continuing this session's
established literature-mining approach after ADR-0104. Rather than mine
a single external catalogue again (JKP and OpenSourceAP/CrossSection are
both already exhausted this session, per ADR-0102/ADR-0103), this round
searched directly (WebSearch) for well-known, single-paper-cited
anomalies genuinely distinct from every factor already in
`factor_scores.py`, restricted to ones computable from data this project
already ingests (`PriceBar.close/high/low/volume`,
`CommonStockSharesOutstanding`) -- needing zero new data acquisition,
zero new ADRs for data-access gaps, unlike ADR-0104's SEC Form 13F work.

Three candidates were verified via WebSearch (paper citation, exact
finding, and predicted sign) before any construction was written, per
RULE 0.8:

1. **Boyer, Mitton & Vorkink (2010), "Expected Idiosyncratic Skewness,"
   The Review of Financial Studies 23(1): 169-202** -- higher expected
   idiosyncratic skewness predicts LOWER subsequent returns (a
   1.00%/month Fama-French alpha spread between the paper's low- and
   high-skewness quintiles).
2. **Ang, Chen & Xing (2006), "Downside Risk," The Review of Financial
   Studies 19(4): 1191-1239** -- higher downside beta (covariance with
   the market conditional on the market being down) predicts HIGHER
   subsequent returns (~6%/year premium in the original US sample).
3. **Datar, Naik & Radcliffe (1998), "Liquidity and Stock Returns: An
   Alternative Test," Journal of Financial Markets 1(2): 203-219** --
   confirmed via WebSearch: "stock returns are a decreasing function of
   the turnover rates" -- share turnover (volume / shares outstanding)
   predicts LOWER subsequent returns (a liquidity premium, alternative
   proxy to Amihud & Mendelson 1986).

## Decision

**`idiosyncratic_skewness_score`** (price-only,
`(security_id, as_of_time, data: AsOfDataView, lookback_days=21)`):
reuses `idiosyncratic_volatility_score`'s own market-model residual
construction (single-factor OLS against `BENCHMARK_SYMBOL`, ~1-month
window) but takes the residuals' third standardized moment (population
skewness) instead of their standard deviation, and negates it. A
REALIZED proxy for the original paper's own cross-sectionally EXPECTED
skewness model, the same realized-for-expected substitution this
module's `max_effect_score` and `idiosyncratic_volatility_score`
already make. Distinct from both `max_effect_score` (a single-extreme-
observation statistic) and `idiosyncratic_volatility_score` (the second
moment of the same residuals) -- see its own docstring for why all
three can disagree on an individual security.

**`downside_beta_score`** (price-only,
`(security_id, as_of_time, data: AsOfDataView, lookback_days=252)`):
reuses `low_beta_score`'s own `Cov/Var` OLS beta estimator, restricted
to the subset of paired trading days where the benchmark return is
below its own trailing mean over the same window (the paper's own
"downside" definition). RAW (not negated) -- unlike `low_beta_score`,
a HIGHER downside beta is this paper's own hypothesized more-attractive
direction, the same "no negation needed" situation `illiquidity_score`
already documents. Needs at least 20 downside-day paired observations.

**`share_turnover_score`** (hybrid,
`(security_id, as_of_time, fundamentals_repository, price_repository, lookback_days=252)`):
average daily `volume / shares_outstanding` over the trailing window,
using the single latest known `CommonStockSharesOutstanding` fiscal-
year value as a constant denominator (the same simplification every
other market-cap-based factor in this module already accepts -- no
daily shares-outstanding series exists). Negated (lower turnover =
more attractive, matching the paper's own finding). A THIRD independent
liquidity proxy alongside `illiquidity_score` (Amihud 2002, price-
impact-based) and `bid_ask_spread_score` (Corwin & Schultz 2012,
range-based) -- volume-based, referencing neither dollar volume nor
price range, so all three can disagree on an individual security.

**Wired in before any real result exists (RULE 0.8)**:
`idiosyncratic_skewness`/`downside_beta` added to
`_PRICE_ONLY_SCORES`/`_PRICE_FACTOR_CANDIDATES` (needs zero new
plumbing, identical call shape to existing price-only candidates);
`share_turnover` added to `_HYBRID_SCORES`/`_HYBRID_FACTOR_CANDIDATES`
(identical call shape to `size_score`/`book_to_market_score`).
`_EXPECTED_NAMES` extended from 36 to 39.

## What this does NOT do

Does not build Boyer-Mitton-Vorkink's own cross-sectional EXPECTED-
skewness model (a full predictive regression using lagged skewness,
volume, size and book-to-market as regressors) -- uses REALIZED
skewness directly, the same simplification already applied to
`max_effect_score`/`idiosyncratic_volatility_score`. Does not use
Ang-Chen-Xing's own 5-year/60-month rolling window or their
sub-period averaging refinements -- uses `low_beta_score`'s existing
single-window estimator restricted to downside days. Does not track a
daily shares-outstanding series for `share_turnover_score` -- uses the
one latest annual XBRL value as a constant denominator across the
window, same limitation every market-cap-based factor here already has.

## Tests

10 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestIdiosyncraticSkewnessScore` 4, `TestDownsideBetaScore` 3,
`TestShareTurnoverScore` 3). `test_run_long_horizon_validation_factor_
wiring.py`'s `_EXPECTED_NAMES` extended to 39 names across 7 candidate
tables. Full suite re-run: 2685 passed (2675 pre-existing + 10 new).
