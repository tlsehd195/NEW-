"""Category: Point-in-Time / Leakage Test -- the candidate alternative
decision process must only ever see data available at decision_time,
never data that only becomes available later, even though the return
measurement afterwards is retrospective (uses evaluation_time)."""

from __future__ import annotations

from datetime import date, timedelta

from counterfactual_helpers import make_bars_repo, utc as cf_utc

from backtest.portfolio import PortfolioView

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from evolution.counterfactual import compute_candidate_decision_alternative

from predict.predictor import DriftPredictor


def _repo_up_to(days: int, *, price_after_cutoff: float = 1000.0):
    closes = {}
    d = date(2024, 1, 2)
    price = 100.0
    for i in range(days):
        closes[d + timedelta(days=i)] = price
        price *= 1.01
    return make_bars_repo(closes), d + timedelta(days=days - 1)


def _flat_portfolio(as_of_time):
    return PortfolioView(as_of_time=as_of_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)


class TestNoFutureDataLeaksIntoTheAlternativeDecision:
    def test_adding_future_bars_after_decision_time_does_not_change_the_decision(self) -> None:
        decision_time = cf_utc(2024, 3, 20)
        evaluation_time = cf_utc(2024, 3, 30)

        repo_short, _ = _repo_up_to(90)  # ends before decision_time + a small margin
        repo_long, _ = _repo_up_to(200)  # same history up to decision_time, plus much more data after it

        predictor = DriftPredictor()
        agent = BaselineRuleDecisionAgent(DecisionConfig(min_confidence=0.0, min_expected_return=-1.0))

        alt_short = compute_candidate_decision_alternative(
            repo_short, "AAA", decision_time, evaluation_time, _flat_portfolio(decision_time),
            predictor, agent, candidate_id="CAND-000001",
        )
        alt_long = compute_candidate_decision_alternative(
            repo_long, "AAA", decision_time, evaluation_time, _flat_portfolio(decision_time),
            predictor, agent, candidate_id="CAND-000001",
        )

        # the DECISION itself must be identical -- future bars (beyond
        # decision_time) must not have been visible to the predictor.
        assert alt_short.action == alt_long.action


class TestCandidatePredictionIsBoundToDecisionTimeNotEvaluationTime:
    def test_clock_is_pinned_to_decision_time(self) -> None:
        import inspect

        from evolution.counterfactual import compute_candidate_decision_alternative as fn

        source = inspect.getsource(fn)
        # the AsOfDataView's clock must be constructed from decision_time,
        # never evaluation_time -- a structural assertion on the actual
        # call site, not just a behavioral one.
        assert "BacktestClock(checkpoints=(decision_time,))" in source
        assert "BacktestClock(checkpoints=(evaluation_time,))" not in source
