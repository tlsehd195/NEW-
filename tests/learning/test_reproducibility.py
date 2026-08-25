"""Category: Reproducibility Test -- same dataset/config/seed produce
the same result (Phase 9 spec section 17, instruction section 17).
"""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset
from learning.evaluation import Evaluator
from learning.pipeline import run_learning_pipeline
from learning.trainer import MeanRewardBaselineTrainer

from trade_journal.enums import TradeProvenance


class TestReproducibleDataset:
    def test_same_records_and_config_produce_an_identical_dataset(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        r1 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        r2 = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        assert r1.dataset.dataset_version == r2.dataset.dataset_version
        assert r1.dataset.splits == r2.dataset.splits
        assert [s.label_value for s in r1.labeled_samples] == [s.label_value for s in r2.labeled_samples]


class TestReproducibleTraining:
    def test_same_dataset_and_seed_produce_the_same_candidate_parameters(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        c1 = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1), seed=7)
        c2 = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1), seed=7)
        assert c1.parameters == c2.parameters
        assert c1.trainer_version == c2.trainer_version


class TestReproducibleEvaluation:
    def test_same_candidate_and_dataset_produce_the_same_metrics(self) -> None:
        journal, records = build_journal_with_closed_trades(10)
        result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        e1 = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        e2 = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert e1.train_metrics == e2.train_metrics
        assert e1.test_metrics == e2.test_metrics
        assert e1.baseline_metrics == e2.baseline_metrics


class TestReproducibleFullPipeline:
    def test_same_inputs_produce_the_same_pipeline_result_content(self) -> None:
        journal, records = build_journal_with_closed_trades(12)
        p1 = run_learning_pipeline(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1), seed=1)
        p2 = run_learning_pipeline(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, run_at=utc(2024, 3, 1), seed=1)
        assert p1.dataset_result.dataset.dataset_version == p2.dataset_result.dataset.dataset_version
        assert p1.candidate.parameters == p2.candidate.parameters
        assert p1.evaluation.train_metrics == p2.evaluation.train_metrics
        assert p1.experiment.status == p2.experiment.status

    def test_no_randomness_module_is_used_anywhere_in_learning_package(self) -> None:
        import ast
        from pathlib import Path

        import learning

        package_dir = Path(learning.__file__).parent
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name != "random", f"{py_file.name} imports random"
                if isinstance(node, ast.ImportFrom) and node.module == "random":
                    raise AssertionError(f"{py_file.name} imports from random")
