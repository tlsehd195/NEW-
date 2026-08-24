"""Category: deterministic prediction calculation, parameter boundary,
baseline vs baseline distinction (Phase 6 spec section 13).
"""

from __future__ import annotations

from datetime import date

from predict_helpers import build_repository, drifting_prices, make_bars, trading_days, view_at

from predict.config import PredictionConfig
from predict.enums import PredictionMethodType
from predict.predictor import DriftPredictor, RandomWalkPredictor


class TestRandomWalkPredictor:
    def test_always_predicts_zero_return_and_even_odds(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 3, 29))
        bars = make_bars("AAA", days, drifting_prices(days, daily_return=0.01))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = RandomWalkPredictor().predict(view, "AAA")
        assert prediction.expected_return == 0.0
        assert prediction.probability == 0.5
        assert prediction.confidence == 1.0
        assert prediction.method_type == PredictionMethodType.DETERMINISTIC_BASELINE

    def test_unaffected_by_the_underlying_trend(self) -> None:
        """By construction, the null-hypothesis baseline never
        differentiates between a bull and bear market -- exactly the
        point of having it as a comparison baseline."""
        days = trading_days(date(2024, 1, 2), date(2024, 3, 29))
        bull_bars = make_bars("AAA", days, drifting_prices(days, daily_return=0.02))
        bear_bars = make_bars("BBB", days, drifting_prices(days, daily_return=-0.02, seed=4))
        repo = build_repository(bars=bull_bars + bear_bars)
        view = view_at(repo, days, len(days) - 1)

        predictor = RandomWalkPredictor()
        bull_pred = predictor.predict(view, "AAA")
        bear_pred = predictor.predict(view, "BBB")
        assert bull_pred.expected_return == bear_pred.expected_return == 0.0


class TestDriftPredictor:
    def test_rising_prices_yield_positive_expected_return(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days, daily_return=0.003))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = DriftPredictor().predict(view, "AAA")
        assert prediction.expected_return is not None and prediction.expected_return > 0
        assert prediction.probability is not None and prediction.probability > 0.5
        assert prediction.expected_volatility is not None and prediction.expected_volatility > 0
        assert prediction.uncertainty is not None and prediction.uncertainty >= 0
        assert prediction.confidence == 1.0

    def test_falling_prices_yield_negative_expected_return(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days, daily_return=-0.003))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = DriftPredictor().predict(view, "AAA")
        assert prediction.expected_return is not None and prediction.expected_return < 0
        assert prediction.probability is not None and prediction.probability < 0.5

    def test_longer_horizon_compounds_the_same_daily_drift(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days, daily_return=0.002))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        short = DriftPredictor(PredictionConfig(horizon_days=1)).predict(view, "AAA")
        long = DriftPredictor(PredictionConfig(horizon_days=20)).predict(view, "AAA")
        assert long.expected_return > short.expected_return > 0

    def test_different_lookback_yields_different_configuration_version(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        p1 = DriftPredictor(PredictionConfig(lookback_days=30)).predict(view, "AAA")
        p2 = DriftPredictor(PredictionConfig(lookback_days=60)).predict(view, "AAA")
        assert p1.configuration_version != p2.configuration_version
