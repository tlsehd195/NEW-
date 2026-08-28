"""Phase 25 evidence-level classification + PBO/DSR applicability tests
(instruction section 24, categories A/B/L/Q + the EvidenceLevel/PBO-DSR
surface itself). SYNTHETIC FIXTURE ONLY where a `WalkForwardAggregate`
is needed -- `classify_evidence_level`'s own `is_real_data` flag is
exactly the mechanism this test suite uses to prove synthetic input can
never produce a real evidence claim, so using synthetic aggregates here
is the correct way to exercise that guarantee, not a violation of it.

Category R (restart persistence): explicitly N/A. Neither
`evidence.py` nor `walk_forward_evaluation.py` adds any new
`DataRepository` persistence -- both are pure computation over data
`DataRepository`/`ResearchLog` already hold in memory. There is nothing
here that could survive or fail to survive a restart.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from strategy_research.classification import CandidateClassification, CandidateEvaluation, PromisingCriteria
from strategy_research.evidence import (
    MIN_DISTINCT_KNOWN_REGIMES_FOR_CANDIDATE,
    MIN_FOLDS_FOR_PRELIMINARY,
    MIN_FOLDS_FOR_ROBUSTNESS,
    MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE,
    EvidenceLevel,
    assess_pbo_dsr_applicability,
    classify_evidence_level,
)
from strategy_research.research_log import ResearchLog
from strategy_research.splits import build_chronological_split
from strategy_research.walk_forward_evaluation import WalkForwardAggregate


def _agg(fold_count: int, positive: int, regimes: dict, median_ret: float = 0.05) -> WalkForwardAggregate:
    return WalkForwardAggregate(
        strategy_name="test_strategy", train_window_months=12, test_window_months=3, step_months=3,
        fold_count=fold_count, positive_net_return_folds=positive,
        median_net_cumulative_return=median_ret if fold_count else None,
        median_net_sharpe=0.5 if fold_count else None,
        stdev_net_cumulative_return=0.02 if fold_count else None,
        worst_max_drawdown=-0.1 if fold_count else None, worst_fold_index=0 if fold_count else None,
        best_net_cumulative_return=0.1 if fold_count else None, best_fold_index=0 if fold_count else None,
        regime_breakdown=regimes, folds=(),
    )


class TestEvidenceLevelNeverReachesValidated:
    """`VALIDATED` must be structurally unreachable from
    `classify_evidence_level`, not merely undocumented -- exercises the
    single most favorable input combination this function can receive
    and confirms it still stops at CANDIDATE."""

    def test_even_the_best_possible_real_input_stops_at_candidate(self) -> None:
        aggregate = _agg(fold_count=20, positive=20, regimes={"BULL": 10, "BEAR": 10})
        assessment = classify_evidence_level(aggregate, is_real_data=True, pbo_dsr_applied=True)
        assert assessment.level == EvidenceLevel.CANDIDATE
        assert assessment.level != EvidenceLevel.VALIDATED

    def test_no_evidence_level_member_named_validated_is_ever_assigned_by_this_module(self) -> None:
        # VALIDATED exists in the enum only as a documented human-review
        # target -- confirm every EvidenceLevel value classify_evidence_level
        # can itself return excludes it, across a wide input sweep.
        seen_levels = set()
        for fold_count in (0, 1, 3, 5, 6, 10, 25):
            for positive in range(0, fold_count + 1):
                for regimes in ({}, {"BULL": fold_count}, {"BULL": fold_count // 2, "BEAR": fold_count - fold_count // 2}):
                    for is_real in (True, False):
                        for pbo in (True, False):
                            agg = _agg(fold_count, positive, regimes)
                            seen_levels.add(classify_evidence_level(agg, is_real_data=is_real, pbo_dsr_applied=pbo).level)
        assert EvidenceLevel.VALIDATED not in seen_levels


class TestEvidenceLevelThresholds:
    def test_synthetic_data_is_always_insufficient_evidence(self) -> None:
        agg = _agg(fold_count=50, positive=50, regimes={"BULL": 25, "BEAR": 25})
        assessment = classify_evidence_level(agg, is_real_data=False, pbo_dsr_applied=True)
        assert assessment.level == EvidenceLevel.INSUFFICIENT_EVIDENCE

    def test_real_data_below_preliminary_floor_is_insufficient(self) -> None:
        agg = _agg(fold_count=MIN_FOLDS_FOR_PRELIMINARY - 1, positive=1, regimes={"BULL": 2})
        assessment = classify_evidence_level(agg, is_real_data=True, pbo_dsr_applied=False)
        assert assessment.level == EvidenceLevel.INSUFFICIENT_EVIDENCE

    def test_real_data_at_preliminary_floor_is_preliminary(self) -> None:
        agg = _agg(fold_count=MIN_FOLDS_FOR_PRELIMINARY, positive=MIN_FOLDS_FOR_PRELIMINARY, regimes={"BULL": MIN_FOLDS_FOR_PRELIMINARY})
        assessment = classify_evidence_level(agg, is_real_data=True, pbo_dsr_applied=False)
        assert assessment.level == EvidenceLevel.PRELIMINARY

    def test_real_data_at_robustness_floor_without_pbo_is_robustness_pending(self) -> None:
        agg = _agg(fold_count=MIN_FOLDS_FOR_ROBUSTNESS, positive=MIN_FOLDS_FOR_ROBUSTNESS, regimes={"BULL": MIN_FOLDS_FOR_ROBUSTNESS})
        assessment = classify_evidence_level(agg, is_real_data=True, pbo_dsr_applied=False)
        assert assessment.level == EvidenceLevel.ROBUSTNESS_PENDING

    def test_real_data_meeting_candidate_bar_with_pbo_applied_is_candidate(self) -> None:
        half = MIN_FOLDS_FOR_ROBUSTNESS // 2
        agg = _agg(fold_count=MIN_FOLDS_FOR_ROBUSTNESS, positive=MIN_FOLDS_FOR_ROBUSTNESS, regimes={"BULL": half, "BEAR": MIN_FOLDS_FOR_ROBUSTNESS - half})
        assessment = classify_evidence_level(agg, is_real_data=True, pbo_dsr_applied=True)
        assert assessment.level == EvidenceLevel.CANDIDATE
        assert assessment.positive_fold_ratio >= MIN_POSITIVE_FOLD_RATIO_FOR_CANDIDATE
        assert assessment.distinct_known_regimes >= MIN_DISTINCT_KNOWN_REGIMES_FOR_CANDIDATE

    def test_single_regime_misses_candidate_bar_even_with_pbo_applied(self) -> None:
        agg = _agg(fold_count=MIN_FOLDS_FOR_ROBUSTNESS, positive=MIN_FOLDS_FOR_ROBUSTNESS, regimes={"BULL": MIN_FOLDS_FOR_ROBUSTNESS})
        assessment = classify_evidence_level(agg, is_real_data=True, pbo_dsr_applied=True)
        assert assessment.level == EvidenceLevel.ROBUSTNESS_PENDING

    def test_low_positive_ratio_misses_candidate_bar_even_with_pbo_applied(self) -> None:
        half = MIN_FOLDS_FOR_ROBUSTNESS // 2
        agg = _agg(fold_count=MIN_FOLDS_FOR_ROBUSTNESS, positive=1, regimes={"BULL": half, "BEAR": MIN_FOLDS_FOR_ROBUSTNESS - half})
        assessment = classify_evidence_level(agg, is_real_data=True, pbo_dsr_applied=True)
        assert assessment.level == EvidenceLevel.ROBUSTNESS_PENDING


class TestEvidenceLevelWithActualPboDsrValues:
    """strategy_research.pbo_dsr integration: when the caller supplies
    real computed PBO/DSR numbers (not just the pbo_dsr_applied=True
    flag), CANDIDATE must additionally require PBO < MAX_PBO_FOR_CANDIDATE
    and DSR >= MIN_DSR_FOR_CANDIDATE -- a fold-consistent-looking result
    that PBO flags as noise must NOT reach CANDIDATE."""

    def _fold_consistent_agg(self) -> WalkForwardAggregate:
        half = MIN_FOLDS_FOR_ROBUSTNESS // 2
        return _agg(
            fold_count=MIN_FOLDS_FOR_ROBUSTNESS, positive=MIN_FOLDS_FOR_ROBUSTNESS,
            regimes={"BULL": half, "BEAR": MIN_FOLDS_FOR_ROBUSTNESS - half},
        )

    def test_good_pbo_and_dsr_confirm_candidate(self) -> None:
        assessment = classify_evidence_level(
            self._fold_consistent_agg(), is_real_data=True, pbo_dsr_applied=True,
            pbo_probability=0.1, deflated_sharpe_ratio=0.99,
        )
        assert assessment.level == EvidenceLevel.CANDIDATE
        assert "PBO=0.10" in assessment.reason

    def test_high_pbo_blocks_candidate_despite_good_fold_ratio(self) -> None:
        assessment = classify_evidence_level(
            self._fold_consistent_agg(), is_real_data=True, pbo_dsr_applied=True,
            pbo_probability=0.7, deflated_sharpe_ratio=0.99,
        )
        assert assessment.level == EvidenceLevel.ROBUSTNESS_PENDING
        assert "noisy trials" in assessment.reason

    def test_low_dsr_blocks_candidate_despite_good_fold_ratio_and_low_pbo(self) -> None:
        assessment = classify_evidence_level(
            self._fold_consistent_agg(), is_real_data=True, pbo_dsr_applied=True,
            pbo_probability=0.1, deflated_sharpe_ratio=0.3,
        )
        assert assessment.level == EvidenceLevel.ROBUSTNESS_PENDING

    def test_pbo_exactly_at_threshold_is_not_below_it(self) -> None:
        assessment = classify_evidence_level(
            self._fold_consistent_agg(), is_real_data=True, pbo_dsr_applied=True,
            pbo_probability=0.5, deflated_sharpe_ratio=0.99,
        )
        assert assessment.level == EvidenceLevel.ROBUSTNESS_PENDING

    def test_omitting_pbo_dsr_values_preserves_old_trust_the_flag_behavior(self) -> None:
        """Backward compatibility: a caller that only sets
        pbo_dsr_applied=True (never supplying the actual numbers) gets
        exactly the pre-existing behavior -- this is what every
        pre-existing caller in this test file and
        scripts/run_long_horizon_validation.py's prior behavior does."""
        assessment = classify_evidence_level(
            self._fold_consistent_agg(), is_real_data=True, pbo_dsr_applied=True,
        )
        assert assessment.level == EvidenceLevel.CANDIDATE


