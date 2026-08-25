"""Category: Leakage Test -- future data does not affect a past
Position Sizing / Risk Engine result (Phase 8 spec section 15).

Neither `PositionSizer` nor `PortfolioRiskEngine` fetches data itself --
both take already-computed `DecisionOutput`/`PredictionOutput`/
`CompositeRegimeObservation`/`PortfolioView` plus an already-fetched
`current_price` as plain data (Phase 8 spec section 9, mirroring
ADR-0013 section 3's precedent for Decision Agent). This suite verifies
the guarantee end to end, one layer further than Phase 7's own
`tests/decision/test_decision_point_in_time.py`: recomputing Prediction,
Regime, and Decision through `AsOfDataView` at an earlier checkpoint,
after appending future bars, and feeding the result through
`PositionSizer` and then `PortfolioRiskEngine`, must reproduce identical
results.
"""

from __future__ import annotations

from datetime import date, timedelta

from risk_helpers import build_repository, drifting_prices, empty_portfolio, make_bars, trading_days, view_at

from decision.agent import BaselineRuleDecisionAgent

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.engine import DeterministicPortfolioRiskEngine
from risk.sizing import DeterministicPositionSizer


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    repo = build_repository(bars=bars)
    return repo, days


def _run_chain_at(repo, days, index):
    view = view_at(repo, days, index)
    prediction = DriftPredictor(PredictionConfig(lookback_days=30)).predict(view, "AAA")
    regime = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
    portfolio = empty_portfolio(view.current_time)
    decision = BaselineRuleDecisionAgent().decide("AAA", view.current_time, prediction, regime, portfolio)

    bars_here = view.get_bars("AAA", view.current_time - timedelta(days=5), view.current_time)
    price = bars_here[-1].close if bars_here else None

    sizing = DeterministicPositionSizer().size("AAA", view.current_time, decision, prediction, regime, portfolio, current_price=price)
    checked = DeterministicPortfolioRiskEngine().assess("AAA", view.current_time, sizing, portfolio, current_price=price)
    return sizing, checked


class TestNoLookahead:
    def test_sizing_and_risk_at_an_earlier_checkpoint_are_unaffected_by_appending_later_bars(self) -> None:
        repo, days = _scenario()
        cutoff_index = 90

        sizing_before, checked_before = _run_chain_at(repo, days, cutoff_index)

        extra_days = trading_days(days[-1] + timedelta(days=1), days[-1] + timedelta(days=60))
        repo.append_bars(make_bars("AAA", extra_days, [500.0 + i for i in range(len(extra_days))]))

        sizing_after, checked_after = _run_chain_at(repo, days, cutoff_index)

        assert sizing_before.status == sizing_after.status
        assert sizing_before.reason == sizing_after.reason
        assert sizing_before.proposed_target_weight == sizing_after.proposed_target_weight
        assert sizing_before.proposed_target_quantity == sizing_after.proposed_target_quantity

        assert checked_before.status == checked_after.status
        assert checked_before.reason == checked_after.reason
        assert checked_before.final_target_weight == checked_after.final_target_weight

    def test_replay_at_the_same_as_of_time_is_deterministic(self) -> None:
        repo, days = _scenario()
        sizing1, checked1 = _run_chain_at(repo, days, 100)
        sizing2, checked2 = _run_chain_at(repo, days, 100)
        assert sizing1.status == sizing2.status
        assert sizing1.proposed_target_weight == sizing2.proposed_target_weight
        assert checked1.status == checked2.status
        assert checked1.final_target_weight == checked2.final_target_weight

    def test_sizing_and_risk_as_of_time_match_the_checkpoint(self) -> None:
        repo, days = _scenario()
        from risk_helpers import checkpoint

        sizing, checked = _run_chain_at(repo, days, 50)
        assert sizing.as_of_time == checkpoint(days[50])
        assert checked.as_of_time == checkpoint(days[50])
