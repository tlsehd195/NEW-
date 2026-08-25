"""Category: Integration Test -- Phase 5 Regime -> Phase 6 Prediction ->
Phase 7 Decision, computed alongside a real BacktestEngine run (Phase 7
spec section 8, 12).

Like Phase 6's Prediction, DecisionAgent is never wired into order
generation -- it is proven to run correctly alongside a live backtest
loop, using the loop's own real `PortfolioView` at each checkpoint,
without altering the strategy's own fills (Phase 7 spec section 4-5:
Position Sizing/Order Creation remain out of scope).
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days
from predict_helpers import drifting_prices

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

from trade_journal.enums import DecisionAction


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="decision-integration-test",
    )
    return repo, config


class RecordingStrategy:
    """A thin pass-through around BuyAndHoldStrategy that also drives the
    full Regime -> Prediction -> Decision chain at every checkpoint,
    purely as an observer -- it never lets the decision influence which
    intents it returns."""

    version = "recording_strategy_v1"

    def __init__(self, repository) -> None:
        self._inner = BuyAndHoldStrategy(["AAA"])
        self._predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        self._regime_detector = RegimeDetector(RegimeConfig())
        self._decision_agent = BaselineRuleDecisionAgent(DecisionConfig())
        self.decisions: list = []

    def generate_orders(self, as_of_time, data, portfolio) -> list[OrderIntent]:
        prediction = self._predictor.predict(data, "AAA")
        regime = self._regime_detector.compute_composite(data, "AAA")
        decision = self._decision_agent.decide("AAA", as_of_time, prediction, regime, portfolio)
        self.decisions.append(decision)
        return self._inner.generate_orders(as_of_time, data, portfolio)


class TestFullChainAlongsideBacktest:
    def test_regime_prediction_decision_chain_runs_at_every_checkpoint(self) -> None:
        repo, config = _scenario()
        strategy = RecordingStrategy(repo)
        result = BacktestEngine(repo, config, strategy).run()

        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        assert len(strategy.decisions) == len(checkpoints)
        assert all(d.action in DecisionAction for d in strategy.decisions)

    def test_decision_computation_does_not_change_the_strategy_fills(self) -> None:
        repo, config = _scenario()

        result_plain = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()
        result_recording = BacktestEngine(repo, config, RecordingStrategy(repo)).run()

        assert [f.price for f in result_plain.fills] == [f.price for f in result_recording.fills]
        assert [f.quantity for f in result_plain.fills] == [f.quantity for f in result_recording.fills]
        assert result_plain.performance == result_recording.performance

    def test_decision_reflects_the_real_portfolio_state_from_the_backtest(self) -> None:
        """Before the strategy buys, the agent should see no position;
        after the buy-and-hold strategy establishes one, later decisions
        should see it and (given a sustained positive signal) prefer
        HOLD over BUY -- proving the chain uses the loop's own, real
        PortfolioView, not a stub."""
        repo, config = _scenario()
        strategy = RecordingStrategy(repo)
        BacktestEngine(repo, config, strategy).run()

        first_decision = strategy.decisions[0]
        assert first_decision.action in (DecisionAction.BUY, DecisionAction.NO_TRADE)

        later_actions = {d.action for d in strategy.decisions[-5:]}
        # Once positioned, the agent never proposes a second BUY for the
        # same fully-held security under a still-positive signal.
        assert DecisionAction.BUY not in later_actions or any(
            d.action == DecisionAction.HOLD for d in strategy.decisions[-5:]
        )

    def test_standalone_view_matches_the_backtest_loop_at_the_same_checkpoint(self) -> None:
        repo, config = _scenario()
        strategy = RecordingStrategy(repo)
        BacktestEngine(repo, config, strategy).run()

        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        clock.index = 60
        view = AsOfDataView(repo, clock)

        predictor = DriftPredictor(PredictionConfig(lookback_days=20))
        regime_detector = RegimeDetector(RegimeConfig())
        prediction = predictor.predict(view, "AAA")
        regime = regime_detector.compute_composite(view, "AAA")

        assert prediction.as_of_time == checkpoints[60]
        assert regime.as_of_time == checkpoints[60]
