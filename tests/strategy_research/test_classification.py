"""Category: Candidate classification (instruction sections 28, 38, 47).
`classify_candidate` must never return PROMISING_CANDIDATE or REJECTED
from synthetic/pipeline-only evaluation data, and the enum itself must
structurally have no VERIFIED_ALPHA/PROVEN_ALPHA member to assign."""

from __future__ import annotations

from strategy_research.classification import CandidateClassification, PromisingCriteria, classify_candidate


class TestNoAlphaClassification:
    def test_enum_has_no_proven_or_verified_alpha_member(self) -> None:
        member_names = {m.name for m in CandidateClassification}
        assert member_names == {"REJECTED", "INCONCLUSIVE", "PROMISING_CANDIDATE"}
        assert "PROVEN_ALPHA" not in member_names
        assert "VERIFIED_ALPHA" not in member_names


class TestClassifyCandidate:
    def test_all_criteria_true_but_no_real_data_is_inconclusive(self) -> None:
        criteria = PromisingCriteria(
            meaningful_vs_benchmark=True, survives_costs=True, has_out_of_sample_result=True,
            consistent_across_periods=True, not_single_symbol_dependent=True,
            not_overly_parameter_sensitive=True, reasonable_turnover=True, acceptable_drawdown=True,
        )
        result = classify_candidate(criteria, has_real_evaluation_data=False)
        assert result == CandidateClassification.INCONCLUSIVE

    def test_all_criteria_true_with_real_data_is_promising(self) -> None:
        criteria = PromisingCriteria(
            meaningful_vs_benchmark=True, survives_costs=True, has_out_of_sample_result=True,
            consistent_across_periods=True, not_single_symbol_dependent=True,
            not_overly_parameter_sensitive=True, reasonable_turnover=True, acceptable_drawdown=True,
        )
        result = classify_candidate(criteria, has_real_evaluation_data=True)
        assert result == CandidateClassification.PROMISING_CANDIDATE

    def test_one_criterion_false_with_real_data_is_inconclusive_not_promising(self) -> None:
        criteria = PromisingCriteria(
            meaningful_vs_benchmark=True, survives_costs=False, has_out_of_sample_result=True,
            consistent_across_periods=True, not_single_symbol_dependent=True,
            not_overly_parameter_sensitive=True, reasonable_turnover=True, acceptable_drawdown=True,
        )
        result = classify_candidate(criteria, has_real_evaluation_data=True)
        assert result == CandidateClassification.INCONCLUSIVE
        assert "survives_costs" in criteria.failing_criteria()

    def test_unevaluated_criterion_is_inconclusive(self) -> None:
        criteria = PromisingCriteria(meaningful_vs_benchmark=True)  # rest default to None
        result = classify_candidate(criteria, has_real_evaluation_data=True)
        assert result == CandidateClassification.INCONCLUSIVE

    def test_explicit_rejection_reason_forces_rejected_even_with_real_data(self) -> None:
        criteria = PromisingCriteria()
        result = classify_candidate(criteria, has_real_evaluation_data=True, explicit_rejection_reason="negative net-of-cost CAGR")
        assert result == CandidateClassification.REJECTED
