"""run_learning_pipeline: the single orchestration function driving the
full Experience -> Cleaning -> Labeling -> Dataset -> Training ->
Evaluation -> Experiment persistence chain (instruction section 23's
required Integration test), mirroring the orchestration role
`baseline.runner.run_baseline` already plays for Phase 2's
BacktestEngine -> Phase 3's `ingest_backtest_result` chain (Phase 4).

This function does not persist anything itself -- it returns the
built objects; the caller decides whether/how to persist them (via
`learning.repository.*` or `storage.learning_repository.*`), the same
separation `baseline.runner.run_baseline` already uses for
Experiment/Experience persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from learning.config import TrainingDatasetConfig
from learning.dataset import DatasetBuildResult, DatasetIdAllocator, build_training_dataset
from learning.evaluation import Evaluator
from learning.experiment import LearningExperimentTracker
from learning.models import CandidateModelArtifact, EvaluationResult, LearningExperimentRecord
from learning.trainer import CandidateTrainer, MeanRewardBaselineTrainer

from trade_journal.enums import TradeProvenance
from trade_journal.models import ExperienceRecord
from trade_journal.repository import TradeJournalRepository


@dataclass(frozen=True)
class LearningPipelineResult:
    dataset_result: DatasetBuildResult
    candidate: CandidateModelArtifact
    evaluation: EvaluationResult
    experiment: LearningExperimentRecord


def run_learning_pipeline(
    journal: TradeJournalRepository,
    records: Sequence[ExperienceRecord],
    *,
    provenance: TradeProvenance,
    config: TrainingDatasetConfig = TrainingDatasetConfig(),
    as_of_cutoff: Optional[datetime] = None,
    trainer: Optional[CandidateTrainer] = None,
    seed: Optional[int] = None,
    run_at: datetime,
    dataset_id_allocator: Optional[DatasetIdAllocator] = None,
) -> LearningPipelineResult:
    trainer = trainer or MeanRewardBaselineTrainer()
    evaluator = Evaluator()
    tracker = LearningExperimentTracker()

    dataset_result = build_training_dataset(
        journal, records, provenance=provenance, config=config, as_of_cutoff=as_of_cutoff,
        created_at=run_at, id_allocator=dataset_id_allocator,
    )

    candidate = trainer.train(
        dataset_result.dataset, dataset_result.labeled_samples, trained_at=run_at, seed=seed,
    )
    # ADR-0049: a trainer MAY optionally implement `predict(candidate,
    # sample) -> Optional[float]` for genuine per-sample-varying
    # evaluation (e.g. learning.linear_trainer.LinearRegressionTrainer)
    # -- not part of the CandidateTrainer Protocol itself, since
    # MeanRewardBaselineTrainer has no need for one and every existing
    # caller/test predates this. Detected via getattr, never required.
    predict_fn = getattr(trainer, "predict", None)
    evaluation = evaluator.evaluate(
        candidate, dataset_result.dataset, dataset_result.labeled_samples, evaluated_at=run_at,
        predict_fn=predict_fn,
    )

    status = "COMPLETED" if dataset_result.dataset.quality_status == "OK" else "FAILED"
    experiment = tracker.record(
        dataset=dataset_result.dataset, candidate=candidate, evaluation=evaluation,
        seed=seed, provenance=provenance, status=status, created_at=run_at,
    )

    return LearningPipelineResult(
        dataset_result=dataset_result, candidate=candidate, evaluation=evaluation, experiment=experiment,
    )
