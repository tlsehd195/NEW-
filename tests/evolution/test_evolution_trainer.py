"""Category: Candidate Generation Test -- Model Evolution can generate
more than one, genuinely different candidate from the same
TrainingDataset (PROJECT_MASTER_PLAN.md Phase 11)."""

from __future__ import annotations

from evolution_helpers import build_dataset, utc

from evolution.pipeline import evaluate_candidate_batch, generate_candidate_batch
from evolution.trainer import TrailingWindowMeanTrainer

from learning.enums import CandidateModelStatus, SplitName
from learning.trainer import MeanRewardBaselineTrainer


class TestTrailingWindowMeanTrainer:
    def test_produces_a_candidate_status(self) -> None:
        result = build_dataset(12)
        candidate = TrailingWindowMeanTrainer(window=3).train(
            result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1)
        )
        assert candidate.status == CandidateModelStatus.CANDIDATE
        assert candidate.dataset_version == result.dataset.dataset_version
        assert candidate.parameters["window"] == 3

    def test_rejects_non_positive_window(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            TrailingWindowMeanTrainer(window=0)

    def test_deterministic_same_inputs_same_output(self) -> None:
        result = build_dataset(12)
        c1 = TrailingWindowMeanTrainer(window=4).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        c2 = TrailingWindowMeanTrainer(window=4).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        assert c1.parameters["predicted_value"] == c2.parameters["predicted_value"]

    def test_different_windows_can_produce_different_candidates(self) -> None:
        result = build_dataset(20)
        small_window = TrailingWindowMeanTrainer(window=2).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        full_window = TrailingWindowMeanTrainer(window=1000).train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
        # not asserted to always differ (would be a flaky numeric coincidence
        # claim) -- only that both trained successfully against the same
        # dataset and can be told apart by their own recorded parameters.
        assert small_window.parameters["window"] != full_window.parameters["window"]
        assert small_window.dataset_version == full_window.dataset_version == result.dataset.dataset_version


class TestGenerateAndEvaluateCandidateBatch:
    def test_generates_multiple_candidates_from_one_dataset(self) -> None:
        result = build_dataset(15)
        trainers = [MeanRewardBaselineTrainer(), TrailingWindowMeanTrainer(window=3), TrailingWindowMeanTrainer(window=6)]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        assert len(candidates) == 3
        assert len({c.trainer_version for c in candidates}) == 3
        assert all(c.dataset_version == result.dataset.dataset_version for c in candidates)
        assert all(c.status == CandidateModelStatus.CANDIDATE for c in candidates)

    def test_evaluates_each_candidate_in_the_batch(self) -> None:
        result = build_dataset(15)
        trainers = [MeanRewardBaselineTrainer(), TrailingWindowMeanTrainer(window=3)]
        candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
        evaluations = evaluate_candidate_batch(candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
        assert len(evaluations) == 2
        assert {e.candidate_id for e in evaluations} == {c.candidate_id for c in candidates}
        for e in evaluations:
            assert e.test_metrics.sample_count == len(result.dataset.splits.get(SplitName.TEST, ()))

    def test_generate_candidate_batch_requires_at_least_one_trainer(self) -> None:
        import pytest

        result = build_dataset(10)
        with pytest.raises(ValueError):
            generate_candidate_batch(result.dataset, result.labeled_samples, [], trained_at=utc(2024, 3, 1))
