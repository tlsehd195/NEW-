"""Category: Leakage Tests -- point-in-time correctness, future-data
rejection, replay stability (Phase 6 spec section 3, 13). Mirrors
tests/regime/test_point_in_time.py's structure, applied to Predictor
instead of RegimeDetector.
"""

from __future__ import annotations

from datetime import date, timedelta

from predict_helpers import build_repository, drifting_prices, make_bars, trading_days, view_at

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor


def _scenario():
    days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
    bars = make_bars("AAA", days, drifting_prices(days))
    repo = build_repository(bars=bars)
    return repo, days


class TestNoLookahead:
    def test_prediction_at_an_earlier_checkpoint_is_unaffected_by_appending_later_bars(self) -> None:
        repo, days = _scenario()
        config = PredictionConfig(lookback_days=30)
        cutoff_index = 60

        before = DriftPredictor(config).predict(view_at(repo, days, cutoff_index), "AAA")

        extra_days = trading_days(days[-1] + timedelta(days=1), days[-1] + timedelta(days=60))
        repo.append_bars(make_bars("AAA", extra_days, [500.0 + i for i in range(len(extra_days))]))

        after = DriftPredictor(config).predict(view_at(repo, days, cutoff_index), "AAA")

        assert before.expected_return == after.expected_return
        assert before.probability == after.probability
        assert before.expected_volatility == after.expected_volatility

    def test_asofdataview_never_exposes_bars_beyond_the_current_checkpoint(self) -> None:
        from predict_helpers import checkpoint

        repo, days = _scenario()
        view = view_at(repo, days, 40)
        bars = view.get_bars("AAA", checkpoint(days[0], 0), view.current_time)
        assert all(b.timestamp <= view.current_time for b in bars)

    def test_replay_at_the_same_as_of_time_is_deterministic(self) -> None:
        repo, days = _scenario()
        config = PredictionConfig(lookback_days=30)
        cutoff_index = 90

        r1 = DriftPredictor(config).predict(view_at(repo, days, cutoff_index), "AAA")
        r2 = DriftPredictor(config).predict(view_at(repo, days, cutoff_index), "AAA")

        assert r1.expected_return == r2.expected_return
        assert r1.probability == r2.probability
        assert r1.confidence == r2.confidence

    def test_no_as_of_time_parameter_exists_on_the_view_predictor_receives(self) -> None:
        """Structural, defensive re-verification (already proven by Phase
        5's identical test on the same AsOfDataView type) that the object
        every Predictor receives has no accidental leakage path."""
        import inspect

        from backtest.asof import AsOfDataView

        assert "as_of_time" not in inspect.signature(AsOfDataView.get_bars).parameters
