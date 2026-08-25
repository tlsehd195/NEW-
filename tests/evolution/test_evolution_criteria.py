"""Category: Validation Test -- the CANDIDATE -> BACKTESTED -> VALIDATED
-> OOS_TESTED status-transition gate: strict order, referential
integrity, explicit numeric criteria, never reaching APPROVED/DEPLOYED,
never silently dropping a failed attempt."""

from __future__ import annotations

import dataclasses

import pytest

from evolution_helpers import build_dataset, utc

from evolution.config import PromotionConfig
from evolution.criteria import CRITERIA_VERSION, evaluate_transition, next_status

from learning.evaluation import Evaluator
from learning.enums import CandidateModelStatus
from learning.trainer import MeanRewardBaselineTrainer


def _candidate_and_evaluation(count: int = 20):
    result = build_dataset(count)
    candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
    evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
    return candidate, evaluation, result


class TestNextStatus:
    def test_full_chain(self) -> None:
        assert next_status(CandidateModelStatus.CANDIDATE) == CandidateModelStatus.BACKTESTED
        assert next_status(CandidateModelStatus.BACKTESTED) == CandidateModelStatus.VALIDATED
        assert next_status(CandidateModelStatus.VALIDATED) == CandidateModelStatus.OOS_TESTED

    def test_no_transition_past_oos_tested(self) -> None:
        with pytest.raises(ValueError):
            next_status(CandidateModelStatus.OOS_TESTED)

    def test_never_returns_approved_or_deployed(self) -> None:
        for status in CandidateModelStatus:
            try:
                result = next_status(status)
            except ValueError:
                continue
            assert result not in (CandidateModelStatus.APPROVED, CandidateModelStatus.DEPLOYED)


class TestEvaluateTransitionHappyPath:
    def test_candidate_to_backtested_passes_with_sufficient_data(self) -> None:
        candidate, evaluation, _ = _candidate_and_evaluation(20)
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000001", evaluated_at=utc(2024, 3, 1),
        )
        assert transition.passed is True
        assert transition.to_status == CandidateModelStatus.BACKTESTED
        assert transition.reason == "all_criteria_met"

    def test_full_chain_can_reach_oos_tested(self) -> None:
        candidate, evaluation, _ = _candidate_and_evaluation(30)
        config = PromotionConfig(min_validation_sample_count=1, min_test_sample_count=1)
        t1 = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, config,
            transition_id="TRANS-000010", evaluated_at=utc(2024, 3, 1),
        )
        assert t1.passed
        t2 = evaluate_transition(
            candidate, evaluation, t1.to_status, config,
            transition_id="TRANS-000011", evaluated_at=utc(2024, 3, 1),
        )
        assert t2.passed
        t3 = evaluate_transition(
            candidate, evaluation, t2.to_status, config,
            transition_id="TRANS-000012", evaluated_at=utc(2024, 3, 1),
        )
        assert t3.passed
        assert t3.to_status == CandidateModelStatus.OOS_TESTED


class TestEvaluateTransitionFailure:
    def test_insufficient_validation_samples_fails_but_is_still_recorded(self) -> None:
        candidate, evaluation, _ = _candidate_and_evaluation(6)
        config = PromotionConfig(min_validation_sample_count=1000)
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.BACKTESTED, config,
            transition_id="TRANS-000020", evaluated_at=utc(2024, 3, 1),
        )
        assert transition.passed is False
        assert "validation_sample_count_sufficient" in transition.reason
        assert transition.criteria["validation_sample_count_sufficient"] is False

    def test_mismatched_evaluation_fails_referential_check(self) -> None:
        candidate, _, _ = _candidate_and_evaluation(20)
        _, other_evaluation, _ = _candidate_and_evaluation(21)  # a different dataset -> different dataset_version
        transition = evaluate_transition(
            candidate, other_evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000021", evaluated_at=utc(2024, 3, 1),
        )
        assert transition.passed is False
        assert transition.reason == "evaluation_matches_candidate"

    def test_never_produces_out_of_order_transition(self) -> None:
        with pytest.raises(ValueError):
            evaluate_transition(
                *_candidate_and_evaluation(20)[:2], CandidateModelStatus.OOS_TESTED, PromotionConfig(),
                transition_id="TRANS-000022", evaluated_at=utc(2024, 3, 1),
            )


class TestComparativeBaselineBar:
    def test_optional_baseline_ratio_can_fail_oos_gate(self) -> None:
        candidate, evaluation, _ = _candidate_and_evaluation(30)
        impossible_config = PromotionConfig(max_test_mae_over_baseline_ratio=1e-12)
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.VALIDATED, impossible_config,
            transition_id="TRANS-000030", evaluated_at=utc(2024, 3, 1),
        )
        assert transition.passed is False
        assert "test_mae_within_baseline_bar" in transition.reason

    def test_default_config_has_no_comparative_bar(self) -> None:
        assert PromotionConfig().max_test_mae_over_baseline_ratio is None


class TestStructuralBoundary:
    def test_transition_is_frozen(self) -> None:
        candidate, evaluation, _ = _candidate_and_evaluation(20)
        transition = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000040", evaluated_at=utc(2024, 3, 1),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            transition.passed = False

    def test_criteria_version_is_stable(self) -> None:
        assert CRITERIA_VERSION == "promotion_criteria_v1"
