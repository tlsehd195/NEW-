# ADR-0107: Coskewness factor

**Status:** Accepted
**Session:** 36 (continued)

## Context

Continuing this session's factor-pool expansion (ADR-0105/ADR-0106),
the account owner asked specifically for top-tier, canonical papers
this time ("전략 더 찾아봐 논문쪽에서 s급이라 판단되는 것들로" -- find more
strategies, from papers judged to be "S-tier"), rather than the long
tail of single-paper anomalies mined so far. Most genuinely canonical,
most-cited asset-pricing papers are already represented in this
module's 42 existing factors (Fama-French value/size, Carhart/Jegadeesh-
Titman momentum, Sloan accruals, Piotroski F-Score, Novy-Marx
profitability, Asness-Frazzini-Pedersen QMJ, Frazzini-Pedersen BAB,
Ang-Hodrick-Xing-Zhang idiosyncratic volatility, Amihud illiquidity,
Datar-Naik-Radcliffe turnover, Ang-Chen-Xing downside risk, and more).

**Harvey & Siddique (2000), "Conditional Skewness in Asset Pricing
Tests," The Journal of Finance 55(3): 1263-1295** is a genuinely
distinct, extremely highly-cited ("S-tier") paper not yet covered:
investors with non-increasing absolute risk aversion prefer positive
portfolio skewness, so a stock whose returns covary NEGATIVELY with the
market's own squared excess return (negative coskewness -- it worsens
portfolio skewness) commands a return premium; positive coskewness
commands a valuation premium and thus a lower subsequent return. The
formula was verified against a primary source (the paper's own
author's institutional page, people.duke.edu/~charvey) rather than
reconstructed from memory alone, per this session's established
citation-verification discipline:

```
CSK_i = E[e_i * e_m^2] / sqrt(Var(e_i) * Var(e_m))
```

where `e_i`/`e_m` are the security's and the benchmark's own demeaned
excess returns over the window (population, not sample, moments,
matching the primary source's own `1/T` normalization).

## Decision

**`coskewness_score`** (price-only,
`(security_id, as_of_time, data: AsOfDataView, lookback_days=252)`):
computes the verified `CSK_i` formula above using daily returns over
the trailing `lookback_days` (default 252, ~1 trading year) -- a
deliberate simplification of the original paper's own monthly-returns/
multi-year-window estimator, the same daily-proxy simplification
`low_beta_score`/`downside_beta_score` already make for their own
market-co-movement estimators. Needs zero new data (reuses the exact
security/benchmark-bars-and-common-dates plumbing every other
price-only factor in this module already uses).

Score is the NEGATIVE of `CSK_i` (higher score = more negative
coskewness = more attractive, matching this module's convention and the
paper's own "negative coskewness earns a higher return" finding).
`None` unless at least 20 paired daily observations exist with non-zero
variance in both series.

**A genuinely different construct from every other risk factor already
in this module**: `low_beta_score`/`downside_beta_score` are LINEAR
co-movement with the market (Cov/Var, first moment); `idiosyncratic_
skewness_score` is the shape of a security's own residual distribution
in isolation (no market co-movement information at all); this factor is
co-movement between a security's own returns and the market's SQUARED
excess return -- a third-moment cross term distinct from all of the
above, so it can and does disagree with every other risk factor here on
an individual security.

**Wired in before any real result exists (RULE 0.8)**: added to
`_PRICE_ONLY_SCORES`/`_PRICE_FACTOR_CANDIDATES` (needs zero new
plumbing, identical call shape to every other price-only candidate).
`_EXPECTED_NAMES` extended from 42 to 43.

## What this does NOT do

Does not use the original paper's own monthly-returns/multi-year
rolling window -- uses daily returns over a 1-year window instead, the
same simplification this module already applies elsewhere. Does not
attempt the paper's own long-short coskewness FACTOR construction
(a cross-sectional, Fama-French-style zero-cost hedge portfolio) --
this is a per-security signal only, consistent with every other factor
in this module.

## Tests

3 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestCoskewnessScore`). `test_run_long_horizon_validation_factor_
wiring.py`'s `_EXPECTED_NAMES` extended to 43 names. Full suite re-run:
2702 passed (2699 pre-existing + 3 new).
