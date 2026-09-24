"""Category: pure-Python CART regression tree + bagged ensemble
correctness, determinism, and honesty about missing/invalid state.
SYNTHETIC data only -- these tests exercise the model's math, not any
real-market claim."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ml.tree_model import BaggedTreeModel, RegressionTreeModel


@dataclass
class _Sample:
    features: dict
    target: float


class TestRegressionTreeRecoversKnownSplit:
    def test_fit_recovers_a_clean_threshold_split(self) -> None:
        # target is exactly 0.0 when x <= 0.5, exactly 10.0 otherwise --
        # a single split at x=0.5 perfectly separates the two groups,
        # so even max_depth=1 should recover it exactly.
        samples = [
            _Sample(features={"x": 0.0}, target=0.0),
            _Sample(features={"x": 0.1}, target=0.0),
            _Sample(features={"x": 0.2}, target=0.0),
            _Sample(features={"x": 0.3}, target=0.0),
            _Sample(features={"x": 0.9}, target=10.0),
            _Sample(features={"x": 0.95}, target=10.0),
            _Sample(features={"x": 1.0}, target=10.0),
            _Sample(features={"x": 1.05}, target=10.0),
        ]
        model = RegressionTreeModel(feature_ids=["x"], max_depth=1, min_samples_leaf_floor=1, min_samples_leaf_fraction=0.0)
        model.fit(samples)
        assert model.predict({"x": 0.15}) == pytest.approx(0.0)
        assert model.predict({"x": 0.97}) == pytest.approx(10.0)

    def test_a_single_leaf_predicts_the_mean_when_no_split_helps(self) -> None:
        # Constant target -- no split can reduce variance (there is
        # none), so the tree should stay a single leaf predicting the
        # constant value regardless of feature value.
        samples = [_Sample(features={"x": x}, target=5.0) for x in range(10)]
        model = RegressionTreeModel(feature_ids=["x"], max_depth=2)
        model.fit(samples)
        assert model.predict({"x": 3}) == pytest.approx(5.0)
        assert model.predict({"x": 999}) == pytest.approx(5.0)


class TestRegressionTreeHonestyAboutMissingOrInvalidState:
    def test_fit_raises_on_empty_samples(self) -> None:
        with pytest.raises(ValueError):
            RegressionTreeModel(feature_ids=["x"]).fit([])

    def test_fit_raises_on_non_finite_target(self) -> None:
        samples = [_Sample(features={"x": 1.0}, target=float("nan"))]
        with pytest.raises(ValueError):
            RegressionTreeModel(feature_ids=["x"]).fit(samples)

    def test_fit_raises_on_non_finite_feature(self) -> None:
        samples = [_Sample(features={"x": float("inf")}, target=1.0)]
        with pytest.raises(ValueError):
            RegressionTreeModel(feature_ids=["x"]).fit(samples)

    def test_predict_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError):
            RegressionTreeModel(feature_ids=["x"]).predict({"x": 1.0})

    def test_predict_with_missing_feature_raises(self) -> None:
        model = RegressionTreeModel(feature_ids=["x", "y"])
        model.fit([_Sample(features={"x": 1.0, "y": 2.0}, target=1.0), _Sample(features={"x": 2.0, "y": 3.0}, target=2.0)])
        with pytest.raises(ValueError):
            model.predict({"x": 1.0})


class TestBaggedTreeDeterminism:
    def _samples(self, n: int) -> list[_Sample]:
        return [
            _Sample(features={f"f{i}": float((s * 7 + i * 3) % 11) for i in range(6)}, target=float(s % 5))
            for s in range(n)
        ]

    def test_same_samples_and_seed_produce_identical_predictions(self) -> None:
        samples = self._samples(40)
        feature_ids = [f"f{i}" for i in range(6)]
        m1 = BaggedTreeModel(feature_ids=feature_ids, random_seed=123)
        m1.fit(samples)
        m2 = BaggedTreeModel(feature_ids=feature_ids, random_seed=123)
        m2.fit(samples)
        query = samples[0].features
        assert m1.predict(query) == m2.predict(query)

    def test_fit_uses_a_local_rng_not_global_random_state(self) -> None:
        import random

        samples = self._samples(40)
        feature_ids = [f"f{i}" for i in range(6)]
        random.seed(999)
        state_before = random.getstate()
        BaggedTreeModel(feature_ids=feature_ids, random_seed=1).fit(samples)
        assert random.getstate() == state_before


class TestBaggedTreeHonestyAboutMissingOrInvalidState:
    def test_fit_raises_on_empty_samples(self) -> None:
        with pytest.raises(ValueError):
            BaggedTreeModel(feature_ids=["x"]).fit([])

    def test_fit_raises_on_non_finite_target(self) -> None:
        samples = [_Sample(features={"x": 1.0}, target=float("nan"))]
        with pytest.raises(ValueError):
            BaggedTreeModel(feature_ids=["x"]).fit(samples)

    def test_predict_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError):
            BaggedTreeModel(feature_ids=["x"]).predict({"x": 1.0})

    def test_predict_with_missing_feature_raises(self) -> None:
        feature_ids = [f"f{i}" for i in range(6)]
        samples = [
            _Sample(features={f"f{i}": float(s + i) for i in range(6)}, target=float(s))
            for s in range(20)
        ]
        model = BaggedTreeModel(feature_ids=feature_ids)
        model.fit(samples)
        with pytest.raises(ValueError):
            model.predict({"f0": 1.0})

    def test_n_trees_fit_is_zero_before_fit_and_positive_after(self) -> None:
        feature_ids = [f"f{i}" for i in range(6)]
        samples = [
            _Sample(features={f"f{i}": float((s * 7 + i * 3) % 11) for i in range(6)}, target=float(s % 5))
            for s in range(40)
        ]
        model = BaggedTreeModel(feature_ids=feature_ids)
        assert model.n_trees_fit == 0
        model.fit(samples)
        assert 0 < model.n_trees_fit <= model.n_estimators


class TestBaggedTreeEnsembleReducesVarianceVsSingleTree:
    def test_ensemble_prediction_is_the_mean_of_its_trees(self) -> None:
        feature_ids = [f"f{i}" for i in range(6)]
        samples = [
            _Sample(features={f"f{i}": float((s * 7 + i * 3) % 11) for i in range(6)}, target=float(s % 5))
            for s in range(40)
        ]
        model = BaggedTreeModel(feature_ids=feature_ids, random_seed=5)
        model.fit(samples)
        query = samples[0].features
        manual_mean = sum(tree.predict(query) for tree in model._trees) / len(model._trees)
        assert model.predict(query) == pytest.approx(manual_mean)
