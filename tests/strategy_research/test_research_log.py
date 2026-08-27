"""Category: Multiple-testing transparency (instruction section 26).
ResearchLog must retain every candidate evaluated, including rejected
and inconclusive ones -- never silently pruned to just the winner."""

from __future__ import annotations

from strategy_research.classification import CandidateClassification, CandidateEvaluation, PromisingCriteria
from strategy_research.research_log import ResearchLog


def _evaluation(name, version, params, classification, reason=None):
    return CandidateEvaluation(
        strategy_name=name, strategy_version=version, hypothesis="test hypothesis", parameters=params,
        train_period=("2018-01-01", "2020-12-31"), validation_period=("2021-01-01", "2021-12-31"),
        test_period=None, criteria=PromisingCriteria(), classification=classification, rejection_reason=reason,
    )


class TestResearchLogRetainsEverything:
    def test_all_entries_preserved_including_rejected(self) -> None:
        log = ResearchLog(selection_procedure="fixed single default parameter set per candidate, no grid search")
        log.record(_evaluation("BuyAndHold", "buy_and_hold_v1", {}, CandidateClassification.INCONCLUSIVE))
        log.record(_evaluation("LongTermMomentum", "long_term_momentum_v1", {"lookback_months": 12}, CandidateClassification.REJECTED, "negative excess return"))
        log.record(_evaluation("TrendVolatility", "trend_volatility_v1", {"trend_lookback_months": 9}, CandidateClassification.INCONCLUSIVE))

        assert log.candidate_count == 3
        assert len(log.by_classification(CandidateClassification.REJECTED)) == 1
        assert len(log.by_classification(CandidateClassification.INCONCLUSIVE)) == 2
        assert len(log.all_entries()) == 3  # nothing dropped

    def test_re_recording_the_same_strategy_appends_not_overwrites(self) -> None:
        """A second attempt at the same strategy (e.g. after adjusting
        parameters) must show up as a SECOND entry, not silently replace
        the first -- this is what keeps a post-hoc parameter change
        auditable rather than invisible."""
        log = ResearchLog(selection_procedure="test")
        log.record(_evaluation("LongTermMomentum", "long_term_momentum_v1", {"lookback_months": 12}, CandidateClassification.INCONCLUSIVE))
        log.record(_evaluation("LongTermMomentum", "long_term_momentum_v1", {"lookback_months": 6}, CandidateClassification.INCONCLUSIVE))
        assert log.candidate_count == 2
        assert log.parameter_combination_count() == 2

    def test_summary_names_every_strategy_and_its_classification(self) -> None:
        log = ResearchLog(selection_procedure="test")
        log.record(_evaluation("BuyAndHold", "buy_and_hold_v1", {}, CandidateClassification.INCONCLUSIVE))
        summary = log.summary()
        assert summary["candidate_count"] == 1
        assert summary["strategies"][0]["strategy_name"] == "BuyAndHold"
        assert summary["strategies"][0]["classification"] == "INCONCLUSIVE"
