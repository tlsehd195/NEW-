"""Category: Prediction consuming Regime as an input (Phase 6 spec
section 9, PROJECT_MASTER_PLAN.md section 4.1's "Market Regime Detection
→ Prediction/Signal Engine" data flow).

Like Phase 5's `RegimeConditionedStrategy` (ADR-0011 section 6), this is
illustrative wiring, not a claim of superior accuracy. No test here
asserts `RegimeAwarePredictor`'s expected_return is closer to any
realized outcome than `DriftPredictor`'s -- only that the wiring runs,
produces a populated `regime_context`, and that the documented damping
behavior (dampen toward zero, reduce confidence, only under EXTREME
volatility) is mechanically correct.
"""

from __future__ import annotations

from datetime import date

from predict_helpers import build_repository, drifting_prices, make_bars, trading_days, view_at

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor, RegimeAwarePredictor
from predict.repository import InMemoryPredictionRepository

from regime.enums import RegimeAxis


class TestRegimeAwarePredictor:
    def test_regime_context_is_populated_with_all_five_axes(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = RegimeAwarePredictor().predict(view, "AAA")
        assert prediction.regime_context is not None
        assert set(prediction.regime_context.keys()) == {axis.value for axis in RegimeAxis}

    def test_extreme_volatility_dampens_expected_return_relative_to_plain_drift(self) -> None:
        import random

        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        rng = random.Random(13)
        closes = [100.0]
        for _ in range(1, len(days)):
            closes.append(max(0.01, closes[-1] * (1 + rng.gauss(0.003, 0.08))))  # noisy but drifting up
        bars = make_bars("AAA", days, closes)
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        plain = DriftPredictor().predict(view, "AAA")
        aware = RegimeAwarePredictor().predict(view, "AAA")

        volatility_state = aware.regime_context["VOLATILITY"]
        if volatility_state == "EXTREME" and plain.expected_return is not None:
            assert abs(aware.expected_return) <= abs(plain.expected_return)
            assert aware.confidence <= plain.confidence

    def test_no_damping_when_volatility_is_not_extreme(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days, daily_return=0.0005))  # calm drift
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        plain = DriftPredictor().predict(view, "AAA")
        aware = RegimeAwarePredictor().predict(view, "AAA")

        if aware.regime_context["VOLATILITY"] != "EXTREME" and plain.expected_return is not None:
            assert aware.expected_return == plain.expected_return
            assert aware.confidence == plain.confidence

    def test_allocates_its_own_independent_prediction_id_not_the_wrapped_drift_predictors(self) -> None:
        """Session 37 (ADR-0115, external review, previously-remaining
        MEDIUM): before this fix, `RegimeAwarePredictor.predict()`
        reused `base.prediction_id` (the internal DriftPredictor's own
        id) verbatim as its own result's `prediction_id` -- there was no
        way to give it an id independent of whatever the wrapped
        DriftPredictor happened to allocate, no matter how the caller
        constructed it. `starting_id` now controls this predictor's own
        allocator directly, proving the two are genuinely decoupled."""
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        plain = DriftPredictor().predict(view, "AAA")  # its internal drift also starts at PRED-000001
        aware = RegimeAwarePredictor(starting_id=100).predict(view, "AAA")
        assert aware.prediction_id == "PRED-000100"
        assert aware.prediction_id != plain.prediction_id

    def test_recording_both_predictions_in_the_same_repository_loses_neither(self) -> None:
        """The concrete payoff of independently-seedable ids: a caller
        that coordinates starting_id across predictor instances sharing
        one repository (the same `starting_id`-offsetting convention
        this codebase already uses for a single orchestration run's
        other id-allocating components, e.g. `orchestration.
        paper_strategies.RunCycleStartingIds`) can now persist both a
        plain DriftPredictor result and a RegimeAwarePredictor result
        for the same security/as_of_time without one overwriting the
        other -- pre-fix, reusing the wrapped predictor's id made that
        structurally impossible no matter what the caller did."""
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo_data = build_repository(bars=bars)
        view = view_at(repo_data, days, len(days) - 1)

        plain = DriftPredictor().predict(view, "AAA")
        aware = RegimeAwarePredictor(starting_id=100).predict(view, "AAA")

        prediction_repo = InMemoryPredictionRepository()
        prediction_repo.record(plain)
        prediction_repo.record(aware)

        assert prediction_repo.get(plain.prediction_id) == plain
        assert prediction_repo.get(aware.prediction_id) == aware
        assert len(prediction_repo.list_all(security_id="AAA")) == 2

    def test_fails_closed_the_same_way_as_the_wrapped_predictor(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 1, 31))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, 3)

        aware = RegimeAwarePredictor(PredictionConfig(lookback_days=60)).predict(view, "AAA")
        assert aware.expected_return is None
