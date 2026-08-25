"""LearningExperimentTracker: allocates "LRN-000001" style ids and ties
a training run's dataset/candidate/evaluation together into one
`LearningExperimentRecord`, mirroring `backtest.experiment.
ExperimentTracker`'s id-allocation pattern (Phase 2) for a differently-
shaped record (see `learning.models.LearningExperimentRecord` docstring
and docs/decisions/ADR-0015 section 1 for why the two are not the same
type).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from learning.models import CandidateModelArtifact, EvaluationResult, LearningExperimentRecord, TrainingDataset

from trade_journal.enums import TradeProvenance


class LearningExperimentTracker:
    def __init__(self) -> None:
        self._next_id = 1

    def _allocate_id(self) -> str:
        eid = f"LRN-{self._next_id:06d}"
        self._next_id += 1
        return eid

    def record(
        self,
        *,
        dataset: TrainingDataset,
        candidate: CandidateModelArtifact,
        evaluation: EvaluationResult,
        seed: Optional[int],
        provenance: TradeProvenance,
        status: str,
        created_at: datetime,
    ) -> LearningExperimentRecord:
        return LearningExperimentRecord(
            experiment_id=self._allocate_id(),
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.dataset_version,
            trainer_version=candidate.trainer_version,
            evaluator_version=evaluation.evaluator_version,
            candidate_id=candidate.candidate_id,
            evaluation_id=evaluation.evaluation_id,
            configuration_version=dataset.configuration_version,
            seed=seed,
            provenance=provenance,
            status=status,
            created_at=created_at,
        )
