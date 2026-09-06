# ADR-0108: Ohlson O-Score factor

**Status:** Accepted
**Session:** 36 (continued)

## Context

Directly continuing ADR-0107's "S-tier only" instruction, the account
owner asked to implement whichever S-tier papers are actually
implementable, or keep searching ("구현 할 수 있는 s급 논문들 구현하거나
더 찾아"). This session's earlier pass (ADR-0106, in the "가능한 많이
전략을 더 찾아봐" round) had provisionally listed **Ohlson (1980),
"Financial Ratios and Probabilistic Prediction of Bankruptcy," Journal
of Accounting Research 18(1): 109-131** as excluded, reasoning that its
`SIZE` variable needs a GNP price-level deflator this project has no
macro data source for.

Revisiting that exclusion with a NEW argument (not a result-driven
reversal -- this project has never computed a real IC for this factor,
so RULE 0.8 is not implicated): this module only ever uses a factor
score for CROSS-SECTIONAL ranking of securities at the SAME
`as_of_time` (Spearman IC against forward returns, rank-averaging,
top-N portfolio construction) -- it never compares one security's score
across two different dates. At any single date, the GNP deflator has
exactly one value, applied identically to every security scored that
day. Subtracting `-0.407 * ln(deflator)` from every security's O-score
on a given date shifts the ENTIRE cross-section by an identical
constant and therefore changes NO security's rank relative to any
other on that date. Omitting the deflator is mathematically EXACT for
this project's only use case, not an approximation -- a fundamentally
different situation from guessing a value that would actually change
relative rankings.

All 9 input variables and their published coefficients were verified
via WebSearch against at least two independent sources each (this
session's established discipline for any formula with numeric
coefficients, following the same standard already applied to
Corwin-Schultz and Harvey-Siddique) rather than reconstructed from a
34-year-old memory of the paper.

## Decision

**`ohlson_o_score`** (fundamentals-only,
`(security_id, as_of_time, repository)`):

```
O = -1.32 - 0.407*SIZE + 6.03*TLTA - 1.43*WCTA + 0.0757*CLCA
    - 1.72*OENEG - 2.37*NITA - 1.83*FUTL + 0.285*INTWO - 0.521*CHIN
```

where (using concepts already ingested for `altman_z_score`/
`roa_score`/`sloan_accruals_score`/`shareholder_yield_score`, needing
ZERO new data):
- `SIZE = ln(Assets)` (deflator omitted, see above)
- `TLTA = Liabilities / Assets`
- `WCTA = (AssetsCurrent - LiabilitiesCurrent) / Assets`
- `CLCA = LiabilitiesCurrent / AssetsCurrent`
- `OENEG = 1 if Liabilities > Assets else 0`
- `NITA = NetIncomeLoss / Assets`
- `FUTL = NetCashProvidedByUsedInOperatingActivities / Liabilities`
  (the standard modern proxy for Ohlson's own pre-cash-flow-statement-
  era "funds provided by operations," verified via WebSearch as the
  widely-used practitioner approximation)
- `INTWO = 1 if NetIncomeLoss was negative in BOTH of the two most
  recent fiscal years else 0`
- `CHIN = (NI_t - NI_{t-1}) / (|NI_t| + |NI_{t-1}|)`

Score is the NEGATIVE of the raw `O` value (higher `O` = higher
predicted bankruptcy probability = less attractive), matching this
module's convention and the same Dichev (1998)/Campbell-Hilscher-
Szilagyi (2008) distress-anomaly direction `altman_z_score` already
documents (healthier = more attractive).

**Wired in before any real result exists (RULE 0.8)**: added to
`_SCORES`/`_FUNDAMENTALS_FACTOR_CANDIDATES` (identical call shape to
every other fundamentals-only candidate, e.g. `sloan_accruals_score`).
`_EXPECTED_NAMES` extended from 43 to 44.

## What this does NOT do

Does not attempt Campbell, Hilscher & Szilagyi (2008)'s own dynamic
hazard model ("In Search of Distress Risk") -- its published logit
coefficients apply to a larger, harder-to-verify variable set (NIMTAAVG,
TLMTA, EXRETAVG, RSIZE, SIGMA, CASHMTA, MB, PRICE, several of them
exponentially-weighted trailing averages), and the fabrication risk of
misremembering or misconstructing any one of eight coefficients was
judged too high for this session to safely verify via search alone.
Does not attempt Pastor & Stambaugh (2003)'s systematic liquidity risk
factor -- its own construction needs a cross-sectional, universe-wide
aggregate liquidity innovation series (a within-month per-stock
regression, aggregated and then run through an AR(2) model), a
materially more complex piece of new infrastructure than any single-
security factor already in this module.

## Tests

6 new tests in `tests/strategy_research/test_factor_scores.py`
(`TestOhlsonOScore`). `test_run_long_horizon_validation_factor_
wiring.py`'s `_EXPECTED_NAMES` extended to 44 names. Full suite re-run:
2708 passed (2702 pre-existing + 6 new).
