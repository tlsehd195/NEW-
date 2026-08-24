"""Category: backtest integration (Phase 6 spec section 8, 13).

Predictions are computed via `AsOfDataView` inside a live
`BacktestEngine.run()` loop, purely as an observer -- they never
influence order generation. This is deliberately different from Phase
5's `RegimeConditionedStrategy`: the instruction for this phase lists
"Prediction 결과만으로 주문 생성 금지" as a hard principle, and with no
Position Sizing/Risk Engine yet (Phase 8), wiring a prediction directly
into a Strategy's order decisions would blur exactly the boundary this
phase must preserve. So integration here means "runs correctly and
reproducibly inside the same data flow," not "drives a trade."
"""

from __future__ import annotations

from datetime import date

from backtest_helpers import build_repository, make_bars, make_security, trading_days
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock, build_daily_checkpoints
from backtest.engine import BacktestConfig, BacktestEngine
from backtest.strategy import BuyAndHoldStrategy

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    securities = [make_security("AAA", "AAA")]
    repo = build_repository(bars=bars, securities=securities)
    config = BacktestConfig(
        market="US_EQUITY", start_date=days[0], end_date=days[-1], initial_capital=100_000.0,
        security_ids=("AAA",), code_version="predict-integration-test",
    )
    return repo, config


class TestBacktestEngineUnmodified:
    def test_existing_baseline_still_runs_unaffected_by_the_predict_module_existing(self) -> None:
        repo, config = _scenario()
        result = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()
        assert result.is_valid_performance
        assert len(result.fills) > 0


class TestPredictionsAlongsideABacktest:
    def test_predictions_computed_at_every_checkpoint_do_not_change_the_backtest_result(self) -> None:
        """Running a predictor at every checkpoint (a pure side
        observation) must not alter the strategy's own fills/performance
        -- proving Prediction genuinely does not feed back into
        execution unless a future phase deliberately wires it in."""
        repo, config = _scenario()

        result_without_predictions = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        view = AsOfDataView(repo, clock)
        predictor = DriftPredictor(PredictionConfig(lookback_days=30))
        predictions = []
        for i in range(len(checkpoints)):
            clock.index = i
            predictions.append(predictor.predict(view, "AAA"))

        result_with_predictions_computed = BacktestEngine(repo, config, BuyAndHoldStrategy(["AAA"])).run()

        assert len(predictions) == len(checkpoints)
        assert [f.price for f in result_without_predictions.fills] == [
            f.price for f in result_with_predictions_computed.fills
        ]

    def test_prediction_as_of_time_matches_the_checkpoint_it_was_computed_at(self) -> None:
        repo, config = _scenario()
        calendar = repo.get_trading_calendar("US_EQUITY")
        checkpoints = build_daily_checkpoints(calendar, config.start_date, config.end_date)
        clock = BacktestClock(checkpoints)
        clock.index = 50
        view = AsOfDataView(repo, clock)

        prediction = DriftPredictor().predict(view, "AAA")
        assert prediction.as_of_time == checkpoints[50]
