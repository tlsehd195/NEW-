# ADR-0049: `LinearRegressionTrainer` -- the first `CandidateTrainer` that actually learns

**Status:** Accepted
**Session:** 36

## Context

ADR-0048 fixed the wiring so `LabeledSample` (via `ExperienceRecord.
state["features"]`) could actually carry a `Strategy`'s decision-time
rationale end to end. That ADR deliberately stopped short of building
anything that reads `features` -- `learning.trainer.
MeanRewardBaselineTrainer` was, and remained, a constant predictor.

The user then asked to "finish" the retraining feature. This ADR is
that: the first `CandidateTrainer` that fits an actual model (OLS,
optionally ridge-regularized) against `LabeledSample.features`, plus
the `Evaluator`/`pipeline` changes needed for a per-sample-varying
prediction to be evaluated meaningfully at all (the existing
`Evaluator` only ever knew how to score one constant `predicted_value`
against an entire split).

## What was found while building this: `LabeledSample` had no `features` field either

Tracing the chain all the way from `ExperienceRecord.state["features"]`
(ADR-0048's fix) down to where a trainer actually reads samples from
found a THIRD gap in the same "record rationale, then retrain" chain:
`learning.models.LabeledSample` -- what every `CandidateTrainer`
Protocol implementation actually receives -- had no `features` field
at all, and `learning.labeling.Labeler.label()` never copied
`ExperienceRecord.state["features"]` into one. So even after ADR-0048,
a trainer receiving `Sequence[LabeledSample]` still had nothing to
learn from. Fixed here as part of the same "make retraining actually
possible" effort:

- `LabeledSample` gains `features: Optional[dict] = None`.
- `Labeler.label()` sets it from `record.state.get("features")`.

## Decision

### 1. `LinearRegressionTrainer` reuses `ml.linear_model.LinearRegressionModel`, not a second implementation

`ml.linear_model` (built for the ML Research Track, ADR-0043) is
already a tested, pure-stdlib OLS-via-Gauss-Jordan-elimination
implementation, explicitly documented as operating on "anything with
`.features: dict` and `.target: float`" -- i.e. already duck-typed for
reuse outside its original `ml.dataset.MLSample` caller. A tiny local
`_FeatureTargetView` adapter (in `learning/linear_trainer.py`) maps a
`LabeledSample`'s `.features`/`.label_value` onto that shape, so
`ml.linear_model` itself never needs to import anything from
`learning` -- the dependency is one-directional and shallow (`ml.
linear_model` is a leaf math module with no imports back into
`learning`/`trade_journal`). Writing a second Gauss-Jordan solver
would duplicate already-validated math for no reason.

### 2. `feature_ids` has no default -- the same "no silent default" discipline as `TrainingDatasetConfig.provenance` (ADR-0015 decision 3)

A caller must always say explicitly which keys of a sample's
free-form `features` dict this trainer should read. There is no way
to safely infer "the right" feature set, since `features`'s keys are
entirely up to whichever `Strategy` populated `OrderIntent.features`
(ADR-0048) -- a different Strategy could use entirely different names.

### 3. Never fabricates a fit or a prediction

`train()`: TRAIN samples missing any required feature are excluded,
not fabricated with a default value. Zero valid TRAIN samples, or a
singular normal-equations matrix, leaves `fitted=False` with
`coefficients`/`intercept` both `None` -- the exact same "no signal,
never a fabricated fallback fit" discipline `ml.ml_strategy.
_default_ols_builder` already applies, reapplied here.

`predict(candidate, sample)`: returns `None` (never a guessed value)
whenever the candidate never fit, or `sample` is missing a required
feature. This is a **new pattern for this project's Learning Engine**
(not part of the `CandidateTrainer` Protocol itself -- `MeanRewardBaselineTrainer`
never needed one) that `Evaluator`/`pipeline` detect via `getattr` and
use for genuine per-sample-varying evaluation.

### 4. `Evaluator.evaluate()` gains an optional `predict_fn`, fully backward-compatible

The existing `Evaluator` computed every split's metrics against ONE
constant `candidate.parameters.get("predicted_value", 0.0)` --
adequate for `MeanRewardBaselineTrainer`, meaningless for a model whose
prediction varies per sample. `evaluate()` now accepts an optional
`predict_fn: (candidate, sample) -> Optional[float]`; when omitted
(every caller/test that existed before this ADR), it falls back to a
`lambda sample: predicted_value` that reproduces the original behavior
byte-for-byte -- confirmed by every pre-existing `Evaluator` test
still passing unmodified. `_compute_metrics` now excludes samples
where `predict_fn` returns `None` from that split's metrics rather
than fabricating an error against a guessed value -- `sample_count`
in the resulting `EvaluationMetrics` is therefore honestly "how many
samples this candidate could actually score," which can be smaller
than the full split for a real trainer (e.g. samples missing a
required feature), but is always the full split size for the
constant-prediction path, since that path never returns `None`.

`learning.pipeline.run_learning_pipeline` auto-detects a trainer's
optional `predict` method via `getattr(trainer, "predict", None)` and
threads it through -- no caller has to know in advance which kind of
trainer it was given.

## Why this is not a RULE 0.8 violation

No factor formula, strategy logic, walk-forward result, or Signal IC
value is touched by anything in this ADR. `LinearRegressionTrainer` is
generic Learning Engine infrastructure -- like `MeanRewardBaselineTrainer`
before it, it has no opinion about which features matter or which
Strategy should populate them. No existing `Strategy` was modified to
set `OrderIntent.features`; that remains a future, separate decision,
correctly deferred until a `strategy_research` candidate reaches
VALIDATED status (none has yet -- 17 candidates await real raw-IC
results as of this session). Every test in this ADR uses fully
synthetic, deterministic, exact linear relationships (never real
market data) specifically so this remains a plumbing/capability
demonstration, not a claim about any real predictive signal.

## Tests

15 new tests:

- `tests/learning/test_linear_trainer.py` (13): recovers a known exact
  linear relationship's true coefficients/intercept; predictions match
  held-out TEST-split samples to within floating-point tolerance;
  TRAIN-split-only leakage guard (mirrors `MeanRewardBaselineTrainer`'s
  own); every "never fabricates" case (no features at all -- the
  realistic default for every existing Strategy today; samples missing
  a required feature excluded not fabricated; `predict()` returns
  `None` for an unfit candidate or an incomplete sample; empty TRAIN
  split; zero `feature_ids` rejected); `Evaluator` per-sample-prediction
  integration (near-zero error on the exact relationship, unaffected
  default path for `MeanRewardBaselineTrainer`, unscoreable samples
  excluded from `sample_count`).
- `tests/integration/test_learning_pipeline.py` (2 more, added to the
  existing `TestFullPipelineIntegration` file): the full `OrderIntent.
  features -> ... -> LinearRegressionTrainer -> Evaluator` chain driven
  through `run_learning_pipeline` exactly as a real caller would, not
  just the lower-level helpers each unit test exercises separately;
  and the realistic "no Strategy sets features" case does not crash
  the pipeline, degrading honestly to an unfit candidate.

Full suite: 2189 passed (up from 2174).

## What this does NOT do

- Does not modify any existing `Strategy` to populate `OrderIntent.
  features` -- deciding what rationale to attach is a separate,
  future decision belonging with an actually-validated
  `strategy_research` candidate, not this trainer.
- Does not add PBO/Deflated Sharpe/Walk-Forward validation to
  `Evaluator` -- still explicitly deferred (`docs/specifications/
  PHASE-9-learning-engine.md` section 13), unchanged by this ADR.
- Does not change `CandidateModelStatus` handling -- `LinearRegressionTrainer`
  only ever produces `CandidateModelStatus.CANDIDATE`, verified by the
  same AST boundary scan (`tests/learning/test_learning_boundary.py`)
  that already covers every file in `learning/*.py`, including this
  new one.
- Does not add a new ML dependency -- `ml.linear_model` is pure
  stdlib, reused as-is; `pyproject.toml` is unchanged.
