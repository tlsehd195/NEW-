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

## Decision 6 -- real 8-candidate result: regularization helped modestly, still no CANDIDATE; a second real experiment_id collision found and fixed

The user ran `run_long_horizon_validation.py` with `--fundamentals-db-path`
against the real 39-symbol catalogs (same `--start`/`--end` as Decision
4's run). The real result:

```
PBO: 20.00% across 70 CSCV splits (8 candidates)

buy_and_hold:              42% positive folds -- below 60% bar. TEST net cumret=+20.16%
ml_ols:                    53% positive folds -- below 60% bar. TEST net cumret=+37.34% sharpe=0.58, DSR=0.9999
long_term_momentum:        57% positive folds -- below 60% bar. TEST net cumret=+16.81%
risk_controlled_momentum:  57% positive folds -- below 60% bar. TEST net cumret=+8.70%
leverage:                  57% positive folds -- below 60% bar. TEST net cumret=+33.56%
ml_ridge:                  58% positive folds -- below 60% bar. TEST net cumret=+30.76% sharpe=0.63, DSR=1.0000
rank_average_ensemble:     58% positive folds -- below 60% bar. TEST net cumret=-23.04% sharpe=0.44, DSR=0.9989
trend_volatility:          60% positive folds -- clears the bar, but DSR=0.9323 < 0.95 (FAILED). TEST net cumret=+0.13%
```

**`ml_ridge` and `rank_average_ensemble` both modestly outperform
`ml_ols` on fold-consistency (58% vs 53%)** -- some real evidence that
regularization (and, separately, rank-averaging) reduces the
instability a plain unregularized fit on this little data showed, the
motivation Decision 5 built both against. **Neither clears the 60%
bar.** `ml_ridge`'s DSR (1.0000) is the highest of all 8 candidates,
but is never evaluated against the 0.95 threshold since fold-
consistency blocks first -- the same "never reaches the second gate"
pattern every fundamentals/ML candidate has shown so far.

**A second genuine divergence, in the opposite direction from
Decision 4's**: `rank_average_ensemble` has among the better fold-
consistency of the fundamentals/ML candidates (58%, tied with
`ml_ridge`) but the WORST held-out TEST result of all 8
(-23.04% net, the only negative TEST return this project has ever
observed for any candidate). Read per this project's established
"PBO/DSR vs. held-out TEST divergence" framing: reasonable walk-
forward consistency does not guarantee a good TEST-window outcome
either -- the two metrics answer genuinely different questions, and
neither substitutes for the other. `REAL_VALIDATION_NOT_COMPLETED`
remains correct for all 8 candidates.

**A second real `experiment_id` collision, found by direct comparison
of this run's printed output against Decision 4's**: both runs printed
the SAME `experiment_id`, despite Decision 5 adding 2 new candidates
(6 -> 8) and reverting `ml_ols`'s own `train_window_months` default
(36 -> 60, changing its fitted model and therefore its real result --
compare `ml_ols`'s TEST cumret here, +37.34%, against Decision 4's
+55.59%, the SAME candidate under the SAME `experiment_id`). Root
cause: `fundamentals_included` only distinguishes "no fundamentals"
from "some fundamentals candidates," not which ones, and no field ever
captured the candidate set itself. Fixed by moving the `experiment_id`
computation to AFTER `strategy_specs` is fully built and hashing the
actual sorted candidate name list (`candidate_names`). **Explicitly
NOT a full fix**: this still cannot detect a change to an EXISTING
candidate's own fixed internal parameters (e.g. `MLStrategyParameters.
train_window_months` changing while the candidate is still named
`ml_ols`) -- there is no code-identity/git-commit-hash mechanism in
this script, and building one is out of scope here. This is recorded
as a real, known, deliberately unresolved gap, not silently left
undocumented. 2 new regression tests. Full suite: 2040 passed.

## Decision 7 -- real Stage 3 (64-symbol) result: first-ever CANDIDATE (`leverage`), but its held-out TEST result is the worst this project has ever recorded; pool-level PBO got worse, not better

The user ran the real ingestion (`ingest_real_market_data.py --universe
RESEARCH_UNIVERSE`, `ingest_fundamentals_data.py --universe
RESEARCH_UNIVERSE`) for ADR-0044's 24 new symbols, then
`run_long_horizon_validation.py --universe RESEARCH_UNIVERSE --start
2010-01-01 --end 2023-04-28 --fundamentals-db-path ... --data-status
REAL` against the real 64-symbol catalog. Real result:

```
PBO: 38.57% across 70 CSCV splits (8 candidates)

buy_and_hold:              38% positive folds -- below 60% bar. TEST net cumret=+21.67% sharpe=0.41
long_term_momentum:        53% positive folds -- below 60% bar. TEST net cumret=+24.75% sharpe=0.40
trend_volatility:          53% positive folds -- below 60% bar. TEST net cumret=-2.69% sharpe=0.16
risk_controlled_momentum:  53% positive folds -- below 60% bar. TEST net cumret=+20.51% sharpe=0.37
leverage:                  60% positive folds -- CLEARS the bar. PBO=0.39<0.5, DSR=0.9674>=0.95.
                            evidence=CANDIDATE. TEST net cumret=-26.43% sharpe=0.52 (7 trades)
ml_ols:                    50% positive folds -- below 60% bar. TEST net cumret=+109.10% sharpe=0.75
ml_ridge:                  47% positive folds -- below 60% bar. TEST net cumret=+75.91% sharpe=0.64
rank_average_ensemble:     57% positive folds -- below 60% bar. TEST net cumret=+5.56% sharpe=0.43
```

**`leverage` is the first candidate in this project's entire history to
reach `evidence=CANDIDATE`** -- 60% positive folds (exactly at the
bar), PBO=0.39<0.5, Deflated Sharpe=0.9674>=0.95, all three gates
cleared. **This must not be read as validation, or even as encouraging
evidence, for the reason stated in the tool's own output**
(`"Still not VALIDATED: that requires explicit human review this
function does not perform"`): `leverage`'s held-out TEST result is
**-26.43% net -- the single worst TEST result this project has ever
recorded for any candidate**, surpassing the previous record
(`rank_average_ensemble`'s -23.04%, ADR-0043 Decision 6). Per this
project's own established "PBO/DSR vs. held-out TEST divergence"
framing, this is the starkest instance of that divergence yet: the
ONE candidate that cleared every walk-forward robustness gate produced
the worst single-window outcome of the entire pool. Clearing
CANDIDATE's statistical bar answers "was this consistent across
resampled historical folds," not "would this have made money just
now" -- those are different questions, and this result is the clearest
demonstration to date of why neither substitutes for the other.

**A second, opposite-direction divergence, more extreme than any
prior instance**: `ml_ols` produced this project's best-ever TEST
result (+109.10% net, sharpe=0.75) while its fold-consistency (50%)
is actually WORSE than its own Stage 2 number (53%, ADR-0043 Decision
4). `ml_ridge` shows the same pattern less starkly (+75.91% TEST vs.
47% fold-consistency, down from Stage 2's 58%).

**A finding that runs counter to this round's own motivating
hypothesis**: universe expansion (ADR-0044) was pursued specifically
because a wider cross-section was expected to reduce the multiple-
testing/overfitting risk visible in the 39-symbol results. Instead,
**pool-level PBO rose from 20.00% (Stage 2, same 8 candidates,
ADR-0043 Decision 6) to 38.57% (Stage 3)** -- roughly double. This is
not proof that widening the universe caused more overfitting risk
(the fold count also changed, 76 -> 60, from a different chronological
split under the same `--train-fraction`/`--validation-fraction`
defaults applied to a data range whose actually-available bars differ
slightly by symbol; multiple things changed at once, not isolated by
this run), but it is real evidence against the hypothesis that
breadth alone would improve robustness, and it must be stated plainly
rather than downplayed because it cuts against this round's own
motivating rationale.

**Per RULE 0.8**: none of these real TEST observations may be used to
retune `leverage`, `ml_ols`, `ml_ridge`, the universe, or any other
parameter now that they have been seen. `REAL_VALIDATION_NOT_COMPLETED`
remains the correct overall classification for this project's real
progress -- one candidate reaching the `CANDIDATE` evidence-level label
is a defined statistical threshold, not a claim that a validated,
deployable edge has been found; the TEST result attached to that same
candidate argues directly against treating it as one.

## Decision 8 -- an externally-researched candidate, `asset_growth_score`, added via literature search rather than found by trying every combination of what this project already had

Asked how to speed up finding a validated strategy, the user proposed
combining traits from famous investors' philosophies and picking
"whatever looks good" -- the assistant flagged this as exactly the
sequential/post-hoc-selection bias RULE 0.8 exists to prevent (choosing
rules because they already look attractive is indistinguishable from
data-mining after the fact), and instead proposed searching published,
independently-replicated academic/practitioner research for a rule that
can be fixed BEFORE any result is seen, same as every other candidate
in this project. The user agreed and asked for broad research (12
candidate strategies researched and verified via web search: Piotroski
F-Score, Quality Minus Junk, O'Shaughnessy Trending Value, Altman
Z-Score, Graham NCAV, Dividend Growth, Sloan Accruals, Asset Growth
Anomaly, PEAD, Value+Momentum combination, Shareholder Yield, 52-week
High Momentum), each checked for (a) independent academic replication,
not just the original publication, (b) whether it is genuinely
different information from what this project has already tested
(ROE/ROA/net_margin/leverage are all single-period LEVEL ratios), and
(c) whether it is feasible against this project's actual current data
(most need new SEC XBRL concepts or a data source -- consensus earnings
estimates for PEAD -- this project does not have and would require new
real ingestion to obtain).

**`asset_growth_score` (Cooper, Gulen & Schill 2008, "The Asset Growth
Effect in Stock Returns," Journal of Finance) was chosen to build
first, specifically because it needs zero new data**: the finding is a
strong, negative relationship between a company's YoY total-assets
growth rate and its subsequent returns (reported ~20%/year premium for
low- over high-growth firms across a 40-year US sample, holding even
within large-cap stocks specifically), and `Assets` is already one of
the 5 default XBRL concepts this project's real ingestion has been
collecting since ADR-0042 -- unlike every other researched candidate,
this one required no new ingestion round in the user's environment to
test. It is also the first factor in `strategy_research.factor_scores`
that is a year-over-year CHANGE rather than a single fiscal year's
ratio, needing a new code path (`_fy_records`, refactored out of the
existing `_latest_fiscal_year_value` so both share the same
point-in-time FY-filtering discipline) rather than reusing `_fy_ratio`.

**Explicitly NOT wired into `run_long_horizon_validation.py`'s 8-candidate
walk-forward pool yet**, per the user's own instruction ("바로 넣으면
문제 생길 수도 있으니까 테스트 후 넣을지 말지 정함" -- don't add it
directly, decide after testing) -- mirrors exactly how `leverage_score`
itself was first validated via cheap raw Signal IC
(`compute_fundamentals_ic_from_catalog.py`, now accepting `--score
asset_growth`) before ever being built into a full `Strategy` and
added to the walk-forward candidate pool (ADR-0042 Decision 12,
`leverage_strategy.py`). Only once a real IC result is relayed and
judged worth the additional multiple-testing burden of a 9th walk-forward
candidate does building `AssetGrowthStrategy` become the next step --
not decided here.

**Other researched candidates, deliberately not pursued this round,
with the specific reason**:
- Piotroski F-Score, Shareholder Yield -- credible, strong replication,
  but need new SEC XBRL concepts (cash flow, debt, shares outstanding,
  etc.) not yet ingested; real next steps once `asset_growth`'s own
  result comes back.
- Quality Minus Junk, O'Shaughnessy Trending Value, Magic Formula --
  credible but substantially more construction complexity (multi-metric
  composites, enterprise-value calculations combining price and
  fundamentals data) for a first try.
- PEAD -- needs consensus earnings-estimate data this project has no
  source for at all; not feasible without a new data source, not just
  new ingestion.
- Altman Z-Score, Graham NCAV -- researched and explicitly rejected:
  Z-Score's own backtest evidence shows it does not work as a
  standalone return-predicting signal (only as a bankruptcy-risk
  filter); NCAV's modern-era evidence is mixed-to-negative in the US
  specifically, and structurally cannot apply to this project's
  large/mid-cap-only universe (NCAV requires trading below net current
  asset value, essentially never true for a blue-chip company).
- 52-week High Momentum -- original effect confirmed but recent
  backtests show it decays to near-cash after realistic costs; also
  redundant with this project's existing price-momentum candidates.

7 new tests (6 in `tests/strategy_research/test_factor_scores.py::
TestAssetGrowthScore`, 1 CLI end-to-end wiring test in `tests/
strategy_research/test_compute_fundamentals_ic_from_catalog_cli.py`).
Full suite: 2063 passed (up from 2056).

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
