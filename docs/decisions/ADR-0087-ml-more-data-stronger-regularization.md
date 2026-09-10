# ADR-0087: ML factor-combination -- more training data + stronger regularization, wired blind

**Status:** Accepted
**Session:** 36 (continued)

## Context

The account owner's final instruction this session asked to proceed
with two directions in parallel: the insider-trading data pipeline
(ADR-0086) and "팩터 조합에 머신러닝 적용 (전에 얘기했던 '정규화 강화 +
데이터 늘리기' 방향)" -- apply ML to factor combination, specifically
the "strengthen regularization + increase data" direction discussed
earlier in this session. This ADR covers the second direction.

ADR-0043 Decision 5 already recorded a real, relevant finding: `ml_ridge`
(regularized) showed measurably better fold-consistency than `ml_ols`
(unregularized) on the same data -- 58% vs 53% positive folds -- which
that ADR's own writeup attributed to the fit having "little data."
Regularization strength and training-data volume are the two standard,
complementary responses to exactly that problem, so this ADR makes
both changes together rather than picking one.

## Decision

**More data** (`src/ml/ml_strategy.py`, `MLStrategyParameters.
train_window_months`): extended from 60 months (5 fiscal-year
fundamentals snapshots) to 84 months (7). This is the model's own
internal fit-lookback -- how far back each walk-forward fold's lazy
in-strategy fit walks to assemble its TRAIN sample set (see that
module's own docstring for why this is decoupled from
`run_walk_forward_evaluation`'s unrelated `train_window_months`
parameter). Deliberately NOT lowering `TRAIN_SAMPLE_STEP_MONTHS`
(training-sample cadence, currently 6 months) to sample more densely
within the same window instead: that module's own docstring already
establishes that fundamentals features only change once per fiscal
year, so sampling more often within an unchanged window recomputes the
same values without adding new information, for real extra fit cost --
only extending the calendar window itself adds genuinely new,
distinct historical fundamentals/price observations.

**Stronger regularization** (`src/ml/linear_model.py`,
`CANDIDATE_RIDGES`): the pre-registered ridge grid
`select_ridge_via_expanding_window_cv` searches over was widened from
`(0.001, 0.01, 0.1, 1.0, 10.0, 100.0)` to additionally include `500.0`
and `1000.0` -- extended upward only, every prior candidate value kept,
so a real prior run's chosen ridge remains reachable by the same grid.
A longer training window (the change above) can also mean more
autocorrelated, non-independent annual snapshots feeding the same fit,
which is a reasonable a priori justification for allowing a stronger
penalty to be selected if the CV search finds one helps.

Both changes decided and committed together, before either one's own
real result exists (this session's network cannot reach real data at
all) -- per RULE 0.8, neither is a response to having seen an outcome.

## What this does NOT do

Does not add new factor scores to the ML feature set (`ml.features.
FEATURE_IDS` stays at 6: `momentum`, `low_volatility`, `roe`, `roa`,
`net_margin`, `leverage`). Considered and rejected for this ADR: most
of the newer literature candidates (`asset_growth`, `piotroski`,
`sloan_accruals`, `sue`, etc.) would require reworking every ML test
fixture across `tests/ml/` to supply their additional XBRL concepts
(and, for `sue`, an entirely different quarterly-data fixture shape) --
a materially larger, separate-scope change from "more data" as
interpreted here (more historical rows for the existing feature set,
not more columns). Does not run the walk-forward pipeline against real
data -- this session's own network is blocked, same constraint every
earlier ADR this session documents. Does not change `ml_ols`'s (or
`ml_ridge`'s) `version` string despite the default parameter change --
this reproduces the exact, already-documented, deliberately-unresolved
gap ADR-0043 Decision 5 itself flagged ("this still cannot detect a
change to an EXISTING candidate's own fixed internal parameters...
while the candidate is still named `ml_ols`"); not a new problem
introduced here, and not fixed here either (out of this ADR's scope).

## Tests

`tests/ml/test_ml_strategy.py::TestParameterValidation::
test_default_train_window_is_84_months_adr_0087` (new) --
`MLStrategyParameters().train_window_months == 84`.
`tests/ml/test_linear_model.py::TestCandidateRidgesGridADR0087` (new,
3 tests) -- the two new candidates are present, every prior candidate
value is still present, and the grid stays sorted ascending. Full
`tests/ml/` suite (40 tests) and full repository suite re-run after
these changes; every pre-existing test still passes.
