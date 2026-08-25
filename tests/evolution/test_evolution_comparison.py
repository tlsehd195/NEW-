"""Category: Model Comparison Test -- ranking multiple candidates
evaluated on the same dataset, never declaring a "winner"/deployment
verdict."""

from __future__ import annotations

import pytest

from evolution_helpers import build_dataset, utc

from evolution.comparison import compare_candidates
from evolution.pipeline import evaluate_candidate_batch, generate_candidate_batch
from evolution.trainer import TrailingWindowMeanTrainer

from learning.trainer import MeanRewardBaselineTrainer


def _evaluations(count: int = 15):
    result = build_dataset(count)
    trainers = [
        MeanRewardBaselineTrainer(),
        TrailingWindowMeanTrainer(window=2),
        TrailingWindowMeanTrainer(window=5),
    ]
    candidates = generate_candidate_batch(result.dataset, result.labeled_samples, trainers, trained_at=utc(2024, 3, 1))
    return evaluate_candidate_batch(candidates, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1)), result


class TestCompareCandidates:
    def test_ranks_all_candidates(self) -> None:
        evaluations, _ = _evaluations()
        comparison = compare_candidates(evaluations, comparison_id="CMP-000001", compared_at=utc(2024, 3, 1))
        assert set(comparison.ranked_candidate_ids) == {e.candidate_id for e in evaluations}
        assert comparison.ranking_metric == "test_mean_absolute_error"

    def test_ranking_is_ascending_by_metric(self) -> None:
        evaluations, _ = _evaluations()
        comparison = compare_candidates(evaluations, comparison_id="CMP-000002", compared_at=utc(2024, 3, 1))
        by_id = {e.candidate_id: e.test_metrics.mean_absolute_error for e in evaluations}
        values = [by_id[cid] for cid in comparison.ranked_candidate_ids]
        assert values == sorted(values)

    def test_has_no_winner_or_is_better_field(self) -> None:
        import dataclasses

        from evolution.models import CandidateComparison

        field_names = {f.name for f in dataclasses.fields(CandidateComparison)}
        assert "winner" not in field_names
        assert "is_better" not in field_names
        assert "champion" not in field_names

    def test_requires_at_least_one_evaluation(self) -> None:
        with pytest.raises(ValueError):
            compare_candidates([], comparison_id="CMP-000003", compared_at=utc(2024, 3, 1))

    def test_rejects_mismatched_datasets(self) -> None:
        evaluations_a, _ = _evaluations(15)
        evaluations_b, _ = _evaluations(25)
        with pytest.raises(ValueError):
            compare_candidates(
                [evaluations_a[0], evaluations_b[0]], comparison_id="CMP-000004", compared_at=utc(2024, 3, 1)
            )

    def test_rejects_unsupported_metric(self) -> None:
        evaluations, _ = _evaluations()
        with pytest.raises(ValueError):
            compare_candidates(evaluations, comparison_id="CMP-000005", compared_at=utc(2024, 3, 1), metric="not_a_real_metric")

    def test_deterministic_ranking(self) -> None:
        evaluations, _ = _evaluations()
        c1 = compare_candidates(evaluations, comparison_id="CMP-000006", compared_at=utc(2024, 3, 1))
        c2 = compare_candidates(evaluations, comparison_id="CMP-000006", compared_at=utc(2024, 3, 1))
        assert c1.ranked_candidate_ids == c2.ranked_candidate_ids
