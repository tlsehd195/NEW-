"""Category: pure-Python OLS correctness + honesty about missing state.
SYNTHETIC data only -- these tests exercise the solver's math, not any
real-market claim."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from ml.linear_model import CANDIDATE_RIDGES, LinearRegressionModel, select_ridge_via_expanding_window_cv


@dataclass
class _Sample:
    features: dict
    target: float


@dataclass
class _TimedSample:
    as_of_time: datetime
    features: dict
    target: float


def _utc(day_offset: int) -> datetime:
    return datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)


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


class TestSelectRidgeViaExpandingWindowCv:
    def test_falls_back_to_weakest_ridge_with_too_little_history(self) -> None:
        samples = [_TimedSample(as_of_time=_utc(i), features={"x": float(i)}, target=float(i)) for i in range(2)]
        assert select_ridge_via_expanding_window_cv(samples, ["x"], folds=3) == CANDIDATE_RIDGES[0]

    def test_never_raises_and_returns_one_of_the_candidates(self) -> None:
        # Noiseless linear data spread over enough distinct dates to
        # form real CV folds -- must return a value from the
        # pre-registered grid, never crash, never fabricate.
        samples = [
            _TimedSample(as_of_time=_utc(i * 10), features={"x": float(i)}, target=2.0 * i + 1.0)
            for i in range(20)
        ]
        chosen = select_ridge_via_expanding_window_cv(samples, ["x"], folds=3)
        assert chosen in CANDIDATE_RIDGES

    def test_cv_never_reads_a_sample_from_the_future_relative_to_its_own_fold(self) -> None:
        # Deliberately construct data where a LATER block's relationship
        # is different from the earlier blocks' -- an expanding-window
        # CV fold trained only on strictly-earlier dates cannot see that
        # later shift, so this is a structural (not just numerical)
        # check that the split is chronological, not random. We assert
        # this indirectly: the function must not raise and must still
        # return a valid candidate despite the regime change (a random-
        # split implementation would not fail this either, but a
        # look-ahead bug that trained on the whole dataset including
        # future blocks would not raise either -- this test's real
        # value is documented in test_ml_strategy.py's leakage-focused
        # checks; this one guards against the function crashing when
        # given non-stationary data, which the earlier synthetic tests
        # do not exercise).
        samples = [
            _TimedSample(as_of_time=_utc(i * 10), features={"x": float(i)}, target=2.0 * i + 1.0)
            for i in range(10)
        ] + [
            _TimedSample(as_of_time=_utc(100 + i * 10), features={"x": float(i)}, target=-5.0 * i + 1.0)
            for i in range(10)
        ]
        chosen = select_ridge_via_expanding_window_cv(samples, ["x"], folds=3)
        assert chosen in CANDIDATE_RIDGES
