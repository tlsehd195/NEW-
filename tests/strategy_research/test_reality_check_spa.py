"""Tests for strategy_research.reality_check_spa (White's Reality Check
and Hansen's SPA test).

SYNTHETIC FIXTURES ONLY -- proves the calculation correctly distinguishes
a genuine, planted edge from pure noise against known-labeled inputs,
not a claim about any real strategy."""

from __future__ import annotations

import random

import pytest

from strategy_research.reality_check_spa import (
    RealityCheckResult,
    SpaResult,
    excess_returns_vs_benchmark,
    hansen_spa,
    white_reality_check,
)


def _seeded_rng(seed: int) -> random.Random:
    return random.Random(seed)


class TestExcessReturnsVsBenchmark:
    def test_computes_pairwise_difference(self) -> None:
        result = excess_returns_vs_benchmark(
            {"a": [0.05, 0.02, -0.01], "b": [0.01, 0.01, 0.01]},
            benchmark_fold_returns=[0.02, 0.0, 0.0],
        )
        assert result["a"] == pytest.approx([0.03, 0.02, -0.01])
        assert result["b"] == pytest.approx([-0.01, 0.01, 0.01])

    def test_raises_on_mismatched_fold_count(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            excess_returns_vs_benchmark({"a": [0.01, 0.02]}, benchmark_fold_returns=[0.0])


class TestWhiteRealityCheck:
    def test_genuine_edge_over_benchmark_gets_low_p_value(self) -> None:
        rng = _seeded_rng(1)
        n_folds = 40
        good = [rng.gauss(0.02, 0.01) for _ in range(n_folds)]
        noise_a = [rng.gauss(0.0, 0.01) for _ in range(n_folds)]
        noise_b = [rng.gauss(0.0, 0.01) for _ in range(n_folds)]

        result = white_reality_check(
            {"good": good, "noise_a": noise_a, "noise_b": noise_b},
            num_bootstrap_samples=500,
            seed=42,
        )
        assert isinstance(result, RealityCheckResult)
        assert result.best_candidate == "good"
        assert result.p_value < 0.05
        assert result.num_folds == n_folds

    def test_pure_noise_candidates_get_high_p_value(self) -> None:
        # Under the null (no candidate truly beats the benchmark), the
        # Reality Check p-value is approximately Uniform(0, 1) by
        # construction -- this seed/bootstrap-seed pair was checked to
        # land well above the rejection threshold, not cherry-picked
        # for an extreme value.
        rng = _seeded_rng(0)
        n_folds = 40
        candidates = {
            f"noise_{i}": [rng.gauss(0.0, 0.01) for _ in range(n_folds)] for i in range(4)
        }
        result = white_reality_check(candidates, num_bootstrap_samples=500, seed=7)
        assert result.p_value > 0.2

    def test_requires_matching_fold_counts(self) -> None:
        with pytest.raises(ValueError, match="same fold count"):
            white_reality_check({"a": [0.01, 0.02], "b": [0.01]})

    def test_requires_at_least_two_folds(self) -> None:
        with pytest.raises(ValueError, match="need at least 2 folds"):
            white_reality_check({"a": [0.01]})


class TestHansenSpa:
    def test_genuine_edge_over_benchmark_gets_low_p_value(self) -> None:
        rng = _seeded_rng(3)
        n_folds = 40
        good = [rng.gauss(0.02, 0.01) for _ in range(n_folds)]
        noise_a = [rng.gauss(0.0, 0.01) for _ in range(n_folds)]
        noise_b = [rng.gauss(0.0, 0.01) for _ in range(n_folds)]

        result = hansen_spa(
            {"good": good, "noise_a": noise_a, "noise_b": noise_b},
            num_bootstrap_samples=500,
            seed=42,
        )
        assert isinstance(result, SpaResult)
        assert result.best_candidate == "good"
        assert result.p_value < 0.05

    def test_pure_noise_candidates_get_high_p_value(self) -> None:
        # See the matching Reality Check test's comment: under the null
        # the p-value is approximately Uniform(0, 1); this seed pair
        # was checked to land well above the rejection threshold.
        rng = _seeded_rng(0)
        n_folds = 40
        candidates = {
            f"noise_{i}": [rng.gauss(0.0, 0.01) for _ in range(n_folds)] for i in range(4)
        }
        result = hansen_spa(candidates, num_bootstrap_samples=500, seed=7)
        assert result.p_value > 0.2

    def test_requires_matching_fold_counts(self) -> None:
        with pytest.raises(ValueError, match="same fold count"):
            hansen_spa({"a": [0.01, 0.02], "b": [0.01]})
