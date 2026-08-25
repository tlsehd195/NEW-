"""Category: Persistence Test -- save, reload, idempotency for the
persistent Learning Engine stores (Phase 9 spec section 15)."""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc
from storage_helpers import new_engine

from learning.dataset import build_training_dataset
from learning.pipeline import run_learning_pipeline

from storage.learning_repository import (
    DuckDBCandidateModelRepository,
    DuckDBEvaluationRepository,
    DuckDBLearningExperimentRepository,
    DuckDBTrainingDatasetRepository,
)

from trade_journal.enums import TradeProvenance


def _pipeline_result(count: int = 10):
    journal, records = build_journal_with_closed_trades(count)
    return run_learning_pipeline(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1))


class TestPersistenceAndRestart:
    def test_full_pipeline_result_survives_restart(self, tmp_path) -> None:
        result = _pipeline_result()

        engine1 = new_engine(tmp_path)
        ds_repo1 = DuckDBTrainingDatasetRepository(engine1)
        cand_repo1 = DuckDBCandidateModelRepository(engine1)
        eval_repo1 = DuckDBEvaluationRepository(engine1)
        exp_repo1 = DuckDBLearningExperimentRepository(engine1)

        ds_repo1.record(result.dataset_result.dataset)
        cand_repo1.record(result.candidate)
        eval_repo1.record(result.evaluation)
        exp_repo1.record(result.experiment)
        engine1.close()

        engine2 = new_engine(tmp_path)
        ds_repo2 = DuckDBTrainingDatasetRepository(engine2)
        cand_repo2 = DuckDBCandidateModelRepository(engine2)
        eval_repo2 = DuckDBEvaluationRepository(engine2)
        exp_repo2 = DuckDBLearningExperimentRepository(engine2)

        reloaded_ds = ds_repo2.get(result.dataset_result.dataset.dataset_id)
        assert reloaded_ds is not None
        assert reloaded_ds.splits == result.dataset_result.dataset.splits
        assert reloaded_ds.sample_count == result.dataset_result.dataset.sample_count

        reloaded_cand = cand_repo2.get(result.candidate.candidate_id)
        assert reloaded_cand is not None
        assert reloaded_cand.parameters == result.candidate.parameters

        reloaded_eval = eval_repo2.get(result.evaluation.evaluation_id)
        assert reloaded_eval is not None
        assert reloaded_eval.train_metrics == result.evaluation.train_metrics

        reloaded_exp = exp_repo2.get(result.experiment.experiment_id)
        assert reloaded_exp is not None
        assert reloaded_exp.status == result.experiment.status
        engine2.close()


class TestIdempotency:
    def test_recording_the_same_dataset_twice_does_not_duplicate(self, tmp_path) -> None:
        result = _pipeline_result()
        engine = new_engine(tmp_path)
        repo = DuckDBTrainingDatasetRepository(engine)
        d1 = repo.record(result.dataset_result.dataset)
        d2 = repo.record(result.dataset_result.dataset)
        assert d1.dataset_id == d2.dataset_id
        assert len(repo.list_all()) == 1
        engine.close()

    def test_recording_the_same_candidate_twice_does_not_duplicate(self, tmp_path) -> None:
        result = _pipeline_result()
        engine = new_engine(tmp_path)
        repo = DuckDBCandidateModelRepository(engine)
        c1 = repo.record(result.candidate)
        c2 = repo.record(result.candidate)
        assert c1.candidate_id == c2.candidate_id
        assert len(repo.list_all()) == 1
        engine.close()

    def test_recording_the_same_evaluation_twice_does_not_duplicate(self, tmp_path) -> None:
        result = _pipeline_result()
        engine = new_engine(tmp_path)
        repo = DuckDBEvaluationRepository(engine)
        e1 = repo.record(result.evaluation)
        e2 = repo.record(result.evaluation)
        assert e1.evaluation_id == e2.evaluation_id
        assert len(repo.list_all()) == 1
        engine.close()

    def test_recording_the_same_learning_experiment_twice_does_not_duplicate(self, tmp_path) -> None:
        result = _pipeline_result()
        engine = new_engine(tmp_path)
        repo = DuckDBLearningExperimentRepository(engine)
        x1 = repo.record(result.experiment)
        x2 = repo.record(result.experiment)
        assert x1.experiment_id == x2.experiment_id
        assert len(repo.list_all()) == 1
        engine.close()

    def test_rebuilding_the_identical_dataset_and_recording_again_is_idempotent(self, tmp_path) -> None:
        journal, records = build_journal_with_closed_trades(8)
        engine = new_engine(tmp_path)
        repo = DuckDBTrainingDatasetRepository(engine)

        r1 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        r2 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        repo.record(r1.dataset)
        repo.record(r2.dataset)
        assert len(repo.list_all()) == 1
        engine.close()


class TestPointInTimeMetadataPersisted:
    def test_as_of_cutoff_round_trips(self, tmp_path) -> None:
        journal, records = build_journal_with_closed_trades(10)
        cutoff = utc(2024, 1, 6)
        result = build_training_dataset(
            journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, as_of_cutoff=cutoff, created_at=utc(2024, 3, 1),
        )
        engine = new_engine(tmp_path)
        repo = DuckDBTrainingDatasetRepository(engine)
        repo.record(result.dataset)
        reloaded = repo.get_by_version(result.dataset.dataset_version)
        assert reloaded.as_of_cutoff == cutoff
        engine.close()


class TestProvenanceFilter:
    def test_list_all_filters_by_provenance(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBTrainingDatasetRepository(engine)

        journal_hist, hist_records = build_journal_with_closed_trades(4, provenance=TradeProvenance.HISTORICAL_SIMULATION)
        journal_paper, paper_records = build_journal_with_closed_trades(4, provenance=TradeProvenance.PAPER_TRADING)
        hist_result = build_training_dataset(journal_hist, hist_records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        paper_result = build_training_dataset(journal_paper, paper_records, provenance=TradeProvenance.PAPER_TRADING, created_at=utc(2024, 3, 1))
        repo.record(hist_result.dataset)
        repo.record(paper_result.dataset)

        assert len(repo.list_all(provenance=TradeProvenance.HISTORICAL_SIMULATION)) == 1
        assert len(repo.list_all(provenance=TradeProvenance.PAPER_TRADING)) == 1
        assert len(repo.list_all(provenance=TradeProvenance.LIVE_TRADING)) == 0
        engine.close()
