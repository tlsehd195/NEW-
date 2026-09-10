"""Repository Protocols + InMemory reference implementations for the
Learning Engine's four persisted types, mirroring the Repository
Protocol discipline Phase 1/3/5/6/7/8 already established.

See docs/specifications/PHASE-9-learning-engine.md section 15.
"""

from __future__ import annotations

import dataclasses
from typing import Optional, Protocol

from learning.models import CandidateModelArtifact, EvaluationResult, LearningExperimentRecord, TrainingDataset

from trade_journal.enums import TradeProvenance


class TrainingDatasetRepository(Protocol):
    def record(self, dataset: TrainingDataset) -> TrainingDataset:
        """Idempotent on dataset_version -- rebuilding an identical
        dataset (same source experiences + same configuration) returns
        the existing record rather than duplicating it."""
        ...

    def get(self, dataset_id: str) -> Optional[TrainingDataset]: ...
    def get_by_version(self, dataset_version: str) -> Optional[TrainingDataset]: ...
    def list_all(self, *, provenance: Optional[TradeProvenance] = None) -> list[TrainingDataset]: ...


class InMemoryTrainingDatasetRepository:
    def __init__(self) -> None:
        self._datasets: dict[str, TrainingDataset] = {}
        self._by_version: dict[str, str] = {}

    def record(self, dataset: TrainingDataset) -> TrainingDataset:
        existing_id = self._by_version.get(dataset.dataset_version)
        if existing_id is not None:
            return self._datasets[existing_id]
        self._datasets[dataset.dataset_id] = dataset
        self._by_version[dataset.dataset_version] = dataset.dataset_id
        return dataset

    def get(self, dataset_id: str) -> Optional[TrainingDataset]:
        return self._datasets.get(dataset_id)

    def get_by_version(self, dataset_version: str) -> Optional[TrainingDataset]:
        did = self._by_version.get(dataset_version)
        return self._datasets.get(did) if did is not None else None

    def list_all(self, *, provenance: Optional[TradeProvenance] = None) -> list[TrainingDataset]:
        results = list(self._datasets.values())
        if provenance is not None:
            results = [d for d in results if d.provenance == provenance]
        return sorted(results, key=lambda d: d.created_at)


class CandidateModelRepository(Protocol):
    def record(self, candidate: CandidateModelArtifact) -> CandidateModelArtifact:
        """Idempotent on (dataset_version, trainer_version, seed,
        provenance)."""
        ...

    def get(self, candidate_id: str) -> Optional[CandidateModelArtifact]: ...
    def list_all(self, *, dataset_id: Optional[str] = None) -> list[CandidateModelArtifact]: ...


class InMemoryCandidateModelRepository:
    """Assigns its own `candidate_id` at record time (ignoring whatever
    id the caller's trainer put on the artifact) -- external review
    finding (Session 36 continued): trainers each carry their own
    process-local `_IdAllocator` starting at 1 (see
    `learning.trainer`/`evolution.trainer`), so `evolution.pipeline
    .generate_candidate_batch`'s documented multi-trainer use produces
    multiple candidates that all claim "CAND-000001". Mirrors
    `storage.learning_repository.DuckDBCandidateModelRepository`, which
    already reassigns `candidate_id` from its own sequence for the same
    reason -- this in-memory reference implementation must do the same
    so it isn't the one repository where that collision silently
    overwrites a distinct candidate under a colliding id."""

    def __init__(self) -> None:
        self._candidates: dict[str, CandidateModelArtifact] = {}
        self._natural_keys: dict[tuple, str] = {}
        self._next_id = 1

    @staticmethod
    def _key(c: CandidateModelArtifact) -> tuple:
        return (c.dataset_version, c.trainer_version, c.seed, c.provenance)

    def record(self, candidate: CandidateModelArtifact) -> CandidateModelArtifact:
        key = self._key(candidate)
        existing_id = self._natural_keys.get(key)
        if existing_id is not None:
            return self._candidates[existing_id]
        candidate = dataclasses.replace(candidate, candidate_id=f"CAND-{self._next_id:06d}")
        self._next_id += 1
        self._candidates[candidate.candidate_id] = candidate
        self._natural_keys[key] = candidate.candidate_id
        return candidate

    def get(self, candidate_id: str) -> Optional[CandidateModelArtifact]:
        return self._candidates.get(candidate_id)

    def list_all(self, *, dataset_id: Optional[str] = None) -> list[CandidateModelArtifact]:
        results = list(self._candidates.values())
        if dataset_id is not None:
            results = [c for c in results if c.dataset_id == dataset_id]
        return sorted(results, key=lambda c: c.trained_at)


