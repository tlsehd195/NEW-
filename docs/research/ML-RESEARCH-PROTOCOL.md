# ML Research Track Protocol (Phase 32, Track B)

## 0. What this document is

A **research infrastructure design**, not an ML implementation. Per
the Phase 32 instructions this session executed against: no ML model
is trained, no new dependency is added, no strategy is deployed, and
`TEST-1` (see `strategy_research.locked_windows`) is not touched by
anything described here. This document exists so that, whenever ML
research on this project actually begins, it starts from a governance
structure decided *before* any model is fit -- not invented
after-the-fact to justify whatever the first experiment happened to
produce.

## 1. Existing ML-adjacent infrastructure (audit)

Searched `src/`, `tests/`, `scripts/` for ML/model/feature/training
code (`find src tests scripts -type f | grep -Ei
"ml|model|feature|train|learn|predict"`). What actually exists, and
what it is NOT:

| Module | What it does | What it is NOT |
|---|---|---|
| `src/predict/` (Phase 6) | `Predictor` Protocol + 3 deterministic baselines (`RandomWalkPredictor`, `DriftPredictor`, `RegimeAwarePredictor`). Sources data exclusively via `AsOfDataView` (point-in-time safe by construction). Returns `PredictionOutput` only -- no predictor here can emit an `Order`/`OrderIntent`, structurally enforcing "Prediction is separate from investment decisions". Already carries `feature_version`, `data_version`, `method_version`, `configuration_version` per prediction. | No predictor here fits parameters to historical data -- all 3 are fixed-formula baselines, not learned models. |
| `src/learning/` (Phase 9) | `DataCleaner` -> `Labeler` -> `build_training_dataset` (chronological TRAIN/VALIDATION/TEST split, content-hash `dataset_version`, `as_of_cutoff` leakage guard) -> `MeanRewardBaselineTrainer` -> `Evaluator` -> `LearningExperimentTracker`. Trains on `ExperienceRecord` (realized trade outcomes from `TradeJournalRepository`). | **Trains on this system's own past trading decisions, not on raw historical market data.** This answers a different question ("what worked when we traded") than Track B's stated goal ("does historical market data contain predictive signal") -- it requires the system to already be live/paper trading to generate training data, which this project is not doing. Cannot be reused as-is for a market-data-features -> future-return model. |
| `src/evolution/` (Phase 11) | `ModelLineageRecord`/`CandidateComparison`/`compare_candidates`/`evaluate_transition`/`TrailingWindowMeanTrainer` -- model status lifecycle (`CandidateModelStatus`) and A/B comparison between two trained candidates. | Governs promotion of an already-trained candidate; does not itself train on market data or select features. |
| `src/regime/features.py` (Phase 5) | `annualized_realized_vol`, `data_completeness`, `compute_trend`/`compute_volatility`/`compute_liquidity`/`compute_correlation`/`compute_stress` -- hand-written technical features for regime classification. | Not a registry (no `feature_id`/version/leakage-risk metadata per feature) and not exposed as ML model inputs today -- consumed only by `RegimeDetector`. |
| `src/strategy_research/signal_ic.py` (this session) | Rank-IC diagnostic for a rule-based strategy's own score function against realized forward returns. | Diagnostic only, not a model -- no fitting, no parameters learned. |

**Conclusion**: real point-in-time discipline (`AsOfDataView`),
versioning conventions, and an experiment-tracking *pattern* already
exist and are reusable. What does NOT exist: a pipeline that takes
historical market-data **features** (price/volume/technical, not
trading-experience) and fits a model to predict **future returns**,
with its own feature/target/model registries and TEST-1-aware
splitting. That is the actual gap Track B fills.

## 2. ML Track goal (explicit, to prevent scope creep)

```
ML Track = a research system for discovering whether historically
available information contains out-of-sample predictive signal.
```

NOT the goal: "find a model that maximizes backtest return." A model
selected by backtest-return alone is exactly the overfitting failure
mode this project's own PBO/DSR machinery exists to catch -- applying
it to model selection is pointless if the selection process itself
already threw away everything but the best-looking backtest.

## 3. TEST-1 lock (binding on ML Track, not just rule-based strategies)

`strategy_research.locked_windows.TEST_1` = `2023-04-28T14:24Z` ..
`2026-08-27T00:00Z`. `overlaps_any_locked_window(start, end)` returns
the offending window(s) for any proposed range. **Every future ML
data split (train, validation, AND test) must call this and refuse to
proceed on a non-empty result.** This is not scoped to the 4 existing
rule-based strategies -- it applies to any model, on the reasoning in
`locked_windows.py`'s own docstring: reusing an observed TEST range
for a *different* model is still evaluating against an already-seen
answer key.

