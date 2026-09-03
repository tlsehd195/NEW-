"""Evaluator: minimal evaluation interface for a `CandidateModelArtifact`
(instruction section 13).

Computes MAE/MSE against each split's actual `label_value`, plus a
`baseline_metrics` comparison point (a trivial "always predict 0.0"
predictor, evaluated over the same TEST split) so a candidate can be
read next to a baseline rather than in isolation -- never a claim that
the candidate is superior (instruction section 14: "단일 높은 수익률만으로
모델 우위를 주장하지 않는다"). This phase does not implement PBO/
Deflated Sharpe/Walk-Forward validation -- see
docs/specifications/PHASE-9-learning-engine.md section 13 and
Phase Boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Sequence

from learning.enums import SplitName
from learning.models import CandidateModelArtifact, EvaluationMetrics, EvaluationResult, LabeledSample, TrainingDataset

# Session 36 (ADR-0049): a trainer whose prediction genuinely varies
# per sample (e.g. learning.linear_trainer.LinearRegressionTrainer)
# supplies one of these -- (candidate, sample) -> a predicted
# label_value, or None when this particular sample cannot be scored
# (e.g. missing a required feature). MeanRewardBaselineTrainer has no
# such method; Evaluator.evaluate falls back to its original
# constant-`predicted_value` behavior when none is given, so every
# pre-existing caller/test is unaffected.
PredictFn = Callable[[CandidateModelArtifact, LabeledSample], Optional[float]]


class _IdAllocator:
    def __init__(self) -> None:
        self._next_id = 1

    def allocate(self) -> str:
        eid = f"EVAL-{self._next_id:06d}"
        self._next_id += 1
        return eid


def _compute_metrics(samples: Sequence[LabeledSample], predict: Callable[[LabeledSample], Optional[float]]) -> EvaluationMetrics:
    # `None` predictions (a sample this particular candidate/trainer
    # cannot score, e.g. missing a required feature) are excluded, not
    # scored as an error against a fabricated value -- `sample_count`
    # here is honestly the number of samples actually scored, which can
    # be smaller than the split's own total size for a trainer with a
    # `predict` method; it is always the full split size for the
    # constant-prediction (no `predict_fn`) path, since that path never
    # returns None.
    scored = [(s.label_value, prediction) for s in samples for prediction in (predict(s),) if prediction is not None]
    n = len(scored)
    if n == 0:
        return EvaluationMetrics(sample_count=0, mean_absolute_error=None, mean_squared_error=None, mean_label=None)
    errors = [actual - predicted for actual, predicted in scored]
    mae = sum(abs(e) for e in errors) / n
    mse = sum(e * e for e in errors) / n
    mean_label = sum(actual for actual, _ in scored) / n
    return EvaluationMetrics(sample_count=n, mean_absolute_error=mae, mean_squared_error=mse, mean_label=mean_label)


class Evaluator:
    version = "evaluator_v1"

    def __init__(self) -> None:
        self._ids = _IdAllocator()

    def evaluate(
        self,
        candidate: CandidateModelArtifact,
        dataset: TrainingDataset,
        labeled_samples: Sequence[LabeledSample],
        *,
        evaluated_at: datetime,
        predict_fn: Optional[PredictFn] = None,
    ) -> EvaluationResult:
        by_split: dict[SplitName, list[LabeledSample]] = {split: [] for split in SplitName}
        for split in SplitName:
            ids = set(dataset.splits.get(split, ()))
            by_split[split] = [s for s in labeled_samples if s.trade_id in ids]

        if predict_fn is None:
            predicted_value = candidate.parameters.get("predicted_value", 0.0)
            predict = lambda sample: predicted_value  # noqa: E731 -- matches every prior candidate's constant prediction
        else:
            predict = lambda sample: predict_fn(candidate, sample)  # noqa: E731

        return EvaluationResult(
            evaluation_id=self._ids.allocate(),
            candidate_id=candidate.candidate_id,
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            train_metrics=_compute_metrics(by_split[SplitName.TRAIN], predict),
            validation_metrics=_compute_metrics(by_split[SplitName.VALIDATION], predict),
            test_metrics=_compute_metrics(by_split[SplitName.TEST], predict),
            baseline_metrics=_compute_metrics(by_split[SplitName.TEST], lambda sample: 0.0),
            evaluator_version=self.version,
            evaluated_at=evaluated_at,
            provenance=dataset.provenance,
        )
