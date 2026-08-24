"""Category: insufficient data / fail-closed (Phase 6 spec section 8, 13).

PROJECT_MASTER_PLAN.md section 1.4's "Model Unknown -> 신규 주문 차단"
applied to a Predictor that cannot support a real estimate: it must
return `None` numeric fields and a low `confidence`, never a
plausible-looking guess.
"""

from __future__ import annotations

from datetime import date

from predict_helpers import build_repository, drifting_prices, make_bars, trading_days, view_at

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor, RegimeAwarePredictor


class TestFailClosed:
    def test_insufficient_history_yields_none_estimates_not_a_guess(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))  # short window
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, 3)  # very early checkpoint

        prediction = DriftPredictor(PredictionConfig(lookback_days=60)).predict(view, "AAA")
        assert prediction.expected_return is None
        assert prediction.probability is None
        assert prediction.expected_volatility is None
        assert prediction.uncertainty is None
        assert prediction.confidence is not None and prediction.confidence < 1.0

    def test_no_data_at_all_for_an_unknown_security_is_none_not_zero(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = DriftPredictor().predict(view, "ZZZ")  # no bars exist for ZZZ
        assert prediction.expected_return is None
        assert prediction.confidence == 0.0

    def test_confidence_reflects_a_real_completeness_ratio_not_a_fixed_placeholder(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        config = PredictionConfig(lookback_days=60)

        low = DriftPredictor(config).predict(view_at(repo, days, 10), "AAA")
        high = DriftPredictor(config).predict(view_at(repo, days, len(days) - 1), "AAA")
        assert low.confidence < high.confidence
        assert high.confidence == 1.0

    def test_regime_aware_predictor_also_fails_closed_on_insufficient_history(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, 3)

        prediction = RegimeAwarePredictor(PredictionConfig(lookback_days=60)).predict(view, "AAA")
        assert prediction.expected_return is None
        # regime_context is still populated (Regime's own UNKNOWN states are
        # honest data, not withheld) even though the return estimate is None.
        assert prediction.regime_context is not None