### TEST-2 policy (per the governing instructions' section 33)

Two documented options, neither selected here (selecting one now,
before any ML work exists to need it, would itself be an
un-justified, premature choice):

- **Option A -- wait for real future data.** Once real time passes
  2026-08-27, newly available data is a genuinely unseen test period.
  Simplest, least debatable, but requires waiting.
  - Update, RESOLVED per user instruction 2026-08-29 turn: see
    `docs/decisions/ADR-0041-test-1-lock-and-ml-research-track.md`'s
    "Track A resolution addendum" -- new held-out
    is created automatically by construction on every future
    `RESEARCH_UNIVERSE_STAGE2` re-run against a later `--end` date,
    since `build_chronological_split`'s TEST region is always the
    most recent 20% of `[start, end]`.
- **Option B -- a pre-registered historical TEST-2.** Fix a *different*
  historical range (e.g. some sub-period of 2010-2023-04-28, currently
  TRAIN+VALIDATION) as a second, permanent lock, decided by a rule
  that does not reference any strategy's or model's result (e.g. "the
  most recent 20% of the current TRAIN+VALIDATION region" -- a
  mechanical rule, not a cherry-pick). Available sooner, but overlaps
  data the walk-forward TRAIN+VALIDATION region already used for
  fold-level cross-validation, which needs its own justification
  before being repurposed as a TEST.

**Whichever is chosen, it must be chosen and locked BEFORE any ML
train/validation/model-selection work reads any data from it** -- not
selected after seeing which historical sub-period would make a
candidate model look good.

## 4. Leakage prevention

Every ML feature must carry:

```
feature_available_at: datetime   # when this value was actually knowable
```

Every ML target must carry:

```
target_period_start: datetime
target_period_end: datetime
```

**Hard constraint, checked at dataset-build time, not just documented:**

```
feature_available_at <= prediction_time
```

Any sample violating this is EXCLUDED, not clamped or corrected --
mirrors `data_infra.repository.DataRepository`'s existing
`available_time <= as_of_time` look-ahead guard (ADR-0004) and
`learning.dataset.build_training_dataset`'s existing `as_of_cutoff`
mechanism, both already proven in this codebase; a new ML dataset
builder should call the *same* `AsOfDataView`/`available_time`
machinery rather than reinvent a parallel one.

Target leakage: the target's own calculation must not read any bar
whose `timestamp > target_period_end`, and the feature set used to
predict it must not read any bar whose `timestamp >= target_period_start`
(otherwise the "future" the target measures has already partially
leaked into the "present" the features describe).

## 5. Train / Validation / Test structure

```
TRAIN -> VALIDATION -> MODEL SELECTION -> LOCK -> TEST (once)
```

Reuses this project's existing chronological-split discipline
(`strategy_research.splits.build_chronological_split`, never a random
shuffle) rather than inventing a second splitting mechanism. TEST is
evaluated exactly once; after that evaluation, no feature, model,
hyperparameter, or target change may be made and re-evaluated against
the same TEST range (this is the identical rule ADR-0038 already
applied to the rule-based strategies' bug fix -- the corrected
strategies were NOT re-scored against TEST-1).

## 6. Experiment governance / hyperparameter budget

Every ML experiment run must record, before results are known:

```
experiment_id
model_family
feature_set_id
target_id
hyperparameter_set_id
training_window
validation_window
random_seed
selection_reason        # filled in AFTER validation, not before
```

**The experiment count itself must be tracked and reported.** "More
models is not more evidence" (section 30 of the governing
instructions) -- 100 experiments with only the best one reported is
exactly what PBO's CSCV resampling exists to catch, and reporting only
model count without reporting attempt count defeats that purpose. A
future `MLExperimentRepository` (parallel to the existing
`storage.learning_repository`) must expose "how many experiments were
run in this study" as a first-class, always-visible field -- not an
optional one a report can omit.

## 7. Model selection rule

```
Candidate models -> Predefined evaluation protocol -> VALIDATION
results -> statistical correction for multiple comparisons -> selection
-> LOCK
```

