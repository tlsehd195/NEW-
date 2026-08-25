"""Candidate status-transition gate: advances
`learning.enums.CandidateModelStatus` through
`CANDIDATE -> BACKTESTED -> VALIDATED -> OOS_TESTED` under explicit,
versioned, numeric criteria -- never automatically, never past
`OOS_TESTED` (`APPROVED`/`DEPLOYED` require a human approval step this
module cannot perform, PROJECT_MASTER_PLAN.md section 11.5).

See docs/specifications/PHASE-11-model-evolution.md section 5.

A failing evaluation is never silently dropped -- `evaluate_transition`
always returns a `ModelStatusTransition` record, with `passed=False` and
the specific failed check(s) named in `reason`, mirroring
`learning.cleaning.DataCleaner`'s "never silently drop a sample"
discipline (Phase 9) applied to status transitions instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from evolution.config import PromotionConfig
from evolution.models import ModelStatusTransition

from learning.enums import CandidateModelStatus, SplitName
from learning.models import CandidateModelArtifact, EvaluationMetrics, EvaluationResult

CRITERIA_VERSION = "promotion_criteria_v1"

# The only transitions this module can ever produce. APPROVED/DEPLOYED
# are deliberately absent -- there is no key in this table that maps to
# either (tests/evolution/test_evolution_boundary.py verifies this by
# reflection, not just by reading this comment).
_NEXT_STATUS: dict[CandidateModelStatus, CandidateModelStatus] = {
    CandidateModelStatus.CANDIDATE: CandidateModelStatus.BACKTESTED,
    CandidateModelStatus.BACKTESTED: CandidateModelStatus.VALIDATED,
    CandidateModelStatus.VALIDATED: CandidateModelStatus.OOS_TESTED,
}


def next_status(current: CandidateModelStatus) -> CandidateModelStatus:
    """The only status `evaluate_transition` may attempt to move a
    candidate into from `current`. Raises for `OOS_TESTED` and beyond --
    this module performs no further automated transition past
    out-of-sample testing."""
    try:
        return _NEXT_STATUS[current]
    except KeyError:
        raise ValueError(
            f"no automated transition exists from {current.value} -- "
            "APPROVED/DEPLOYED require human approval (PROJECT_MASTER_PLAN.md section 11.5)"
        ) from None


def _metrics_for(evaluation: EvaluationResult, split: SplitName) -> EvaluationMetrics:
    return {
        SplitName.TRAIN: evaluation.train_metrics,
        SplitName.VALIDATION: evaluation.validation_metrics,
        SplitName.TEST: evaluation.test_metrics,
    }[split]


def _finite(value: Optional[float]) -> bool:
    if value is None:
        return False
    return value == value and value not in (float("inf"), float("-inf"))  # NaN != NaN


def evaluate_transition(
    candidate: CandidateModelArtifact,
    evaluation: EvaluationResult,
    current_status: CandidateModelStatus,
    config: PromotionConfig,
    *,
    transition_id: str,
    evaluated_at: datetime,
) -> ModelStatusTransition:
    """Attempts to move `candidate` from `current_status` to
    `next_status(current_status)`. `evaluation` must be the
    `EvaluationResult` computed for this exact `candidate` against its
    own `dataset_version` -- referential mismatch is itself a failing
    criterion, not a silently-ignored input (checked first, before any
    metric is read)."""
    to_status = next_status(current_status)
    checks: dict = {}

    referential_ok = (
        evaluation.candidate_id == candidate.candidate_id
        and evaluation.dataset_version == candidate.dataset_version
    )
    checks["evaluation_matches_candidate"] = referential_ok

    if not referential_ok:
        return ModelStatusTransition(
            transition_id=transition_id,
            candidate_id=candidate.candidate_id,
            dataset_id=candidate.dataset_id,
            dataset_version=candidate.dataset_version,
            evaluation_id=evaluation.evaluation_id,
            from_status=current_status,
            to_status=to_status,
            passed=False,
            criteria_version=CRITERIA_VERSION,
            criteria=checks,
            reason="evaluation_matches_candidate",
            provenance=candidate.provenance,
            evaluated_at=evaluated_at,
        )

    if to_status == CandidateModelStatus.BACKTESTED:
        # A candidate is "backtested" once it has produced usable,
        # finite metrics over the split it was actually trained on --
        # proof the train -> evaluate chain ran end to end without a
        # degenerate/empty result.
        train_metrics = _metrics_for(evaluation, SplitName.TRAIN)
        checks["train_sample_count"] = train_metrics.sample_count
        checks["train_sample_count_positive"] = train_metrics.sample_count > 0
        checks["train_mae_finite"] = _finite(train_metrics.mean_absolute_error)
        checks["train_mse_finite"] = _finite(train_metrics.mean_squared_error)
        passed = checks["train_sample_count_positive"] and checks["train_mae_finite"] and checks["train_mse_finite"]

    elif to_status == CandidateModelStatus.VALIDATED:
        val_metrics = _metrics_for(evaluation, SplitName.VALIDATION)
        checks["validation_sample_count"] = val_metrics.sample_count
        checks["validation_sample_count_sufficient"] = val_metrics.sample_count >= config.min_validation_sample_count
        checks["validation_mae_finite"] = _finite(val_metrics.mean_absolute_error)
        checks["validation_mse_finite"] = _finite(val_metrics.mean_squared_error)
        passed = (
            checks["validation_sample_count_sufficient"]
            and checks["validation_mae_finite"]
            and checks["validation_mse_finite"]
        )

    else:  # OOS_TESTED
        test_metrics = _metrics_for(evaluation, SplitName.TEST)
        checks["test_sample_count"] = test_metrics.sample_count
        checks["test_sample_count_sufficient"] = test_metrics.sample_count >= config.min_test_sample_count
        checks["test_mae_finite"] = _finite(test_metrics.mean_absolute_error)
        checks["test_mse_finite"] = _finite(test_metrics.mean_squared_error)
        passed = checks["test_sample_count_sufficient"] and checks["test_mae_finite"] and checks["test_mse_finite"]

        if passed and config.max_test_mae_over_baseline_ratio is not None:
            baseline_mae = evaluation.baseline_metrics.mean_absolute_error
            checks["baseline_mae_finite"] = _finite(baseline_mae)
            if _finite(baseline_mae) and _finite(test_metrics.mean_absolute_error):
                bar = baseline_mae * config.max_test_mae_over_baseline_ratio
                checks["test_mae_within_baseline_bar"] = test_metrics.mean_absolute_error <= bar
                passed = passed and checks["test_mae_within_baseline_bar"]
            else:
                checks["test_mae_within_baseline_bar"] = False
                passed = False

    failed_checks = sorted(name for name, value in checks.items() if value is False)
    reason = "all_criteria_met" if passed else ";".join(failed_checks)

    return ModelStatusTransition(
        transition_id=transition_id,
        candidate_id=candidate.candidate_id,
        dataset_id=candidate.dataset_id,
        dataset_version=candidate.dataset_version,
        evaluation_id=evaluation.evaluation_id,
        from_status=current_status,
        to_status=to_status,
        passed=passed,
        criteria_version=CRITERIA_VERSION,
        criteria=checks,
        reason=reason,
        provenance=candidate.provenance,
        evaluated_at=evaluated_at,
    )
