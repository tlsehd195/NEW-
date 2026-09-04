# ADR-0057: wire `combined_factor`/`idiosyncratic_volatility` into the walk-forward/PBO/DSR pool

**Status:** Accepted
**Session:** 36

## Context

Real raw IC results for both candidates came back from the user's own
environment (Stage 4 universe, 2010-01-01 to TEST_1.start):

| candidate | observations | mean_ic | IR | positive_ic_ratio |
|---|---|---|---|---|
| `idiosyncratic_volatility` | 79 | -0.0151 | -0.068 | 50.63% |
| `combined_factor` | 43 (vs. 79-80 for every other candidate) | -0.0530 | -0.092 | 39.53% |

Both are negative -- the opposite sign from what each was hypothesized
to predict (ADR-0053, ADR-0054). `idiosyncratic_volatility`'s result is
small enough to read as "no signal" (matching `long_term_reversal`/
`fifty_two_week_high`'s own near-zero, wrong-sign results in the
original 20-candidate screen). `combined_factor`'s result is more
striking for a second reason: its `observations=43` is well below every
other candidate's 79-80 -- a direct, structural consequence of its own
9-leg all-or-nothing missing-data rule (`piotroski_f_score` alone was
already the sparsest of the original 20 candidates at 49/80; requiring
ALL 9 legs simultaneously narrows the surviving cross-section further
still). This raises a real possibility that the negative result
reflects a narrow, non-random surviving sample (large, structurally
simple filers with complete data across 9 disparate concept sets)
rather than a genuine test of the "combining reduces noise" hypothesis
across the full universe.

## Decision -- wire both into the pool, unconditionally

Consistent with `ADR-0051`'s own explicit precedent (the user chose to
wire all 20 original candidates regardless of raw IC sign, specifically
to avoid post-hoc selection after seeing a result -- RULE 0.8), both
new candidates are wired into `run_long_horizon_validation.py`'s
`strategy_specs` pool without any sign-based or coverage-based
filtering. Making a new ad-hoc exception for these two now -- excluding
them because their raw IC looked unfavorable -- would itself be exactly
the kind of post-hoc cherry-picking RULE 0.8 exists to prevent, and
would contradict the project's own already-established rule rather than
apply it consistently.

`combined_factor`'s low-`observations` concern is real but is a
question of HOW TO READ its eventual walk-forward result (a possible
sample-selection artifact, the same class of concern the SLB/`size`
concentration finding already raised for a different candidate, worth
checking against the concentration report the same way if it reaches
`CANDIDATE`) -- not a reason to withhold it from the pool. Excluding it
now would hide the coverage problem rather than let PBO/DSR and the
existing concentration-report tooling actually surface it.

Given as a recommendation, not a unilateral decision -- the user was
asked which of 3 options to take and explicitly delegated the call
("어떻게 하는게 좋을꺼 같어?"), and this ADR's recommendation (wire
both, matching ADR-0051 precedent) was accepted.

`idiosyncratic_volatility_score` added to `_PRICE_FACTOR_CANDIDATES`
(it is a `PriceScoreFn`, same shape as `low_beta_score`/`illiquidity_
score` already in that table). `combined_factor_score` added to
`_UNIVERSE_FACTOR_CANDIDATES` (a `UniverseScoreFn`, same shape as
`quality_minus_junk_score`/`value_composite_score`) -- both tables
already existed (ADR-0051), so no new Strategy wrapper, factory
function, or loop was needed; this is purely a 2-line table addition.
The pool grows from 28 to 30 candidates.

## Tests

`tests/strategy_research/test_run_long_horizon_validation_factor_wiring.py`'s
`TestCandidateTables._EXPECTED_NAMES` updated to the 22 total names now
expected across the 4 candidate tables (20 from ADR-0051 + these 2);
its "all 20" test renamed to "all 22" for accuracy. No other test
required changes -- both new score functions already had their own
dedicated unit tests from ADR-0053/ADR-0054.

Full suite: 2253 passed (unchanged count -- pool-wiring change only, no new tests).

## What this does NOT do

- Does not change `_TOP_N_FOR_EVALUATION` or any other existing
  candidate's parameters.
- Does not run the actual walk-forward/PBO/DSR evaluation -- that still
  requires the user's own real-data environment
  (`python3 scripts/run_long_horizon_validation.py ...`), same as every
  prior candidate-pool expansion this session.
- Does not resolve the `combined_factor` coverage question -- that is
  deferred to when its actual walk-forward/concentration-report result
  is seen, per this ADR's own reasoning above.
