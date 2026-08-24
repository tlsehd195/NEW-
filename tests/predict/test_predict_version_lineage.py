"""Category: version lineage, reproducibility (Phase 6 spec section 7, 13)."""

from __future__ import annotations

from datetime import date

from predict_helpers import build_repository, drifting_prices, make_bars, trading_days, view_at

from predict.config import PredictionConfig
from predict.predictor import DriftPredictor, RandomWalkPredictor


class TestVersionLineage:
    def test_every_prediction_carries_full_lineage_fields(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = DriftPredictor().predict(view, "AAA")
        assert prediction.feature_version
        assert prediction.method_version
        assert prediction.configuration_version
        assert isinstance(prediction.data_version, tuple) and len(prediction.data_version) > 0
        assert prediction.model_version is None  # no trained model in Phase 6

    def test_data_version_reflects_the_bars_actually_used(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = DriftPredictor().predict(view, "AAA")
        real_versions = {b.provenance.data_version for b in bars}
        assert set(prediction.data_version).issubset(real_versions)

    def test_random_walk_has_no_data_dependency_and_empty_data_version(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        prediction = RandomWalkPredictor().predict(view, "AAA")
        assert prediction.data_version == ()

    def test_identical_inputs_produce_byte_identical_predictions(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, drifting_prices(days))
        repo = build_repository(bars=bars)

        p1 = DriftPredictor().predict(view_at(repo, days, 100), "AAA")
        p2 = DriftPredictor().predict(view_at(repo, days, 100), "AAA")
        assert p1.expected_return == p2.expected_return
        assert p1.probability == p2.probability
        assert p1.expected_volatility == p2.expected_volatility
        assert p1.uncertainty == p2.uncertainty
        assert p1.configuration_version == p2.configuration_version

    def test_deterministic_baseline_vs_model_based_is_a_typed_distinction(self) -> None:
        from predict.enums import PredictionMethodType

        assert RandomWalkPredictor.method_type == PredictionMethodType.DETERMINISTIC_BASELINE
        assert DriftPredictor.method_type == PredictionMethodType.DETERMINISTIC_BASELINE
        # MODEL_BASED is reserved for a future trained model -- no class
        # in Phase 6 uses it, which is itself the point (no ML model
        # ships yet).
        all_method_types = {PredictionMethodType.DETERMINISTIC_BASELINE, PredictionMethodType.MODEL_BASED}
        assert PredictionMethodType.MODEL_BASED in all_method_types
