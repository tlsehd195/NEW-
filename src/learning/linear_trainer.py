"""`LinearRegressionTrainer`: the first `CandidateTrainer` that actually
learns from `LabeledSample.features` rather than predicting a constant
(`learning.trainer.MeanRewardBaselineTrainer`).

See docs/decisions/ADR-0049 for why this exists now (the user asked
what "a real trainer" meant and what applying the RL/meta-labeling
literature ADR-0015 cites would take; ADR-0048 fixed the wiring that
made `features` reach `LabeledSample` at all; this module is what
reads it).

**Reuses `ml.linear_model.LinearRegressionModel`** (the pure-stdlib
OLS-via-Gauss-Jordan machinery already built and tested for the ML
Research Track, ADR-0043) rather than a second, parallel
implementation -- that class's own docstring already documents it
operates on "anything with `.features: dict` and `.target: float`",
so `LabeledSample` (which has `.features` and `.label_value`, not
`.target`) is adapted via a tiny local wrapper rather than requiring
`ml.linear_model` to know about `learning.models` at all, keeping the
reuse one-directional and the dependency shallow (`ml.linear_model` is
a leaf math module with no imports back into `learning`/`trade_journal`).

**Never fabricates a fit or a prediction**: too few TRAIN samples with
every required feature present, or a singular normal-equations matrix,
leaves the candidate `fitted=False` with `coefficients`/`intercept`
both `None` -- exactly `ml.ml_strategy._default_ols_builder`'s own
"no signal, never a fabricated fallback fit" discipline, reapplied
here. `predict()` returns `None` (never a guessed value) for any
sample missing a required feature or when the candidate never fit --
`Evaluator` (see `learning/evaluation.py`) already excludes `None`
predictions from its metrics rather than treating them as errors
against a fabricated value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from learning.enums import CandidateModelStatus, SplitName
from learning.models import CandidateModelArtifact, LabeledSample, TrainingDataset

from ml.linear_model import LinearRegressionModel

_DEFAULT_RIDGE = 1e-6


@dataclass(frozen=True)
class _FeatureTargetView:
    """Adapts a `LabeledSample` to `LinearRegressionModel.fit`'s duck-typed
    `.features`/`.target` requirement without `ml.linear_model` needing
    to import `learning.models`."""

    features: dict
    target: float


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        cid = f"CAND-{self._next_id:06d}"
        self._next_id += 1
        return cid


class LinearRegressionTrainer:
    """A `CandidateTrainer` (see `learning.trainer.CandidateTrainer`)
    that fits an OLS (optionally ridge-regularized) model predicting
    `LabeledSample.label_value` from a fixed, caller-declared set of
    `feature_ids`.

    `feature_ids` has no default (the same "no default that could
    silently do the wrong thing" discipline `TrainingDatasetConfig.
    provenance` already established, ADR-0015 decision 3) -- a caller
    must always say explicitly which keys of a sample's `features`
    dict this trainer should read, since `features` is a free-form
    dict whose keys are entirely up to whichever Strategy populated
    `OrderIntent.features` (see ADR-0048); there is no way to safely
    infer the "right" feature set from the data itself.

    Also implements an optional `predict(candidate, sample)` method
    (not part of the `CandidateTrainer` Protocol itself, since
    `MeanRewardBaselineTrainer` has no need for one) that `learning.
    evaluation.Evaluator`/`learning.pipeline.run_learning_pipeline`
    detect via `getattr` and use for genuine per-sample-varying
    evaluation instead of the constant-`predicted_value` path every
    trainer before this one used."""

    version = "linear_regression_trainer_v1"

    def __init__(self, feature_ids: Sequence[str], *, ridge: float = _DEFAULT_RIDGE) -> None:
        if not feature_ids:
            raise ValueError("LinearRegressionTrainer requires at least one feature_id")
        self._feature_ids = list(feature_ids)
        self._ridge = ridge
        self._ids = _IdAllocator()

    def _samples_with_required_features(self, samples: Sequence[LabeledSample]) -> list[LabeledSample]:
        required = set(self._feature_ids)
        return [s for s in samples if s.features is not None and required <= set(s.features)]

    def train(
        self,
        dataset: TrainingDataset,
        labeled_samples: Sequence[LabeledSample],
        *,
        trained_at: datetime,
        seed: Optional[int] = None,
        experiment_id: Optional[str] = None,
    ) -> CandidateModelArtifact:
        train_ids = set(dataset.splits.get(SplitName.TRAIN, ()))
        train_samples = self._samples_with_required_features(
            [s for s in labeled_samples if s.trade_id in train_ids]
        )

        model = LinearRegressionModel(feature_ids=self._feature_ids, ridge=self._ridge)
        fitted = False
        if train_samples:
            try:
                model.fit([_FeatureTargetView(features=s.features, target=s.label_value) for s in train_samples])
                fitted = True
            except ValueError:
                pass  # singular matrix / too few distinct samples -- no fabricated fit

        return CandidateModelArtifact(
            candidate_id=self._ids.allocate(),
            status=CandidateModelStatus.CANDIDATE,
            trainer_version=self.version,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            feature_version=dataset.feature_version,
            label_version=dataset.label_version,
            parameters={
                "feature_ids": list(self._feature_ids),
                "ridge": self._ridge,
                "fitted": fitted,
                "train_sample_count": len(train_samples),
                "coefficients": model.coefficients if fitted else None,
                "intercept": model.intercept if fitted else None,
            },
            seed=seed,
            trained_at=trained_at,
            provenance=dataset.provenance,
            experiment_id=experiment_id,
        )

    def predict(self, candidate: CandidateModelArtifact, sample: LabeledSample) -> Optional[float]:
        """Never fabricates: `None` whenever `candidate` never fit, or
        `sample` is missing a required feature -- the same missing-data
        honesty this project's factor scores already apply, here for a
        trained model's own predictions rather than a formula's."""
        if not candidate.parameters.get("fitted"):
            return None
        if sample.features is None:
            return None
        feature_ids = candidate.parameters["feature_ids"]
        if not set(feature_ids) <= set(sample.features):
            return None
        coefficients = candidate.parameters["coefficients"]
        intercept = candidate.parameters["intercept"]
        return intercept + sum(coefficients[f] * sample.features[f] for f in feature_ids)