class TestPboDsrApplicability:
    """Category L (research log completeness) exercised through the
    applicability check's own dependence on a fully-populated
    `ResearchLog`."""

    def _mk_entry(self, name: str, params: dict) -> CandidateEvaluation:
        return CandidateEvaluation(
            strategy_name=name, strategy_version="v1", hypothesis="h", parameters=params,
            train_period=(datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2023, 6, 1, tzinfo=timezone.utc)),
            validation_period=(), test_period=None,
            criteria=PromisingCriteria(), classification=CandidateClassification.INCONCLUSIVE,
        )

    def test_not_applicable_with_a_single_candidate(self) -> None:
        log = ResearchLog(selection_procedure="test")
        log.record(self._mk_entry("s1", {}))
        result = assess_pbo_dsr_applicability(log, real_fold_counts_by_candidate={"s1": 10})
        assert result.applicable is False
        assert result.candidate_count == 1

    def test_not_applicable_when_a_candidate_has_too_few_real_folds(self) -> None:
        log = ResearchLog(selection_procedure="test")
        log.record(self._mk_entry("s1", {}))
        log.record(self._mk_entry("s2", {}))
        result = assess_pbo_dsr_applicability(log, real_fold_counts_by_candidate={"s1": 10, "s2": 1})
        assert result.applicable is False
        assert result.min_real_out_of_sample_folds_across_candidates == 1

    def test_applicable_when_every_candidate_clears_the_fold_floor(self) -> None:
        log = ResearchLog(selection_procedure="test")
        log.record(self._mk_entry("s1", {}))
        log.record(self._mk_entry("s2", {}))
        result = assess_pbo_dsr_applicability(
            log, real_fold_counts_by_candidate={"s1": 6, "s2": 6}, min_candidates=2, min_folds_per_candidate=6,
        )
        assert result.applicable is True

    def test_every_logged_candidate_is_retained_never_pruned(self) -> None:
        # Instruction sections 26/39: rejected/inconclusive candidates
        # must remain visible in the log, not silently disappear once a
        # "better" candidate is recorded.
        log = ResearchLog(selection_procedure="test")
        log.record(self._mk_entry("s1", {"a": 1}))
        log.record(self._mk_entry("s1", {"a": 2}))  # same strategy, different params -- a second, distinct entry
        log.record(self._mk_entry("s2", {}))
        assert log.candidate_count == 3
        assert log.parameter_combination_count() == 3
        summary = log.summary()
        assert summary["candidate_count"] == 3
        assert len(summary["strategies"]) == 3


