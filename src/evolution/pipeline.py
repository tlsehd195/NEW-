"""generate_candidate_batch / evaluate_candidate_batch: thin composition
helpers proving Model Evolution's "generate multiple candidates from one
TrainingDataset, then evaluate each" step end to end -- no new
persistence or decision authority, exactly the same "return objects, let
the caller decide whether to persist" separation
`learning.pipeline.run_learning_pipeline` already uses (Phase 9).

See docs/specifications/PHASE-11-model-evolution.md section 3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from learning.evaluation import Evaluator
from learning.models import CandidateModelArtifact, EvaluationResult, LabeledSample, TrainingDataset
from learning.trainer import CandidateTrainer


def generate_candidate_batch(
    dataset: TrainingDataset,
    labeled_samples: Sequence[LabeledSample],
    trainers: Sequence[CandidateTrainer],
    *,
    trained_at: datetime,
    seed: Optional[int] = None,
) -> list[CandidateModelArtifact]:
    if not trainers:
        raise ValueError("generate_candidate_batch requires at least one trainer")
    return [trainer.train(dataset, labeled_samples, trained_at=trained_at, seed=seed) for trainer in trainers]


def evaluate_candidate_batch(
    candidates: Sequence[CandidateModelArtifact],
    dataset: TrainingDataset,
    labeled_samples: Sequence[LabeledSample],
    *,
    evaluated_at: datetime,
    evaluator: Optional[Evaluator] = None,
) -> list[EvaluationResult]:
    evaluator = evaluator or Evaluator()
    return [evaluator.evaluate(c, dataset, labeled_samples, evaluated_at=evaluated_at) for c in candidates]
