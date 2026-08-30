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

## Decision 3 -- real VALIDATION result received; built into a strategy through the same rigor `leverage` went through; a real performance issue found and fixed along the way

The user ran `scripts/train_ml_model_from_catalog.py` against the real
39-symbol catalogs and relayed:

```
training_window=[2010-01-04, 2019-12-23) train_samples=810 (real run: 805, PILOT_UNIVERSE smoke test: 810)
validation_window=[2019-12-29, 2021-08-28)
VALIDATION observations=11
VALIDATION mean_ic=0.1055
VALIDATION ic_information_ratio=0.41036483171008087
VALIDATION positive_ic_ratio=81.82%
```

This is the strongest raw signal-quality metric this project has
produced across every hypothesis tested to date (mean_ic, IR, and
positive-ratio all exceed `leverage_score`'s own raw IC). **It must be
read with at least as much caution as that earlier result, for
additional reasons specific to this one**:

1. **Only 11 VALIDATION observations** -- far fewer than any prior IC
   result here (`leverage_score`'s own 80 observations, for
   comparison). With this few, non-independent (overlapping 60-day
   forward-return windows), dates, both the point estimate and its
   apparent stability (IR) carry very little statistical weight.
2. **The VALIDATION window (2019-12-29..2021-08-28) is dominated by
   the COVID crash and recovery** -- an extreme, historically unusual
   regime. A correlation this strong here could reflect that one
   macro event rather than a persistent structural relationship.
3. **This is genuinely the first, single, pre-registered experiment**
   (favorable point, unlike a result found after trying many models)
   -- but the fitted coefficients contain a sign flip worth flagging:
   `leverage`'s own raw univariate IC is positive, yet its coefficient
   in the fitted model is slightly negative, plausibly a multicollinearity
   artifact among the profitability-related features (`roe`/`roa`/
   `net_margin`/`leverage` all move together to some degree) rather
   than a real, opposite-signed effect once the other 5 features are
   held fixed.

**Consistent with how `leverage_score`'s own raw IC lead was handled**
(ADR-0042 Decisions 13/14): this must go through the same walk-forward
+ PBO/DSR pipeline before being trusted, not accepted on the raw
VALIDATION number alone. Built `src/ml/ml_strategy.py` --
`MLStrategy`, a 6th strategy candidate, wired into
`run_long_horizon_validation.py`'s `strategy_specs` behind the same
`--fundamentals-db-path` gate as `leverage` (no new CLI argument).

**The one genuinely new architectural problem this required solving**:
`run_walk_forward_evaluation` calls a zero-argument
`strategy_factory: Callable[[], Strategy]` once per fold and never
tells the returned instance that fold's own train/test boundaries --
every existing strategy tolerates this because none of them fit
anything. `MLStrategy` fits itself LAZILY, on its first
`generate_orders` call within a fold, walking backward from that
call's own `as_of_time` (which IS the fold's `test_start`) by
`train_window_months` -- reconstructing exactly that fold's own TRAIN
region with zero fold-boundary plumbing added to `walk_forward_
evaluation.py`, mirroring how `LongTermMomentumStrategy`'s own 12-month
lookback already "automatically sees genuine train-period history the
moment the test window's first checkpoint fires" (that module's own
docstring). Leakage safety: every training sample's target must be
fully realized by the live `as_of_time` the fit runs at
(`training_date + horizon_days <= as_of_time`), so every query the fit
issues has `end <= as_of_time` -- strictly narrower than what
`AsOfDataView` already guarantees, not a new or separate guard. Target
computation duplicates (does not call) `strategy_research.signal_ic.
forward_return`'s few lines of math against `AsOfDataView`'s narrower
interface instead of the raw `DataRepository` that function expects --
reusing it directly would require `MLStrategy` to hold a raw repository
reference, which would itself violate `AsOfDataView`'s own stated
central invariant ("no method, override, or parameter through which a
well-behaved Strategy implementation could request data beyond the
clock's current checkpoint").

**A real performance problem, found by actually running it, not
assumed**: a first manual smoke test against a small synthetic
catalog (5 symbols, 84 walk-forward folds) did not complete within 240
seconds -- `MLStrategy` refits from scratch at every fold's first
checkpoint, and walk-forward evaluations routinely have 70-100+ folds.
Profiled directly: one fit cost ~2.05s for 5 symbols at the original
design (`train_window_months=60`, training-sample cadence tied to
`rebalance_months=3`). Fixed by (1) decoupling the internal
training-sample cadence from the live rebalance cadence into a fixed
`TRAIN_SAMPLE_STEP_MONTHS=6` (fundamentals are FY-only -- sampling
every 3 months recomputes the same annual fundamentals value 4x over
for no new information) and (2) reducing `train_window_months` from 60
to 36 (3 years still covers 3 distinct fiscal-year snapshots). Re-profiled
after both changes: ~0.86s/fit for 5 symbols (2.4x faster); the same
84-fold, 5-symbol, 6-candidate smoke test then completed in 1m46s. Also
added per-strategy progress printing (`Evaluating strategy: {name}
...`, `flush=True`) to `run_long_horizon_validation.py`'s main loop --
`ml_ols` is now measurably the slowest candidate to evaluate, and a
long silent wait would repeat the exact "looks hung" UX problem this
project already hit once with `ingest_fundamentals_data.py`.

8 new tests (`tests/ml/test_ml_strategy.py`): fits and correctly ranks
the stronger synthetic uptrend security, rebalance cadence, deterministic
replay, and two honesty checks (no fundamentals data to fit on; backtest
starts too early in history to fit) both return zero orders rather than
a fabricated fallback. 2 new wiring tests
(`TestMLStrategyOptionallyIncluded`) confirm the same fundamentals-gated
inclusion pattern as `leverage`. Full suite: 2020 passed.

Not yet run against the real 39-symbol catalog through the full
walk-forward + PBO/DSR pipeline -- that real run, and whether `ml_ols`
clears the CANDIDATE fold-consistency bar `leverage` itself just
missed, is the immediate next step.

## Decision 4 -- real walk-forward result: `ml_ols` has the SECOND-WORST fold-consistency of all 6 candidates, despite by far the strongest raw VALIDATION IC

The user ran `run_long_horizon_validation.py` with `--fundamentals-db-path`
against the real 39-symbol catalogs (`--start 2010-01-01 --end
2023-04-28`) and relayed the real result:

```
PBO: 12.86% across 70 CSCV splits (6 candidates)

buy_and_hold:              42% positive folds (60 folds) -- below 60% bar. TEST net cumret=+20.16% sharpe=0.38
ml_ols:                     53% positive folds -- below 60% bar. TEST net cumret=+55.59% sharpe=0.57, DSR=0.9999
long_term_momentum:        57% positive folds -- below 60% bar. TEST net cumret=+16.81% sharpe=0.37
risk_controlled_momentum:  57% positive folds -- below 60% bar. TEST net cumret=+8.70% sharpe=0.32
leverage:                  57% positive folds -- below 60% bar. TEST net cumret=+33.56% sharpe=0.54
trend_volatility:          60% positive folds -- clears the bar, but DSR=0.9398 < 0.95 (FAILED). TEST net cumret=+0.13% sharpe=0.27
```

**`ml_ols` does NOT clear the CANDIDATE fold-consistency bar (53%
positive folds vs. the required 60%)** -- and its 53% is the
SECOND-WORST of all 6 candidates, beating only `buy_and_hold`'s 42%,
despite `ml_ols` producing by far the strongest raw VALIDATION Signal
IC of anything this project has tested (mean_ic=+0.1055 vs.
`leverage_score`'s own +0.0782). This is the multiple-testing/
robustness caution from Decision 3 playing out for a second time, more
starkly than for `leverage` itself: a promising raw metric not only
failed to confirm as a robust walk-forward edge, it underperformed on
that specific robustness measure relative to several strategies whose
own raw Signal ICs were null.

**A genuine tension worth naming rather than glossing over**: `ml_ols`
also produced the BEST held-out TEST performance of all 6 candidates
(+55.59% net, sharpe=0.57, versus `leverage`'s +33.56% and
`buy_and_hold`'s +20.16%). Per this project's own established reading
of exactly this pattern (`STRATEGY-VALIDATION-REPORT.md`'s "PBO/DSR
vs. held-out TEST divergence" section, first raised for
`risk_controlled_momentum`'s own case): a strong single-window TEST
result paired with weak walk-forward fold-consistency is evidence the
TEST-window result is plausibly regime-specific luck rather than a
confirmed, structurally robust edge -- fold-consistency, not one
window's return, is what this project's own CANDIDATE bar is built to
measure for exactly this reason. Per RULE 0.8, this TEST observation
cannot be used to retune or re-select `ml_ols` (or anything else) now
that it has been seen.

`REAL_VALIDATION_NOT_COMPLETED` remains the correct classification for
all 6 candidates. Across every hypothesis this project has now tested
against real data -- 3 price/volume Signal ICs, 4 fundamentals-factor
Signal ICs, `leverage` as a full strategy, and now `ml_ols` as a full
strategy -- zero have reached CANDIDATE. See `STRATEGY-VALIDATION-
REPORT.md` Section G's "Sixth update" for the full account.

## Decision 5 -- performance/robustness follow-ups, all self-initiated after the user asked what this project's own discipline was costing in efficiency

Asked directly whether this project's own rules were blocking a more
effective approach, the assistant identified five candidate
improvements and ranked them by expected impact: universe breadth,
regularization, a feature-computation cache (enabling a longer,
statistically-preferable training window), rank-based ensembling, and
quarterly fundamentals. The user asked for all five to be executed.
Three are buildable without new real data and were built in this round;
two (universe breadth, quarterly fundamentals) require new real
ingestion in the user's own network-enabled environment and are
scoped, not built, here.

**Shared feature/target cache** (`src/ml/ml_strategy.py`): a fresh
`MLStrategy` instance is created per walk-forward fold, so an
instance-level cache alone buys nothing -- the real cost was many
different folds' heavily-overlapping `train_window_months`-back TRAIN
windows recomputing the identical `(security_id, as_of_time)`
feature/target value repeatedly. Every such value is a pure function of
`(security_id, as_of_time)` and this run's own read-only repository
content, so a caller MAY inject one shared `dict` pair across every
fold's factory call and every MLStrategy-based candidate (`ml_ols` and
`ml_ridge` consume identical feature/target values regardless of model
family) with zero change in output -- verified directly: a shared-
cache run and an uncached run produce byte-identical fills. This
recovered enough headroom to revert `train_window_months` from 36 back
to 60 (Decision 3's number was a stopgap for a since-fixed performance
problem, not a statistically preferred choice) -- a full 8-candidate
smoke test (buy_and_hold, long_term_momentum, trend_volatility,
risk_controlled_momentum, leverage, ml_ols, ml_ridge,
rank_average_ensemble; 5 synthetic symbols, 84 folds) completed in 55
seconds, faster than the 6-candidate, 36-month-window run before this
change (1m46s).

**Ridge-regularized second model family** (`ml_ridge`,
`src/ml/linear_model.py`'s `select_ridge_via_expanding_window_cv`):
motivated directly by a real observed problem, not speculatively --
`ml_ols`'s fitted `leverage` coefficient came back negative despite a
positive raw univariate Signal IC, plausibly multicollinearity among
the correlated profitability features. The regularization strength is
chosen from a small, pre-registered, log-spaced grid
(`CANDIDATE_RIDGES = (0.001, 0.01, 0.1, 1.0, 10.0, 100.0)`) via
EXPANDING-WINDOW chronological cross-validation on each fold's own
TRAIN samples only -- never a random k-fold split, which would let
temporally-adjacent, autocorrelated samples inflate the out-of-fold
error estimate's apparent reliability, mirroring this project's own
`build_chronological_split` discipline. `MLStrategy` was generalized to
accept a pluggable `model_builder` so this and any future model family
reuse the identical leakage-safe, lazily-per-fold-fit mechanism without
duplicating it.

**Rank-average ensemble** (`rank_average_ensemble`,
`src/strategy_research/ensemble_strategy.py`): a genuinely different,
nonparametric combination technique from `ml_ols`/`ml_ridge`'s fitted
regression -- averages the ranks of `leverage_score` and
`net_margin_score` (the only two factors in this project's history
with a positive raw Signal IC), needing no fitting and no
leakage-safety machinery of its own (every score is computed fresh at
the live `as_of_time`, exactly like `LeverageStrategy` already does).
`strategy_research.signal_ic._rank` was promoted to public
`rank_average` specifically so this module could reuse it rather than
reimplementing rank computation a second time (confirmed no other
caller depended on the private name before renaming).

All three are wired into `run_long_horizon_validation.py` as 3
additional candidates behind the existing `--fundamentals-db-path`
gate (8 candidates total when supplied). 18 new tests (ridge-CV
correctness and honesty, pluggable-model-builder wiring, shared-cache
correctness across two instances, the ensemble strategy's own
determinism/leakage/parameter-validation suite, CLI wiring for both
new candidates). Full suite: 2038 passed (up from 2020).

**A genuine consequence, stated plainly**: three model/combination
approaches (`ml_ols`, `ml_ridge`, `rank_average_ensemble`) evaluated
side by side in one run means ML-RESEARCH-PROTOCOL.md section 7's
model-selection multiple-comparisons framing now actually applies, not
just in principle -- `compute_pbo`/`compute_dsr_for_all_candidates`
already treat every strategy in `strategy_specs` as one candidate pool
(now 8, when fundamentals are included), which is exactly the "wider
candidates mapping, no new statistical method needed" reuse that
section anticipated. No result from any of these three has been
observed against real data yet; when one is, it must be read as one of
three tries, not evaluated as if it were the only model considered.

**Deliberately not attempted in this round**: universe breadth
(requires selecting additional real tickers by a documented, non-
cherry-picked rule -- e.g. actual index constituents rather than a
hand-picked list, per ADR-0030's own established discipline against
inventing an unverified universe -- and real ingestion in a
network-enabled environment) and quarterly (10-Q) fundamentals
(requires real parser/ingestion changes to extend past the FY-only
restriction without reintroducing the exact same-filing collision bug
ADR-0042 Decision 7 already found and fixed once). Both remain
real, scoped next steps, not abandoned.

## What this does NOT do

No TEST evaluation, of any kind, has happened -- this stays true
until a VALIDATION result is judged good enough to warrant it. No
feature/target/model registry is persisted (schemas only, per protocol
section 8, matching the "not built until a model exists to register"
framing -- a persistence layer is a legitimate next step, not built
here to keep this ADR's footprint to exactly what was needed). No risk
controls (section 10) are implemented -- every `MLStrategy`-based
candidate produces `OrderIntent`s only inside this project's existing
research backtest engine (`backtest.engine`), the same as every
rule-based strategy candidate; nothing in `broker/live/` approval or
`risk/` is touched, and no path from any of these models reaches a
real order.
