"""Category: Integration Test -- full Learning Engine pipeline: Trade
Journal Experience -> Cleaning -> Labeling -> Training Dataset ->
Candidate Training -> Evaluation -> Experiment persistence, all through
Phase 4's DuckDB catalog (Phase 9 spec sections 12, 15, instruction
section 23).
"""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.pipeline import run_learning_pipeline

from storage.config import StorageConfig
from storage.engine import StorageEngine
from storage.learning_repository import (
    DuckDBCandidateModelRepository,
    DuckDBEvaluationRepository,
    DuckDBLearningExperimentRepository,
    DuckDBTrainingDatasetRepository,
)

from trade_journal.enums import TradeProvenance


class TestFullPipelineIntegration:
    def test_experience_through_experiment_persistence_end_to_end(self, tmp_path) -> None:
        journal, records = build_journal_with_closed_trades(20)

        result = run_learning_pipeline(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1), seed=1,
        )

        assert result.dataset_result.dataset.sample_count == 20
        assert result.candidate.status.value == "CANDIDATE"
        assert result.evaluation.candidate_id == result.candidate.candidate_id
        assert result.experiment.status == "COMPLETED"

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        ds_repo = DuckDBTrainingDatasetRepository(engine)
        cand_repo = DuckDBCandidateModelRepository(engine)
        eval_repo = DuckDBEvaluationRepository(engine)
        exp_repo = DuckDBLearningExperimentRepository(engine)

        stored_dataset = ds_repo.record(result.dataset_result.dataset)
        stored_candidate = cand_repo.record(result.candidate)
        stored_evaluation = eval_repo.record(result.evaluation)
        stored_experiment = exp_repo.record(result.experiment)

        assert stored_dataset.dataset_version == result.dataset_result.dataset.dataset_version
        assert stored_candidate.dataset_version == stored_dataset.dataset_version
        assert stored_evaluation.candidate_id == stored_candidate.candidate_id
        assert stored_experiment.dataset_version == stored_dataset.dataset_version
        assert stored_experiment.candidate_id == stored_candidate.candidate_id
        assert stored_experiment.evaluation_id == stored_evaluation.evaluation_id
        engine.close()

    def test_full_chain_survives_restart(self, tmp_path) -> None:
        journal, records = build_journal_with_closed_trades(15)
        result = run_learning_pipeline(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1))

        store_config = StorageConfig(tmp_path / "store")
        engine1 = StorageEngine(store_config)
        DuckDBTrainingDatasetRepository(engine1).record(result.dataset_result.dataset)
        DuckDBCandidateModelRepository(engine1).record(result.candidate)
        DuckDBEvaluationRepository(engine1).record(result.evaluation)
        DuckDBLearningExperimentRepository(engine1).record(result.experiment)
        engine1.close()

        engine2 = StorageEngine(store_config)
        assert len(DuckDBTrainingDatasetRepository(engine2).list_all()) == 1
        assert len(DuckDBCandidateModelRepository(engine2).list_all()) == 1
        assert len(DuckDBEvaluationRepository(engine2).list_all()) == 1
        assert len(DuckDBLearningExperimentRepository(engine2).list_all()) == 1
        engine2.close()

    def test_pipeline_lineage_is_sql_joinable_in_one_catalog(self, tmp_path) -> None:
        journal, records = build_journal_with_closed_trades(15)
        result = run_learning_pipeline(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1))

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        DuckDBTrainingDatasetRepository(engine).record(result.dataset_result.dataset)
        DuckDBCandidateModelRepository(engine).record(result.candidate)
        DuckDBEvaluationRepository(engine).record(result.evaluation)
        DuckDBLearningExperimentRepository(engine).record(result.experiment)

        rows = engine.connection.execute(
            "SELECT x.experiment_id, x.status, d.sample_count, c.trainer_version, e.evaluator_version "
            "FROM learning_experiments x "
            "JOIN training_datasets d ON d.dataset_version = x.dataset_version "
            "JOIN candidate_models c ON c.candidate_id = x.candidate_id "
            "JOIN evaluation_results e ON e.evaluation_id = x.evaluation_id "
            "LIMIT 5"
        ).fetchall()
        assert isinstance(rows, list)  # the four-way join executes -- all tables share one catalog
        assert len(rows) == 1
        engine.close()

    def test_two_independent_pipeline_runs_do_not_collide_in_storage(self, tmp_path) -> None:
        """Regression test: each pipeline run constructs its own
        in-process id allocators (DatasetIdAllocator, trainer, evaluator,
        LearningExperimentTracker), all restarting their "...-000001"
        counters -- the storage layer must not collide on primary keys
        across independent runs (the same class of bug Phase 4 already
        fixed for ExperienceRecord.experience_id)."""
        journal1, records1 = build_journal_with_closed_trades(10, start=utc(2024, 1, 2))
        journal2, records2 = build_journal_with_closed_trades(10, start=utc(2024, 6, 1))

        result1 = run_learning_pipeline(journal1, records1, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1))
        result2 = run_learning_pipeline(journal2, records2, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 8, 1))

        assert result1.dataset_result.dataset.dataset_id == result2.dataset_result.dataset.dataset_id  # both "TDS-000001" before storage
        assert result1.candidate.candidate_id == result2.candidate.candidate_id  # both "CAND-000001" before storage

        engine = StorageEngine(StorageConfig(tmp_path / "store"))
        ds_repo = DuckDBTrainingDatasetRepository(engine)
        cand_repo = DuckDBCandidateModelRepository(engine)

        stored1 = ds_repo.record(result1.dataset_result.dataset)
        stored2 = ds_repo.record(result2.dataset_result.dataset)
        assert stored1.dataset_id != stored2.dataset_id
        assert len(ds_repo.list_all()) == 2

        stored_cand1 = cand_repo.record(result1.candidate)
        stored_cand2 = cand_repo.record(result2.candidate)
        assert stored_cand1.candidate_id != stored_cand2.candidate_id
        assert len(cand_repo.list_all()) == 2
        engine.close()
