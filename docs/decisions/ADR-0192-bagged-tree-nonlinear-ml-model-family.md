# ADR-0192: Bagged regression-tree ensemble -- the first nonlinear ML model family

**Status:** Accepted
**Date:** 2026-09-24
**Deciders:** Claude Code (session continued), account owner (asked to
pursue "새 비선형 모델 패밀리 설계/구현" -- design and implement a new
nonlinear model family, alongside executing the two already-prepared
real-data runs the account owner would run separately)

## Context

`ML-RESEARCH-PROTOCOL.md` section 13 and `src/ml/linear_model.py`'s own
module docstring both reserved a nonlinear model family as "its own
future ADR, justified only if [the first OLS model's] VALIDATION result
warrants the added complexity and dependency." That condition is now
met, in the negative: both linear families this project has tried so
far --

- `ml_ols` (plain OLS, `ADR-0043`): does not clear the walk-forward
  `CANDIDATE` fold-consistency bar (53% positive folds vs. the required
  60%, later re-run at 55% with more data -- `STRATEGY-VALIDATION-
  REPORT.md`'s "Phase 33 Addendum" and "Session 36 continued Addendum
  -- ML factor-combination").
- `ml_ridge` (CV-regularized OLS, `ADR-0043` Decision 5, further tuned
  by `ADR-0087`'s wider regularization grid + longer training window):
  also does not clear the bar (58% in one run, 53% in a later one with
  more data -- the same report's addenda).

Both failures share the same underlying assumption: a LINEAR
combination of the 6 factor scores. Neither result rules out a
non-linear combination of the identical 6 features carrying signal the
linear families cannot express -- that hypothesis has not yet been
tested.

## Decision

Add `src/ml/tree_model.py`: `RegressionTreeModel` (a single CART
regression tree, pure Python) and `BaggedTreeModel` (a small bagged
ensemble of `RegressionTreeModel`s with per-tree feature subsampling --
the standard random-forest recipe), wired into `MLStrategy` via a new
`bagged_tree_builder` (`src/ml/ml_strategy.py`) and registered as a
third `run_long_horizon_validation.py` candidate, `ml_tree`, alongside
the existing `ml_ols`/`ml_ridge`.

**No new dependency.** The same reasoning `linear_model.py` already
gives for avoiding `numpy`/`scikit-learn` applies with more force here:
this project's real per-fold TRAIN sizes are tiny (11-80 observations
across every real run recorded in `STRATEGY-VALIDATION-REPORT.md`). A
general-purpose gradient-boosting library's default hyperparameter
surface is tuned for orders of magnitude more data than this project
has; reaching for one would need its own extensive re-tuning to avoid
trivially memorizing 11-80 rows, and that re-tuning would itself be an
undisclosed multiple-comparisons risk. A hand-rolled, heavily-
regularized shallow tree ensemble is the better-justified fit for this
project's actual data regime, not a compromise.

**Hyperparameters are FIXED, not CV-searched** -- `max_depth=2`,
`min_samples_leaf` = max(3, 10% of TRAIN), `n_estimators=25`,
per-tree feature subsample size 3 (of 6 total features). This mirrors
`linear_model.py`'s own `_RIDGE = 1e-6` precedent ("NOT a tuned
hyperparameter subject to model-selection multiple-testing") extended
to the whole tree/forest shape: at N=11-80, a CV search over tree depth
or leaf size would itself have high-variance, unreliable estimates on
such a small TRAIN set, and would stack a second, undisclosed
multiple-comparisons layer on top of the walk-forward/PBO/DSR pipeline
that already treats every strategy in the candidate pool as needing
independent clearance. All five values above are recorded here, before
any real result from this model exists, per RULE 0.8.

**Determinism**: bagging requires real randomness (bootstrap
resampling + feature subsampling), unlike `ml_ols`/`ml_ridge` which are
fully deterministic given their inputs. `BaggedTreeModel` takes an
explicit `random_seed: int` (default fixed, also before any real
result exists) and uses a LOCAL `random.Random(random_seed)` instance
-- never the global `random` module state -- so `fit()` is
byte-for-byte reproducible given the same samples and seed, per
`ML-RESEARCH-PROTOCOL.md` section 9 and this project's existing
seeded-training precedent (`learning.trainer.MeanRewardBaselineTrainer
.train(..., seed=...)`).

**Everything else is unchanged and reused, not duplicated**: `MLStrategy`'s
existing lazy-per-fold-fit mechanism, leakage-safe `AsOfDataView`-backed
feature/target computation, and shared feature/target cache all apply
to `ml_tree` exactly as they already do to `ml_ols`/`ml_ridge` --
`bagged_tree_builder` only needs to satisfy the same `(Sequence[MLSample])
-> Optional[model with .predict()]` contract `MLStrategy.model_builder`
already defines. `ml_tree` goes through the identical walk-forward +
PBO/DSR pipeline as every other candidate; no new statistical machinery
is added.

## Consequences

- A genuinely different hypothesis (non-linear interaction among the 6
  factor scores) gets tested, rather than a third linear variant.
- Real overfitting risk remains, honestly acknowledged rather than
  hidden behind fixed hyperparameters: even `max_depth=2` with a 10%
  leaf floor can fit noise at N=11. The walk-forward/PBO/DSR pipeline's
  fold-consistency bar is the actual check on this, exactly as it
  already is for every other candidate -- this ADR does not claim the
  fixed hyperparameters make overfitting impossible, only that they are
  a deliberately conservative, pre-registered starting point rather
  than a search that could itself be tuned toward a good-looking
  result.
- If `ml_tree` also fails to clear `CANDIDATE`, that is a real, useful
  negative result: it would mean neither a linear nor this specific
  nonlinear combination of these 6 factor scores carries out-of-sample
  signal at this project's real data scale -- not proof no nonlinear
  model ever could, but evidence against the more modest hypothesis
  this ADR actually tests.
- No dependency-policy change; `ML-RESEARCH-PROTOCOL.md` section 13
  remains satisfied (no ML library added).

## Tests

`tests/ml/test_tree_model.py`: `RegressionTreeModel` correctness
(recovers a known threshold-split generating process on noiseless
synthetic data), non-finite feature/target rejection, empty-input
rejection, `predict()`-before-`fit()` rejection, missing-feature
rejection (mirrors every existing `LinearRegressionModel` test in
spirit). `BaggedTreeModel` reproducibility (same samples + seed ->
identical predictions; different seeds -> not required to match),
`n_trees_fit` visibility, and a degenerate-bootstrap-draw case. Full
suite run before merge as the merge gate (see PR).

## Status of Implementation at Time of This ADR

Code and tests complete for `RegressionTreeModel`/`BaggedTreeModel`,
wired into `MLStrategy` (`bagged_tree_builder`) and registered as the
`ml_tree` candidate in `run_long_horizon_validation.py`. **Not yet run
against real data** -- this sandboxed session's network egress is
blocked to every market-data/fundamentals provider (verified directly
this session, not assumed from prior documentation), so, like every
other real-data run recorded in `STRATEGY-VALIDATION-REPORT.md`, the
account owner must execute `run_long_horizon_validation.py --fundamentals-db-path
...` in their own network-enabled environment to get a real
fold-consistency/PBO/DSR result for `ml_tree`. That real run, alongside
the two other outstanding real-data runs already tracked in
`STRATEGY-VALIDATION-REPORT.md`'s "Outstanding real results not yet
received" section, is the immediate next step once the account owner's
environment is available.
