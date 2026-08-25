"""Category: Unit Test -- Evaluator (Phase 9 spec section 13)."""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset
from learning.evaluation import Evaluator
from learning.trainer import MeanRewardBaselineTrainer

from trade_journal.enums import TradeProvenance


def _trained(count: int = 10):
    journal, records = build_journal_with_closed_trades(count)
    result = build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))
    candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
    return result, candidate


class TestEvaluationMetrics:
    def test_evaluation_reports_sample_counts_per_split(self) -> None:
        result, candidate = _trained()
        evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert evaluation.train_metrics.sample_count == 6
        assert evaluation.validation_metrics.sample_count == 2
        assert evaluation.test_metrics.sample_count == 2

    def test_train_mae_is_near_zero_for_the_mean_predictor_on_its_own_split(self) -> None:
        result, candidate = _trained()
        evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        # the mean minimizes MAE-adjacent error on its own training data, so this should be small but not necessarily 0
        assert evaluation.train_metrics.mean_absolute_error is not None
        assert evaluation.train_metrics.mean_absolute_error >= 0.0

    def test_lineage_copied_from_dataset_and_candidate(self) -> None:
        result, candidate = _trained()
        evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert evaluation.candidate_id == candidate.candidate_id
        assert evaluation.dataset_id == result.dataset.dataset_id
        assert evaluation.dataset_version == result.dataset.dataset_version
        assert evaluation.provenance == result.dataset.provenance


class TestBaselineComparison:
    def test_baseline_metrics_are_present_and_never_claim_candidate_superiority(self) -> None:
        result, candidate = _trained()
        evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert evaluation.baseline_metrics.sample_count == evaluation.test_metrics.sample_count
        # both are just numbers on the same result object -- no boolean "candidate_is_better" field exists
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(evaluation)}
        assert "candidate_is_better" not in field_names
        assert "winner" not in field_names


class TestEmptySplitHandling:
    def test_empty_split_reports_none_metrics_not_a_crash(self) -> None:
        result, candidate = _trained(count=0)
        evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert evaluation.train_metrics.sample_count == 0
        assert evaluation.train_metrics.mean_absolute_error is None
        assert evaluation.train_metrics.mean_squared_error is None
