# ADR-0043: ML Research Track's first model -- plain OLS, no new dependency

## Context

`docs/research/ML-RESEARCH-PROTOCOL.md` (Phase 32, Track B) specified
the ML Research Track's governance but deliberately built nothing --
"design before implementation," status `ML_RESEARCH_PARTIALLY_READY`.
Since then, 8 independently-motivated, pre-committed hypotheses have
been tested against the real 39-symbol catalog (3 price/volume, 4
fundamentals-factor ICs, `leverage` as a full walk-forward strategy --
`STRATEGY-VALIDATION-REPORT.md` Section G) and none reaches CANDIDATE.
The user, asked to choose the project's next direction, explicitly
delegated it ("프로젝트 완성에 가까워질 수 있는 방향으로 네가 진행해" --
proceed in whichever direction brings the project closer to
completion); the assistant's own recommendation, made and accepted in
that same exchange, was to begin the ML Track now: rule-based
single-factor search has produced 8 nulls/near-nulls without any
correction for the multiple-testing burden that keeps growing with
each new factor tried, whereas ML asks a genuinely different question
("do these already-computed factors carry information IN COMBINATION")
rather than repeating the same single-factor search pattern.

## Decision 1 -- model family: ordinary least squares, no numpy/scikit-learn

Per `ML-RESEARCH-PROTOCOL.md` section 13 (itself citing ADR-0039's
already-established reasoning): a dependency is added only when a
specific, justified model family is actually being implemented, never
speculatively. The feature set is 6 factor scores
(`momentum`/`low_volatility`/`roe`/`roa`/`net_margin`/`leverage`) over,
at most, a few hundred samples (39-40 symbols, annual-cadence
fundamentals) -- exactly the regime where the simplest possible model
is the correct starting point, not a compromise made for lack of a
library. Plain OLS with an intercept, fit via the closed-form normal
equations solved by pure-Python Gauss-Jordan elimination with partial
pivoting, needs no linear-algebra library at all. **No new dependency
is added by this ADR.** A regularized or nonlinear model family
remains a legitimate future step, but only as its own, separately-
justified ADR -- exactly the deferral pattern ADR-0039 already
established for portfolio-optimization libraries.

A small ridge term (`1e-6`) is added to the normal-equations diagonal
purely for numerical stability against near-collinear factor scores
(several of the 6 factors are correlated by construction -- e.g.
`roa`/`roe` both scale with profitability). This is fixed before any
data is seen and is not a tuned hyperparameter subject to model-
selection multiple-testing; it is recorded as this model's fixed
`hyperparameter_set_id`.

## Decision 2 -- what was built

Additive, new `src/ml/` package + `scripts/train_ml_model_from_catalog.py`:

- `src/ml/features.py` -- `FeatureSpec` schema (per ML-RESEARCH-
  PROTOCOL.md section 8) for the 6-feature `factor_scores_v1` set;
  `compute_feature_vector` combines price-derived scores (via
  `AsOfDataView`, reusing `LongTermMomentumStrategy._momentum_score`
  and `low_volatility_score` unchanged) and fundamentals-derived ones
  (via `DuckDBFundamentalsRepository`, reusing `roe_score`/`roa_score`/
  `net_margin_score`/`leverage_score` unchanged) into one dict --
  returns `None` (never a partially-filled vector) the moment any
  single feature is unavailable. **No imputation anywhere in this
  package** -- a sample with any missing feature is excluded entirely,
  never filled with a mean/zero/forward-fill.
- `src/ml/target.py` -- `TargetSpec` schema for `forward_return_60d`;
  `compute_target` calls `strategy_research.signal_ic.forward_return`
  directly (that function, and `summarize_ic_observations`, were
  promoted from module-private to public in this change specifically
  so this package could reuse them rather than reimplementing realized-
  return math a second time -- confirmed no other code referenced the
  private names before renaming).
- `src/ml/dataset.py` -- `build_ml_dataset` walks rebalance dates
  exactly like `compute_ic_series`/`compute_fundamentals_ic_series`
  already do (same `AsOfDataView`/`BacktestClock` construction), 
  emitting one `MLSample` per `(security_id, as_of_time)` with a
  complete feature vector AND a computable target, carrying
  `feature_available_at`/`target_period_start`/`target_period_end`
  per ML-RESEARCH-PROTOCOL.md section 4's leakage-prevention schema.
- `src/ml/linear_model.py` -- `LinearRegressionModel` (fit/predict),
  `ModelSpec` schema.
- `src/ml/evaluate.py` -- `evaluate_model_ic` applies the *exact same*
  `spearman_ic`/`summarize_ic_observations` machinery used for every
  rule-based factor's IC to a fitted model's `predict()` output instead
  -- the only fair, apples-to-apples comparison against this project's
  existing factor-IC results (e.g. `leverage`'s mean_ic=+0.0782).
- `scripts/train_ml_model_from_catalog.py` -- CLI: fits on TRAIN,
  evaluates via IC on VALIDATION, prints the full experiment-governance
  record ML-RESEARCH-PROTOCOL.md section 6 requires (`experiment_id`,
  `feature_set_id`, `target_id`, `model_family`, `hyperparameter_set_id`,
  `training_window`, `validation_window`, `random_seed=N/A`,
  `dataset_version`, `experiments_run_in_this_study=1`, and a
  `selection_reason` filled in AFTER the VALIDATION IC is computed, per
  section 7). **Deliberately never computes or reads a TEST region at
  all** -- `build_chronological_split`'s `test_start`/`test_end` are
  ignored entirely; ML-RESEARCH-PROTOCOL.md's "LOCK -> TEST (once)"
  stage is not reached by this first, exploratory model. Refuses (exit
  1, no partial output, no override flag) if `[--start, --end]`
  overlaps `strategy_research.locked_windows.TEST_1`, identical to
  every other Signal-IC/walk-forward CLI script.

37 new tests (`tests/ml/`): OLS correctness on a noiseless known
relationship, honesty about missing state (predict-before-fit,
missing-feature, empty-samples all raise rather than fabricate),
feature-vector no-imputation behavior, dataset leakage-field bookkeeping,
evaluation correctness (a perfectly rank-predictive model scores
IC=+1.0 on a 2-security synthetic fixture where that is provably
correct), and CLI wiring (TEST-1 refusal, end-to-end fit+evaluate
against synthetic catalogs, honest failure on zero usable TRAIN
samples). Full suite: 2010 passed.

## What this does NOT do

No model-selection procedure exists yet (only one candidate model
family) -- the moment a second candidate is added, ML-RESEARCH-
PROTOCOL.md section 7's multiple-comparisons correction becomes
required, not optional. No TEST evaluation, of any kind, has happened
-- this stays true until a VALIDATION result is judged good enough to
warrant it. No feature/target/model registry is persisted (schemas
only, per protocol section 8, matching the "not built until a model
exists to register" framing -- a persistence layer is a legitimate
next step, not built here to keep this ADR's footprint to exactly what
the first model needed). No risk controls (section 10) are implemented
-- this model produces a research-only IC diagnostic, never an
`OrderIntent`, and nothing in `broker/` or `risk/` is touched.
