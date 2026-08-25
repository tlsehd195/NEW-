"""compare_candidates: ranks a set of candidates evaluated on the same
`TrainingDataset` by one explicitly named metric.

See docs/specifications/PHASE-11-model-evolution.md section 7.

This is Model Evolution's "candidate comparison" step
(PROJECT_MASTER_PLAN.md section 3's Validation/Evaluation module
responsibility) -- it produces an ordering for research review, never a
"winner"/deployment decision (the same discipline
`learning.evaluation.Evaluator` already established by never setting a
`candidate_is_better` field, Phase 9 spec section 13-14). Comparing
candidates trained/evaluated on different datasets would silently
compare apples to oranges, so it is rejected outright rather than
producing a plausible-looking ranking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from evolution.models import CandidateComparison

from learning.models import EvaluationResult

_SUPPORTED_METRICS = {
    "test_mean_absolute_error": lambda e: e.test_metrics.mean_absolute_error,
    "test_mean_squared_error": lambda e: e.test_metrics.mean_squared_error,
    "validation_mean_absolute_error": lambda e: e.validation_metrics.mean_absolute_error,
}


def compare_candidates(
    evaluations: Sequence[EvaluationResult],
    *,
    comparison_id: str,
    compared_at: datetime,
    metric: str = "test_mean_absolute_error",
) -> CandidateComparison:
    if not evaluations:
        raise ValueError("compare_candidates requires at least one EvaluationResult")
    if metric not in _SUPPORTED_METRICS:
        raise ValueError(f"unsupported ranking_metric {metric!r}; supported: {sorted(_SUPPORTED_METRICS)}")

    dataset_ids = {e.dataset_id for e in evaluations}
    dataset_versions = {e.dataset_version for e in evaluations}
    if len(dataset_ids) != 1 or len(dataset_versions) != 1:
        raise ValueError(
            "compare_candidates requires every EvaluationResult to share the same "
            "dataset_id and dataset_version -- comparing candidates evaluated on "
            "different datasets is not a meaningful ranking"
        )

    extractor = _SUPPORTED_METRICS[metric]
    candidate_ids = tuple(e.candidate_id for e in evaluations)

    def sort_key(evaluation: EvaluationResult) -> tuple[float, str]:
        value: Optional[float] = extractor(evaluation)
        # a missing/non-finite metric sorts last -- never treated as
        # "best" by defaulting to 0 or some other favorable placeholder
        rank_value = value if value is not None and value == value else float("inf")
        return (rank_value, evaluation.candidate_id)

    ranked = tuple(e.candidate_id for e in sorted(evaluations, key=sort_key))

    return CandidateComparison(
        comparison_id=comparison_id,
        dataset_id=next(iter(dataset_ids)),
        dataset_version=next(iter(dataset_versions)),
        candidate_ids=candidate_ids,
        ranking_metric=metric,
        ranked_candidate_ids=ranked,
        compared_at=compared_at,
    )
