"""Category: Persistence Test -- ModelStatusTransitionRepository natural
key discipline (Phase 11 spec section 9)."""

from __future__ import annotations

import dataclasses

from evolution_helpers import build_dataset, utc

from evolution.config import PromotionConfig
from evolution.criteria import evaluate_transition
from evolution.repository import InMemoryModelStatusTransitionRepository

from learning.enums import CandidateModelStatus
from learning.evaluation import Evaluator
from learning.trainer import MeanRewardBaselineTrainer


def _candidate_and_evaluation():
    result = build_dataset(20)
    candidate = MeanRewardBaselineTrainer().train(result.dataset, result.labeled_samples, trained_at=utc(2024, 3, 1))
    evaluation = Evaluator().evaluate(candidate, result.dataset, result.labeled_samples, evaluated_at=utc(2024, 3, 1))
    return candidate, evaluation


class TestNaturalKeyIncludesPassed:
    """Session 37 (ADR-0115, external review N-9): before this fix, the
    natural key omitted `passed` -- a candidate that FAILED a transition
    once and later PASSED the identical (candidate_id, from_status,
    to_status, criteria_version) transition on a retry (still against
    the same criteria_version, e.g. after a fix) collided with the
    earlier failed attempt's key and was silently discarded, contrary
    to this Protocol's own docstring."""

    def test_a_later_passing_retry_is_not_discarded_by_an_earlier_failed_attempt(self) -> None:
        candidate, evaluation = _candidate_and_evaluation()
        repo = InMemoryModelStatusTransitionRepository()

        failing = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000001", evaluated_at=utc(2024, 3, 1),
        )
        # Force a FAILED first attempt sharing every other key field with
        # the later passing one (mirrors "retried after a fix, same
        # criteria_version").
        failing = dataclasses.replace(failing, passed=False, reason="forced_failure_for_test")
        repo.record(failing)
        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.CANDIDATE

        passing = evaluate_transition(
            candidate, evaluation, CandidateModelStatus.CANDIDATE, PromotionConfig(),
            transition_id="TRANS-000002", evaluated_at=utc(2024, 3, 2),
        )
        assert passing.passed is True
        repo.record(passing)

        # The bug: without the fix, this stays CANDIDATE forever -- the
        # passing transition was silently dropped as a "duplicate" of
        # the earlier failed one.
        assert repo.get_current_status(candidate.candidate_id) == CandidateModelStatus.BACKTESTED
        assert len(repo.get_history(candidate.candidate_id)) == 2
