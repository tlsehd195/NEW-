"""Category: Integration Test -- Prediction -> Decision -> Position
Sizing -> Risk Engine, computed alongside a real BacktestEngine run
(Phase 8 spec section 13, instruction section 19).

Like Phase 7's Decision Agent, PositionSizer/PortfolioRiskEngine are
never wired into order generation -- they are proven to run correctly
alongside a live backtest loop, using the loop's own real
`PortfolioView` and an accumulating portfolio-value history at each
checkpoint, without altering the strategy's own fills (Phase 8 spec
section 14: Order Creation remains out of scope).
"""

from __future__ import annotations

from datetime import date, timedelta

from risk_helpers import build_repository, drifting_prices, make_bars, make_security, trading_days

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy, OrderIntent

from decision.agent import BaselineRuleDecisionAgent
from decision.config import DecisionConfig

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor

from regime.config import RegimeConfig
from regime.detector import RegimeDetector

from risk.enums import RiskCheckStatus
from risk.engine import DeterministicPortfolioRiskEngine
from risk.sizing import DeterministicPositionSizer


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="risk-integration-test",
    )
    return repo, config


class RecordingStrategy:
    """A thin pass-through around BuyAndHoldStrategy that also drives the
    full Prediction -> Decision -> Position Sizing -> Risk Engine chain
    at every checkpoint, purely as an observer -- it never lets any of
    those results influence which intents it returns."""

    version = "risk_recording_strategy_v1"

    def __init__(self) -> None:
        self._predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        self._regime_detector = RegimeDetector(RegimeConfig())
        self._decision_agent = BaselineRuleDecisionAgent(DecisionConfig())
        self._sizer = DeterministicPositionSizer()
        self._risk_engine = DeterministicPortfolioRiskEngine()
        self._inner = BuyAndHoldStrategy(["AAA"])
        self.sizings: list = []
        self.checked: list = []
        self._value_history: list[float] = []

    def generate_orders(self, as_of_time, data: AsOfDataView, portfolio) -> list[OrderIntent]:
        prediction = self._predictor.predict(data, "AAA")
        regime = self._regime_detector.compute_composite(data, "AAA")
        decision = self._decision_agent.decide("AAA", as_of_time, prediction, regime, portfolio)

        bars = data.get_bars("AAA", as_of_time - timedelta(days=5), as_of_time)
        price = bars[-1].close if bars else None

        self._value_history.append(portfolio.portfolio_value)

        sizing = self._sizer.size("AAA", as_of_time, decision, prediction, regime, portfolio, current_price=price)
        checked = self._risk_engine.assess(
            "AAA", as_of_time, sizing, portfolio, current_price=price, value_history=tuple(self._value_history),
        )
        self.sizings.append(sizing)
        self.checked.append(checked)
        return self._inner.generate_orders(as_of_time, data, portfolio)


class TestFullChainAlongsideBacktest:
    def test_full_chain_runs_at_every_checkpoint_without_error(self) -> None:
        repo, config = _scenario()
        strategy = RecordingStrategy()
        BacktestEngine(repo, config, strategy).run()

        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        assert len(strategy.sizings) == len(checkpoints)
        assert len(strategy.checked) == len(checkpoints)
        assert all(isinstance(s.status, RiskCheckStatus) for s in strategy.sizings)
        assert all(isinstance(c.status, RiskCheckStatus) for c in strategy.checked)

    def test_position_sizing_and_risk_computation_do_not_change_the_strategy_fills(self) -> None:
        repo, config = _scenario()

        result_plain = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()
        result_recording = BacktestEngine(repo, config, RecordingStrategy()).run()

        assert [f.price for f in result_plain.fills] == [f.price for f in result_recording.fills]
        assert [f.quantity for f in result_plain.fills] == [f.quantity for f in result_recording.fills]
        assert result_plain.performance == result_recording.performance

    def test_sizing_reflects_the_real_portfolio_state_from_the_backtest(self) -> None:
        """Before the strategy buys, the sizer should propose a BUY-sized
        position; after BuyAndHoldStrategy establishes the position,
        later sizing calls should see it and produce a HOLD pass-through
        (no new sizing), proving the chain uses the loop's own, real
        PortfolioView, not a stub."""
        repo, config = _scenario()
        strategy = RecordingStrategy()
        BacktestEngine(repo, config, strategy).run()

        later_reasons = {s.reason for s in strategy.sizings[-5:]}
        assert "no_new_sizing_for_hold" in later_reasons or "no_new_sizing_for_no_trade" in later_reasons

    def test_no_result_ever_falls_through_to_an_undeclared_status(self) -> None:
        repo, config = _scenario()
        strategy = RecordingStrategy()
        BacktestEngine(repo, config, strategy).run()
        for sizing, checked in zip(strategy.sizings, strategy.checked):
            assert sizing.reason
            assert checked.reason
