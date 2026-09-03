# ADR-0051: Wire all 20 raw-IC-screened candidates into the walk-forward/PBO/DSR pool

**Status:** Accepted
**Session:** 36

## Context

Session 36 ran raw Signal IC checks for 20 literature-sourced factor
candidates (see PROJECT_STATUS.md's "raw IC 스크리닝 20개" table) --
6 price/volume-only, 14 fundamentals-dependent (5 fundamentals-only, 7
needing both fundamentals and price data, 2 cross-sectional
composites). 9 of 20 showed the sign the underlying literature predicts
(every `factor_scores.py` score is already constructed so a higher
score should predict a higher forward return); 11 did not, or were
effectively zero.

The question this ADR answers: which of the 20 get wired into
`run_long_horizon_validation.py`'s walk-forward/PBO/DSR pool -- the
expensive, real evaluation stage every candidate must go through before
its evidence can be trusted at all (raw IC is a cheap screen, never a
verdict; see `docs/research/STRATEGY-VALIDATION-REPORT.md` Section G).

Two options were on the table: (a) only the 9 candidates whose raw IC
sign matched the literature's prediction, or (b) all 20. The user chose
(b) explicitly, after being shown that this project's own history
already answers the underlying methodology question: `leverage`'s raw
IC (mean_ic=+0.0782) was weaker than `ml_ols`'s (mean_ic=+0.1055,
ADR-0043 Decision 3), yet `ml_ols` had the second-worst walk-forward
fold-consistency of 6 candidates while `leverage` passed
(`docs/research/STRATEGY-VALIDATION-REPORT.md` Section G, "Sixth
update"). Raw IC sign/magnitude has not reliably predicted walk-forward
robustness in either direction in this project's own real results --
filtering the pool by raw IC now, after seeing it, would be exactly the
post-hoc selection RULE 0.8 prohibits, dressed up as a "principled"
cutoff.

## Decision

### 1. Four generic `Strategy` wrappers, not 20 near-duplicate files

`src/strategy_research/leverage_strategy.py` and
`src/strategy_research/ensemble_strategy.py` already show what
one-off-per-candidate files look like at just 2 copies (~35 lines of
identical rank/rebalance/order-construction logic, copy-pasted). Scaling
that to 20 would be pure duplication with no informational value, so
`src/strategy_research/factor_strategy.py` (new) instead defines 4
generic wrappers matching `factor_scores.py`'s 4 existing score_fn call
shapes:

- `PriceFactorStrategy` -- `score_fn(security_id, as_of_time, data: AsOfDataView)`.
  No injected repository; `data` is the same `AsOfDataView`
  `generate_orders` already receives.
- `FundamentalsFactorStrategy` -- `score_fn(security_id, as_of_time, fundamentals_repository)`.
  Same shape `LeverageStrategy` already hardcodes to `leverage_score`,
  generalized.
- `HybridFactorStrategy` -- `score_fn(security_id, as_of_time, fundamentals_repository, price_repository)`.
  Needs the RAW, point-in-time-safe price repository (its own
  `get_bars(..., as_of_time=...)`) injected via the constructor --
  `AsOfDataView.get_bars` takes no `as_of_time` kwarg (it IS the
  point-in-time guard, applied once at construction), so it cannot
  serve this role. This mirrors `signal_ic.compute_hybrid_ic_series`'s
  identical reasoning.
- `UniverseFactorStrategy` -- `score_fn(security_ids, as_of_time, fundamentals_repository, price_repository) -> dict`.
  For `quality_minus_junk_score`/`value_composite_score`, called once
  per rebalance with the whole universe.

All four share one order-construction helper (`_orders_from_target`),
byte-identical to `LeverageStrategy.generate_orders`'s own logic: sell
anything dropping out of the new top-N target, equal-weight-buy
anything newly entering, `COST_SAFETY_MARGIN` cash headroom,
`None`-scored securities excluded from ranking rather than fabricated.
`LeverageStrategy`/`RankAverageEnsembleStrategy` themselves are left
untouched -- already tested and running, not worth a stylistic-only
refactor's regression risk.

### 2. Wiring in `run_long_horizon_validation.py`

4 module-level tables (`_PRICE_FACTOR_CANDIDATES`,
`_FUNDAMENTALS_FACTOR_CANDIDATES`, `_HYBRID_FACTOR_CANDIDATES`,
`_UNIVERSE_FACTOR_CANDIDATES`) list `(name, hypothesis, score_fn)` for
each of the 20; 4 small factory functions
(`_price_factor_factory`/`_fundamentals_factor_factory`/
`_hybrid_factor_factory`/`_universe_factor_factory`) each take the
runtime values (`security_ids`, `fundamentals_repository`,
`repository`) as explicit parameters and return a zero-arg closure --
deliberately NOT built with a `lambda` directly inside the `for` loop
that iterates each table, which would be Python's classic late-binding
closure bug (every lambda ending up bound to the loop's FINAL value,
not its own). The 6 price-only candidates are appended to
`strategy_specs` unconditionally (they need no fundamentals catalog);
the remaining 14 are appended inside the SAME
`if fundamentals_repository is not None:` guard `leverage`/`ml_ols`/
`ml_ridge`/`rank_average_ensemble` already use -- omitted entirely,
every other candidate unaffected, when `--fundamentals-db-path` is not
supplied. A run with that flag now evaluates 28 candidates total (was
8); without it, 10 (was 4).

### 3. Why raw IC screening results are not used to exclude anyone here

See Context above. No candidate's inclusion depended on its raw IC
value. This ADR's own existence -- built specifically to remove the
temptation to cherry-pick after seeing a screening result -- is itself
downstream of RULE 0.8, not an exception to it.

## Tests

- `tests/strategy_research/test_factor_strategy.py` (new, 11 tests):
  each of the 4 wrapper classes, using small fake score_fns (isolating
  "does the wrapper rank/rebalance/order correctly" from any real
  factor's own hypothesis) -- top-N selection, rebalance cadence,
  `None`-score exclusion, deterministic replay, parameter validation.
  Mirrors `test_leverage_strategy.py`'s exact structure.
- `tests/strategy_research/test_run_long_horizon_validation_factor_wiring.py`
  (new, 7 tests): imports the script module (like
  `test_compute_fundamentals_ic_from_catalog_cli.py`/
  `test_train_ml_model_from_catalog_cli.py` already do for other CLI
  scripts) to call the real `_*_factory` functions the way `main()`'s
  loops actually call them, and asserts each resulting strategy is
  bound to ITS OWN score_fn/version -- the concrete, behavioral
  regression test against the late-binding bug AST/source-text matching
  cannot catch. Also verifies the 4 candidate tables reproduce exactly
  the 20 expected names with no collisions against each other or the 8
  pre-existing candidates.
- `tests/strategy_research/test_run_long_horizon_validation_wiring.py`
  (+3 tests, `TestAdr0051CandidateLoopsGatedCorrectly`): AST/source-text
  placement checks -- the price-factor loop is unconditional, the other
  3 loops sit inside the fundamentals guard, the new imports are
  present. Same never-import-never-call-main() discipline this file's
  own docstring already established.

Full suite: 2213 passed (up from 2192; 11 + 7 + 3 = 21 new tests).

## What this does NOT do

- Does not run any real walk-forward/PBO/DSR evaluation itself -- this
  environment's network access remains blocked (unchanged since Phase
  20); the user must run `run_long_horizon_validation.py
  --fundamentals-db-path ...` in their own environment and relay the
  report.
- Does not change `PBO`/`DSR` computation logic (`pbo_dsr.py`) --
  CSCV combinatorics scale with fold count, not candidate count, so
  the existing implementation handles a 28-candidate pool without
  modification (confirmed by reading `compute_pbo`'s implementation,
  not assumed).
- Does not change any candidate's `CandidateModelStatus`/
  `CandidateClassification` -- every one of the 28 candidates remains
  `INCONCLUSIVE` until a real run produces evidence, same as every
  candidate before this ADR.
- Does not touch `leverage_strategy.py`/`ensemble_strategy.py` --
  left as-is despite now being stylistically superseded by
  `factor_strategy.py`'s generic wrappers, to avoid regression risk on
  already-tested, already-running code for a purely cosmetic gain.
