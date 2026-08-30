"""Category: pure-Python OLS correctness + honesty about missing state.
SYNTHETIC data only -- these tests exercise the solver's math, not any
real-market claim."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ml.linear_model import LinearRegressionModel


@dataclass
class _Sample:
    features: dict
    target: float


class TestRecoversKnownLinearRelationship:
    def test_fit_recovers_exact_coefficients_on_noiseless_data(self) -> None:
        # target = 2*x + 3*y + 1, exactly, no noise -- OLS on exactly
        # this generating process must recover intercept=1, x=2, y=3
        # (up to floating-point tolerance).
        samples = [
            _Sample(features={"x": x, "y": y}, target=2 * x + 3 * y + 1)
            for x, y in [(0, 0), (1, 0), (0, 1), (1, 1), (2, 3), (-1, 2), (4, -2)]
        ]
        model = LinearRegressionModel(feature_ids=["x", "y"])
        model.fit(samples)
        assert model.intercept == pytest.approx(1.0, abs=1e-6)
        assert model.coefficients["x"] == pytest.approx(2.0, abs=1e-6)
        assert model.coefficients["y"] == pytest.approx(3.0, abs=1e-6)

    def test_predict_matches_fitted_formula(self) -> None:
        samples = [
            _Sample(features={"x": x}, target=5 * x - 2)
            for x in [0, 1, 2, 3, 4]
        ]
        model = LinearRegressionModel(feature_ids=["x"])
        model.fit(samples)
        # abs=1e-4, not 1e-6: the fixed stability ridge (see module
        # docstring) introduces a tiny, expected bias that is amplified
        # when predicting at x=10 well outside the training range.
        assert model.predict({"x": 10}) == pytest.approx(48.0, abs=1e-4)


class TestHonestAboutMissingState:
    def test_predict_before_fit_raises(self) -> None:
        model = LinearRegressionModel(feature_ids=["x"])
        with pytest.raises(RuntimeError):
            model.predict({"x": 1.0})

    def test_predict_with_missing_feature_raises(self) -> None:
        model = LinearRegressionModel(feature_ids=["x", "y"])
        model.fit([_Sample(features={"x": 1.0, "y": 2.0}, target=3.0), _Sample(features={"x": 2.0, "y": 1.0}, target=3.0)])
        with pytest.raises(ValueError):
            model.predict({"x": 1.0})

    def test_fit_on_empty_samples_raises(self) -> None:
        model = LinearRegressionModel(feature_ids=["x"])
        with pytest.raises(ValueError):
            model.fit([])