The selection step is itself a multiple-testing procedure and must be
documented as such (this is precisely what `strategy_research.pbo_dsr`
already treats the 4 rule-based strategies as -- "candidates," plural,
with PBO explicitly asking "would the best-of-N have looked this good
by chance"). **A future ML integration should feed its own
VALIDATION-window fold returns into the existing
`compute_pbo`/`compute_dsr_for_all_candidates` functions, the same
interface the 4 rule-based strategies already use** -- no new
statistical method needs inventing for this, only a wider `candidates`
mapping.

## 8. Feature / Target / Model registries (schemas -- not built this Phase)

Per the governing instructions' own emphasis (section 34/42: design
before implementation, minimize this Phase's code footprint), these
are specified as schemas an eventual `FeatureRegistry`/
`TargetRegistry`/`ModelRegistry` module would implement -- not built
now, since no ML model exists yet to register.

```
Feature:
    feature_id, description, source, formula,
    availability_time_rule, lookback, data_dependency,
    known_leakage_risk, version

Target:
    target_id, definition, horizon, calculation,
    availability_time_rule, version

Model:
    model_id, model_family, version, hyperparameters,
    feature_set_id, target_id, training_period, validation_period,
    experiment_id
```

A version bump is required whenever a feature's or target's
*definition* changes -- changing a feature silently in place while
keeping its `feature_id` would make historical experiment records
describe something they no longer mean.

## 9. Reproducibility

Every experiment must be re-derivable from: random seed, feature-set
version, target version, dataset version (content hash, following
`learning.dataset`'s existing `compute_data_version` pattern), code
commit, model version, and configuration hash. No ML code path may
read wall-clock time as an input to training (mirrors this project's
existing reproducibility tests for `learning`/`baseline`, e.g.
`tests/learning/test_reproducibility.py`'s AST-based "no `random`
module used outside a seeded context" check -- an ML equivalent
should assert the same for whatever training library is eventually
adopted).

## 10. Risk controls (design requirements, not implemented this Phase)

A future ML-driven signal must, at minimum, define behavior for:
prediction confidence thresholds, exposure/position/turnover limits
(reusing `risk.config.RiskConfig`, never a parallel risk system),
missing-feature behavior, model-failure behavior (NaN/Inf/timeout ->
no signal, never a fabricated fallback prediction -- same principle
`data_infra.quality`'s new `non_finite_value` check just applied to
market data, ADR-0040), stale-prediction detection, and model/feature
drift monitoring (training-distribution vs. current-distribution
comparison; drift thresholds are NOT set here since setting them
without a real model to calibrate against would itself be an
unjustified guess).

## 11. Pipeline stage separation (unchanged principle, restated for ML)

```
DATA -> FEATURES -> MODEL -> PREDICTION -> SIGNAL -> RANKING
     -> PORTFOLIO CONSTRUCTION -> RISK FILTER -> ORDER
```

A model must not output portfolio weights directly -- it outputs a
`PredictionOutput`-shaped signal (reusing `predict.models.
PredictionOutput`'s existing shape), and ranking/portfolio
construction/risk filtering stay separate, testable stages, exactly as
`backtest.strategy.Strategy.generate_orders` already separates
signal-generation from `PortfolioAccounting`. This also means each
stage's contribution to final performance can be decomposed
independently (the same "signal quality vs. portfolio construction vs.
risk control" separation Track A's `risk_controlled_momentum` finding
already demonstrated the value of, on rule-based strategies).

## 12. Human approval gate (unchanged)

```
ML prediction -> risk checks -> human approval -> order
```

No ML code path may bypass `broker.live.approval`'s existing human
approval gate. This document introduces no exception to it.

## 13. Dependency policy

No `numpy`/`scipy`/`scikit-learn`/`xgboost`/`lightgbm`/`pytorch` (or
any other ML library) is added by this document or by Phase 32. Per
ADR-0039's already-established reasoning (applied there to portfolio-
optimization libraries, the same reasoning applies here): a dependency
decision is made when a specific, justified model family is actually
being implemented, as its own ADR -- not speculatively, ahead of any
concrete need.

## 14. Status

**Updated -- first model built AND run against real data (ADR-0043).**
`src/ml/` implements the feature/target schemas (section 8), a
leakage-safe dataset builder (section 4), a first model family (plain
OLS, no new dependency per section 13), and `scripts/train_ml_model_
from_catalog.py` (TEST-1-guarded per section 3, no TEST region touched
per section 5, full experiment-governance record printed per section
6). The real VALIDATION result (mean_ic=+0.1055, IR=0.41, only 11
observations over a COVID-era window) is the strongest raw signal
metric this project has produced, but per this project's own
discipline was not trusted on its own -- `MLStrategy` (`src/ml/
ml_strategy.py`) now puts it through the same walk-forward + PBO/DSR
pipeline `leverage_score`'s own raw IC lead went through (ADR-0043
Decision 3), including a real per-fold-refit performance problem found
and fixed along the way. Not yet run against the real catalog through
that full pipeline -- that real run is the immediate next step. Still
not built: any feature/target/model registry PERSISTENCE layer
(schemas exist, no `MLExperimentRepository`), a second candidate model
family (so no model-selection multiple-comparisons procedure has been
exercised yet), any TEST-region evaluation, and any risk-control
implementation (section 10).
