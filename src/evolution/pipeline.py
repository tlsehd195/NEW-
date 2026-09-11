"""generate_candidate_batch / evaluate_candidate_batch: thin composition
helpers proving Model Evolution's "generate multiple candidates from one
TrainingDataset, then evaluate each" step end to end -- no new
persistence or decision authority, exactly the same "return objects, let
the caller decide whether to persist" separation
`learning.pipeline.run_learning_pipeline` already uses (Phase 9).

See docs/specifications/PHASE-11-model-evolution.md section 3.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional, Sequence

from learning.evaluation import Evaluator
from learning.models import CandidateModelArtifact, EvaluationResult, LabeledSample, TrainingDataset
from learning.trainer import CandidateTrainer


def _disambiguate_candidate_ids(candidates: list[CandidateModelArtifact]) -> list[CandidateModelArtifact]:
    """Each trainer passed to `generate_candidate_batch` carries its own
    process-local id counter starting at 1 (e.g. `evolution.trainer
    ._IdAllocator`, `learning.trainer._IdAllocator`), since a trainer has
    no way to know what other trainers it might be combined with. This
    phase's whole point is running several trainers on the same dataset
    (see `evolution.trainer.TrailingWindowMeanTrainer`'s module
    docstring), so combining their output in one batch reliably produces
    candidates that all claim `candidate_id="CAND-000001"` -- external
    review finding (Session 36 continued). A repository resolves this by
    reassigning its own id from a natural key at persistence time (see
    `learning.repository.InMemoryCandidateModelRepository` /
    `storage.learning_repository.DuckDBCandidateModelRepository`), but
    code that reads `candidate_id` straight off this batch -- e.g.
    `evolution.comparison.compare_candidates` -- never goes through a
    repository, so it needs the batch itself to already be unique.
    Only the colliding entries are touched (a numeric suffix appended in
    encounter order), so a batch with no collision keeps every trainer's
    own id unchanged."""
    seen: dict[str, int] = {}
    result = []
    for candidate in candidates:
        occurrence = seen.get(candidate.candidate_id, 0) + 1
        seen[candidate.candidate_id] = occurrence
        if occurrence == 1:
            result.append(candidate)
        else:
            result.append(dataclasses.replace(candidate, candidate_id=f"{candidate.candidate_id}-{occurrence}"))
    return result


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
    candidates = [trainer.train(dataset, labeled_samples, trained_at=trained_at, seed=seed) for trainer in trainers]
    return _disambiguate_candidate_ids(candidates)


def evaluate_candidate_batch(
    candidates: Sequence[CandidateModelArtifact],
    dataset: TrainingDataset,
    labeled_samples: Sequence[LabeledSample],
    *,
    evaluated_at: datetime,
    trainers: Optional[Sequence[CandidateTrainer]] = None,
    evaluator: Optional[Evaluator] = None,
) -> list[EvaluationResult]:
    """`trainers`, when given, must be the same length as `candidates`
    and in the same order `generate_candidate_batch` produced them in
    (one trainer per candidate) -- each candidate is then evaluated
    with ITS OWN trainer's optional `predict(candidate, sample)` method
    (ADR-0049), exactly like `learning.pipeline.run_learning_pipeline`
    already does for a single candidate/trainer pair.

    Session 37 (ADR-0115, external review, previously-remaining MEDIUM):
    before `trainers` existed, every candidate here was always evaluated
    with `predict_fn=None` -- `Evaluator.evaluate`'s own fallback in
    that case predicts the SAME constant `candidate.parameters[
    "predicted_value"]` for every sample, which is only correct for a
    constant-output trainer (`MeanRewardBaselineTrainer`/
    `TrailingWindowMeanTrainer`). A genuinely feature-based trainer
    (e.g. `learning.linear_trainer.LinearRegressionTrainer`, which DOES
    implement its own per-sample `predict`) was silently misevaluated
    as if it, too, only ever predicted one constant value -- structurally
    unable to distinguish a real per-sample model from a baseline in any
    comparison this batch feeds. Omit `trainers` (the default) to keep
    every existing caller's behavior unchanged."""
    evaluator = evaluator or Evaluator()
    if trainers is not None and len(trainers) != len(candidates):
        raise ValueError(
            f"trainers ({len(trainers)}) must be the same length as candidates ({len(candidates)}) "
            "-- one trainer per candidate, in the same order generate_candidate_batch produced them"
        )
    predict_fns: Sequence[Optional[object]] = (
        [getattr(t, "predict", None) for t in trainers] if trainers is not None else [None] * len(candidates)
    )
    return [
        evaluator.evaluate(c, dataset, labeled_samples, evaluated_at=evaluated_at, predict_fn=pf)
        for c, pf in zip(candidates, predict_fns)
    ]
