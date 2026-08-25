"""Category: Leakage Test -- future data does not affect a past decision,
as-of replay, deterministic replay (Phase 7 spec section 3, 8, 12).

DecisionAgent itself fetches no data (it only combines already-computed
PredictionOutput/CompositeRegimeObservation/PortfolioView), so this
suite verifies the guarantee end to end: recomputing Prediction and
Regime through AsOfDataView at an earlier checkpoint, after appending
future bars, and feeding the result into DecisionAgent, must reproduce
the identical decision (Phase 7 spec section 3 -- no new leakage guard
is written in `decision.*` itself; the guarantee is inherited).
"""

from __future__ import annotations

from datetime import date, timedelta

from decision_helpers import build_repository, drifting_prices, empty_portfolio, make_bars, trading_days, view_at

from decision.agent import BaselineRuleDecisionAgent

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    repo = build_repository(bars=bars)
    return repo, days


def _decide_at(repo, days, index):
    view = view_at(repo, days, index)
    prediction = DriftPredictor(PredictionConfig(lookback_days=30)).predict(view, "AAA")
    regime = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
    portfolio = empty_portfolio(view.current_time)
    return BaselineRuleDecisionAgent().decide("AAA", view.current_time, prediction, regime, portfolio)


class TestNoLookahead:
    def test_decision_at_an_earlier_checkpoint_is_unaffected_by_appending_later_bars(self) -> None:
        repo, days = _scenario()
        cutoff_index = 90

        before = _decide_at(repo, days, cutoff_index)

        extra_days = trading_days(days[-1] + timedelta(days=1), days[-1] + timedelta(days=60))
        repo.append_bars(make_bars("AAA", extra_days, [500.0 + i for i in range(len(extra_days))]))

        after = _decide_at(repo, days, cutoff_index)

        assert before.action == after.action
        assert before.decision_reason == after.decision_reason
        assert before.target_weight_hint == after.target_weight_hint

    def test_replay_at_the_same_as_of_time_is_deterministic(self) -> None:
        repo, days = _scenario()
        d1 = _decide_at(repo, days, 100)
        d2 = _decide_at(repo, days, 100)
        assert d1.action == d2.action
        assert d1.decision_reason == d2.decision_reason
        assert d1.confidence == d2.confidence

    def test_decision_as_of_time_matches_the_checkpoint(self) -> None:
        repo, days = _scenario()
        from decision_helpers import checkpoint

        decision = _decide_at(repo, days, 50)
        assert decision.as_of_time == checkpoint(days[50])
