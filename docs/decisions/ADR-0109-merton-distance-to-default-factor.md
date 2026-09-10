# ADR-0109: Merton Distance-to-Default factor

**Status:** Accepted
**Session:** 36 (continued)

## Context

Continuing the S-tier round (ADR-0107/ADR-0108), the account owner
asked again to keep finding S-tier candidates ("더 찾아봐"), against the
same integrated criteria this session has now made explicit: (1) check
against the canonical anomaly families by name, not by keyword grep;
(2) most foundational/most-cited paper in its family; (3) genuinely
distinct construction from what this project already has; (4)
verifiable via reliable (ideally primary) sources; (5) implementable
without fabrication risk.

**Merton (1974), "On the Pricing of Corporate Debt: The Risk Structure
of Interest Rates," The Journal of Finance 29(2): 449-470** is the
foundational structural credit-risk model (equity as a call option on
firm assets) underlying the entire "distance to default" literature --
Nobel-cited work, and a genuinely different FAMILY from `altman_z_score`/
`ohlson_o_score` already in this module: those are pure
ACCOUNTING-RATIO discriminant/logit models; Merton's is a MARKET-based
structural model using price, volatility and capital structure. The
full Merton model requires iteratively solving two simultaneous
nonlinear equations for unobservable asset value and volatility -- a
numerical procedure judged too heavy for a screening-stage factor,
consistent with this project's existing "deliberate simplification"
precedents (e.g. `low_beta_score`'s single-window beta vs. the
original paper's own multi-window blend).

**Bharath & Shumway (2008), "Forecasting Default with the Merton
Distance to Default Model," The Review of Financial Studies 21(3):
1339-1369** provides the resolving simplification: a closed-form
"naive" distance-to-default that avoids the iterative solve entirely,
and which their own out-of-sample tests find predicts default AT LEAST
AS WELL as the fully-solved model -- an independently validated
substitute, not merely a shortcut. All formula components (including
the `0.05 + 0.25*sigma_E` naive debt-volatility heuristic) were
verified via WebSearch against at least two independent sources.

**Vassalou & Xing (2004), "Default Risk in Equity Returns," The
Journal of Finance 59(2): 831-868** is cited for the underlying
hypothesis that Merton-style default risk carries return-relevant
information -- honestly noted as a more nuanced, conditional result
(default risk priced mainly WITHIN small-cap/high-book-to-market
segments, interacting with size and value) than a simple univariate
factor can replicate.

## Decision

**`merton_distance_to_default_score`** (hybrid,
`(security_id, as_of_time, fundamentals_repository, price_repository, lookback_days=252)`):

```
naiveDD = [ln((E+F)/F) + (r - 0.5*sigma_V^2)*T] / (sigma_V*sqrt(T))
```

where `E` = market value of equity (`_latest_price * CommonStockSharesOutstanding`,
identical to `altman_z_score`'s own X4 construction), `F` = face value
of debt (`Liabilities`, the same simplification `altman_z_score`'s own
X4 denominator already uses), `r` = the security's own trailing 1-year
raw return, `T = 1`, and `sigma_V = (E/(E+F))*sigma_E + (F/(E+F))*sigma_D`
with `sigma_E` = trailing annualized equity volatility
(`backtest.metrics.annualized_volatility`, the same building block
`low_volatility_score` already uses) and `sigma_D = 0.05 + 0.25*sigma_E`.

Score is RAW (not negated) -- applying this module's own already-
established distress-risk-anomaly sign convention (`altman_z_score`'s:
healthier = more attractive, per Dichev 1998/Campbell-Hilscher-Szilagyi
2008), for internal consistency, not as a claim that Vassalou-Xing's
own more nuanced conditional result implies a simple monotonic
relationship on its own.

**Wired in before any real result exists (RULE 0.8)**: added to
`_HYBRID_SCORES`/`_HYBRID_FACTOR_CANDIDATES` (identical call shape to
`altman_z_score`/`size_score`). Needs zero new data: `Liabilities`/
`CommonStockSharesOutstanding` already ingested, plus ordinary price
history every other price-based factor here already uses.
`_EXPECTED_NAMES` extended from 44 to 45.

## What this does NOT do

Does not solve the full iterative Merton system for an implied asset
value/volatility (Bharath & Shumway's own finding that the naive
version performs at least as well makes this an validated choice, not
merely a convenience). Does not replicate Vassalou & Xing's own
conditional/interaction analysis (default risk priced specifically
within small-cap/high-book-to-market segments) -- this is a plain
univariate score, like every other factor in this module. Does not use
a more refined debt-maturity-weighted face value (short-term debt plus
half long-term debt, a common KMV-style refinement) -- uses total
`Liabilities` directly, the same simplification `altman_z_score`
already uses for its own X4.

## Tests

5 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestMertonDistanceToDefaultScore`). `test_run_long_horizon_validation_
factor_wiring.py`'s `_EXPECTED_NAMES` extended to 45 names. Full suite
re-run: 2713 passed (2708 pre-existing + 5 new).