class EvaluationRepository(Protocol):
    def record(self, evaluation: EvaluationResult) -> EvaluationResult:
        """Idempotent on (candidate_id, dataset_version,
        evaluator_version)."""
        ...

    def get(self, evaluation_id: str) -> Optional[EvaluationResult]: ...
    def list_all(self, *, candidate_id: Optional[str] = None) -> list[EvaluationResult]: ...


class InMemoryEvaluationRepository:
    """Assigns its own `evaluation_id` at record time -- same collision
    reasoning as `InMemoryCandidateModelRepository` above: `Evaluator`
    carries a process-local `_IdAllocator`, so two `Evaluator` instances
    (or `evolution.pipeline.evaluate_candidate_batch` runs sharing one
    across multiple candidates from colliding-id trainers) can produce
    evaluations that both claim "EVAL-000001". Mirrors
    `storage.learning_repository.DuckDBEvaluationRepository`."""

    def __init__(self) -> None:
        self._evaluations: dict[str, EvaluationResult] = {}
        self._natural_keys: dict[tuple, str] = {}
        self._next_id = 1

    @staticmethod
    def _key(e: EvaluationResult) -> tuple:
        return (e.candidate_id, e.dataset_version, e.evaluator_version)

    def record(self, evaluation: EvaluationResult) -> EvaluationResult:
        key = self._key(evaluation)
        existing_id = self._natural_keys.get(key)
        if existing_id is not None:
            return self._evaluations[existing_id]
        evaluation = dataclasses.replace(evaluation, evaluation_id=f"EVAL-{self._next_id:06d}")
        self._next_id += 1
        self._evaluations[evaluation.evaluation_id] = evaluation
        self._natural_keys[key] = evaluation.evaluation_id
        return evaluation

    def get(self, evaluation_id: str) -> Optional[EvaluationResult]:
        return self._evaluations.get(evaluation_id)

    def list_all(self, *, candidate_id: Optional[str] = None) -> list[EvaluationResult]:
        results = list(self._evaluations.values())
        if candidate_id is not None:
            results = [e for e in results if e.candidate_id == candidate_id]
        return sorted(results, key=lambda e: e.evaluated_at)


class LearningExperimentRepository(Protocol):
    def record(self, experiment: LearningExperimentRecord) -> LearningExperimentRecord:
        """Idempotent: recording the same experiment_id twice is a
        no-op the second time (natural key = experiment_id itself),
        mirroring `storage.experiment_repository.DuckDBExperimentRepository`."""
        ...

    def get(self, experiment_id: str) -> Optional[LearningExperimentRecord]: ...
    def list_all(self) -> list[LearningExperimentRecord]: ...


class InMemoryLearningExperimentRepository:
    def __init__(self) -> None:
        self._experiments: dict[str, LearningExperimentRecord] = {}

    def record(self, experiment: LearningExperimentRecord) -> LearningExperimentRecord:
        existing = self._experiments.get(experiment.experiment_id)
        if existing is not None:
            return existing
        self._experiments[experiment.experiment_id] = experiment
        return experiment

    def get(self, experiment_id: str) -> Optional[LearningExperimentRecord]:
        return self._experiments.get(experiment_id)

    def list_all(self) -> list[LearningExperimentRecord]:
        return sorted(self._experiments.values(), key=lambda e: e.created_at)
