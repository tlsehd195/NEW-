# ADR-0053: `idiosyncratic_volatility_score` -- a new candidate from a fresh literature search

**Status:** Accepted
**Session:** 36

## Context

After Session 36's 20-candidate raw IC + walk-forward/PBO/DSR pipeline
concluded with no `VALIDATED` candidate (`docs/research/
STRATEGY-VALIDATION-REPORT.md`'s "Phase 33 Addendum"), the user asked
to search current literature/the internet for further S-tier candidates
-- before seeing any new result, matching this project's established
literature-first discipline (RULE 0.8).

## What was searched, and why the others were rejected

Real web searches (not solely training-data recall) were run for:
current factor-zoo surveys of the most-replicated anomalies, the
idiosyncratic volatility anomaly specifically, post-earnings-
announcement drift (PEAD/SUE), and whether documented anomalies hold up
specifically in large-cap-only universes (this project's own
`RESEARCH_UNIVERSE_STAGE3` is 63 large/mega-cap names only, structurally
different from most academic samples that span the full market-cap
range).

**Rejected candidates and why, decided BEFORE building anything (no
candidate below was excluded for a reason discovered by testing it):**

- **PEAD/SUE (Bernard & Thomas 1989)**: historically "the most
  replicated anomaly in finance," but current research specifically
  finds it "began disappearing from non-microcap stocks around 2001 and
  was essentially zero for large-cap stocks by 2006" -- directly
  contradicts the one property (works in mega-cap universes) this
  project's own universe needs. Not built.
- **Momentum, large-cap growth (2023-2024 factor performance
  coverage)**: recent (2023-2024) strong mega-cap momentum performance
  found in searches is exactly the kind of "chase recent performance"
  signal RULE 0.8 exists to guard against, and this project's own real
  IC for momentum in this exact universe/period is already measured at
  effectively zero (`mean_ic=-0.0078`, `STRATEGY-VALIDATION-REPORT.md`
  Section G) -- re-testing the same already-null hypothesis under a
  "but it's popular right now" justification would not be literature-
  first reasoning.
- **Size, quality, investment/asset-growth, profitability, momentum**
  (the "seven robust factors" a 2024-2025 152-anomaly global ML study
  names): all already tested this project's own real data this
  session, all null or contradicted (see the Phase 33 Addendum). A
  useful, independently-found confirmation search turned up: the size
  premium specifically has been documented as reversed for roughly the
  last decade, and disproportionately so among the largest stocks --
  plausible context for, though not proof of, this project's own null
  `size` finding, noted here as background, not used to justify
  anything.

**Selected: idiosyncratic volatility (Ang, Hodrick, Xing & Zhang 2006,
"The Cross-Section of Volatility and Expected Returns," The Journal of
Finance 61(1): 259-299)**. High idiosyncratic (stock-specific,
non-market) volatility predicts LOWER subsequent returns. Confirmed via
search to be a well-cited, extensively-replicated anomaly (robust once
microcaps/penny stocks/January are excluded -- none of which apply to
this project's mega-cap universe or annual-rebalance design) and,
critically, genuinely distinct in construction from every low-risk
factor already in this codebase:

- `low_volatility_score` (existing): TOTAL trailing volatility, no
  market decomposition.
- `low_beta_score` (existing): systematic co-movement with the market
  ALONE (covariance-based), says nothing about how much of a security's
  own variance is left over.
- `idiosyncratic_volatility_score` (new): the RESIDUAL, stock-specific
  volatility left over AFTER a security's co-movement with the market
  is regressed out -- a security can score differently on all three
  simultaneously.

## Decision

`idiosyncratic_volatility_score` added to `src/strategy_research/
factor_scores.py`, matching the `PriceScoreFn` shape (price-only, no
fundamentals). Reuses `low_beta_score`'s exact `Cov/Var` OLS beta
estimator (no new math primitive), extended to also compute the OLS
intercept and the residual standard deviation. Deliberately matches
the original paper's own trailing ONE-MONTH window (`lookback_days=21`)
rather than a longer, more-stable-but-less-faithful window, and
regresses against the market alone (no SMB/HML control, since this
project has no independently-constructed size/value factor series to
regress against) -- both simplifications stated explicitly, the same
discipline `low_beta_score`'s own docstring already established for
its own simplification versus the original paper's blended estimator.

Wired into `scripts/compute_signal_ic_from_catalog.py` (`--strategy
idiosyncratic_volatility`) so the user can run its raw IC exactly like
every other price-only candidate this session. **Deliberately NOT yet
wired into `run_long_horizon_validation.py`'s walk-forward/PBO/DSR
pool** -- unlike the 20 candidates ADR-0051 wired as one already-decided
batch, this is a single, freshly-discovered candidate; raw IC comes
first, matching this project's standing default process, before any
decision about pool inclusion (which may still end up being "wire it
regardless of the raw IC result," per ADR-0051's own precedent -- that
decision is not made by this ADR).

## Tests

5 new tests: `tests/strategy_research/test_factor_scores.py`
(`TestIdiosyncraticVolatilityScore`, 4 -- a security perfectly explained
by beta has ~0 idiosyncratic volatility regardless of its beta value;
two securities with identical beta but different injected idiosyncratic
noise are correctly ranked; insufficient paired history and missing
benchmark data both return `None`) and
`tests/strategy_research/test_compute_signal_ic_from_catalog_cli.py`
(1 new end-to-end test against a real DuckDB catalog, mirroring
`low_beta`'s own SPY-reachability regression guard). Full suite: 2218
passed (up from 2213).

## What this does NOT do

- Does not wire the new candidate into the walk-forward/PBO/DSR pool --
  that is a separate decision after raw IC is seen (see Decision above).
- Does not build PEAD/SUE, momentum, or any of the other searched-and-
  rejected candidates -- see "What was searched" above for why each was
  rejected before building anything.
- Does not add any new dependency -- pure-stdlib OLS math, identical to
  `low_beta_score`'s existing approach.
