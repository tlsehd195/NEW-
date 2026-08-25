"""Category: Unit Test -- MeanRewardBaselineTrainer (Phase 9 spec
section 11)."""

from __future__ import annotations

from learning_helpers import build_journal_with_closed_trades, utc

from learning.dataset import build_training_dataset
from learning.enums import CandidateModelStatus, SplitName
from learning.trainer import MeanRewardBaselineTrainer

from trade_journal.enums import TradeProvenance


def _dataset_result(count: int = 10):
    journal, records = build_journal_with_closed_trades(count)
    return build_training_dataset(journal, records, provenance=TradeProvenance.HISTORICAL_SIMULATION, created_at=utc(2024, 3, 1))


class TestCandidateTraining:
    def test_candidate_is_always_status_candidate(self) -> None:
        result = _dataset_result()
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        assert candidate.status == CandidateModelStatus.CANDIDATE

    def test_predicted_value_equals_the_mean_train_split_label(self) -> None:
        result = _dataset_result()
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        train_ids = set(result.dataset.splits[SplitName.TRAIN])
        train_labels = [s.label_value for s in result.labeled_samples if s.trade_id in train_ids]
        expected_mean = sum(train_labels) / len(train_labels)
        assert candidate.parameters["predicted_value"] == expected_mean
        assert candidate.parameters["train_sample_count"] == len(train_labels)

    def test_trainer_never_touches_validation_or_test_samples(self) -> None:
        """Swapping out validation/test labels for wildly different
        values must not change the trained candidate at all -- proving
        the trainer only ever reads the TRAIN split."""
        result = _dataset_result()
        candidate_before = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))

        import dataclasses

        non_train_ids = set(result.dataset.splits[SplitName.VALIDATION]) | set(result.dataset.splits[SplitName.TEST])
        mutated_samples = [
            dataclasses.replace(s, label_value=999.0) if s.trade_id in non_train_ids else s
            for s in result.labeled_samples
        ]
        candidate_after = MeanRewardBaselineTrainer().train(result.dataset, mutated_samples, trained_at=utc(2024, 3, 1))
        assert candidate_before.parameters["predicted_value"] == candidate_after.parameters["predicted_value"]

    def test_lineage_copied_from_dataset(self) -> None:
        result = _dataset_result()
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        assert candidate.dataset_id == result.dataset.dataset_id
        assert candidate.dataset_version == result.dataset.dataset_version
        assert candidate.label_version == result.dataset.label_version
        assert candidate.provenance == result.dataset.provenance

    def test_seed_is_recorded_even_though_unused(self) -> None:
        result = _dataset_result()
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1), seed=42)
        assert candidate.seed == 42

    def test_empty_train_split_does_not_crash(self) -> None:
        result = _dataset_result(count=0)
        candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        assert candidate.parameters["predicted_value"] == 0.0
        assert candidate.parameters["train_sample_count"] == 0