class TestChronologicalSplitReservesTestExactlyOnce:
    """Category A (chronological split) and B (no train/val/test
    overlap), re-verified at the Phase 25 usage boundary: the walk-forward
    development region (train_start..validation_end) and the held-out
    TEST region (test_start..test_end) that `scripts/run_long_horizon_validation.py`
    derives from `build_chronological_split` must never overlap."""

    def test_walk_forward_region_and_held_out_test_region_do_not_overlap(self) -> None:
        split = build_chronological_split(
            datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, tzinfo=timezone.utc),
            train_fraction=0.6, validation_fraction=0.2,
        )
        walk_forward_region_end = split.validation_end
        held_out_test_region_start = split.test_start
        assert walk_forward_region_end == held_out_test_region_start
        assert split.test_end > split.test_start

    def test_split_rejects_a_manually_constructed_overlap(self) -> None:
        from strategy_research.splits import TrainValidationTestSplit

        with pytest.raises(ValueError):
            TrainValidationTestSplit(
                train_start=datetime(2023, 1, 1, tzinfo=timezone.utc), train_end=datetime(2023, 8, 1, tzinfo=timezone.utc),
                validation_start=datetime(2023, 6, 1, tzinfo=timezone.utc), validation_end=datetime(2023, 10, 1, tzinfo=timezone.utc),
                test_start=datetime(2023, 9, 1, tzinfo=timezone.utc), test_end=datetime(2023, 12, 1, tzinfo=timezone.utc),
            )


class TestUniverseBenchmarkExclusion:
    """Category Q, re-verified at the Phase 25 evaluation boundary: the
    benchmark symbol this phase's regime/benchmark wiring uses must
    never be a member of the tradeable universe passed to a strategy."""

    def test_benchmark_symbol_is_not_in_pilot_universe_security_ids(self) -> None:
        from data_infra.universe import BENCHMARK_SYMBOL, PILOT_UNIVERSE_V1

        assert BENCHMARK_SYMBOL not in PILOT_UNIVERSE_V1.symbol_ids
