import numpy as np
import pytest

from strategy_research.reality_check import compute_reality_check


def _noise(k, n, seed=1, scale=0.05):
    rng = np.random.default_rng(seed)
    base = rng.normal(0.01, scale, n)
    return {f"c{i}": list(base + rng.normal(0, scale, n)) for i in range(k)}, list(base)


def test_pure_noise_not_significant():
    cands, base = _noise(20, 40)
    r = compute_reality_check(cands, base, num_bootstrap=500, seed=3)
    assert r.reality_check_p_value > 0.1 and r.spa_p_value > 0.1
    assert r.num_candidates == 20 and r.num_observations == 40


def test_true_edge_detected_even_among_noise():
    cands, base = _noise(10, 60)
    cands["edge"] = [b + 0.05 + e for b, e in zip(base, np.random.default_rng(9).normal(0, 0.01, 60))]
    r = compute_reality_check(cands, base, num_bootstrap=500, seed=3)
    assert r.best_candidate == "edge"
    assert r.reality_check_p_value < 0.05 and r.spa_p_value < 0.05


def test_deterministic_and_validates_input():
    cands, base = _noise(3, 20)
    a = compute_reality_check(cands, base, num_bootstrap=200, seed=5)
    assert a == compute_reality_check(cands, base, num_bootstrap=200, seed=5)
    with pytest.raises(ValueError):
        compute_reality_check({"a": [0.1] * 5}, [0.0] * 4)
    with pytest.raises(ValueError):
        compute_reality_check({}, [0.0] * 10)
