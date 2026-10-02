"""White Reality Check and Hansen SPA over per-fold excess returns.

White (2000, Econometrica 68(5)) and Hansen (2005, JBES 23(4)): given K
candidates' excess return against a baseline, test H0 "no candidate beats
the baseline" while accounting for having looked at all K. Inputs are the
fold returns the walk-forward run already produced (no new backtest);
excess_k[t] = candidate_k[t] - baseline[t].

Resampling is the stationary bootstrap (Politis & Romano 1994) with
geometric block lengths, because overlapping rolling folds are
autocorrelated. The same resampled indices are used for every candidate so
cross-candidate dependence is preserved. Results are deterministic for a
given `seed`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RealityCheckResult:
    reality_check_p_value: float  # White (2000), centered at 0
    spa_p_value: float  # Hansen (2005), lower-bound recentering ("consistent" p)
    best_candidate: str
    best_mean_excess: float
    num_candidates: int
    num_observations: int
    num_bootstrap: int
    mean_block_length: float


def _stationary_indices(n: int, mean_block: float, num_bootstrap: int, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / mean_block
    idx = np.empty((num_bootstrap, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, size=num_bootstrap)
    restart = rng.random((num_bootstrap, n)) < p
    fresh = rng.integers(0, n, size=(num_bootstrap, n))
    for t in range(1, n):
        idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def compute_reality_check(
    fold_returns_by_candidate: Mapping[str, Sequence[float]],
    baseline_returns: Sequence[float],
    *,
    num_bootstrap: int = 2000,
    mean_block_length: float | None = None,
    seed: int = 0,
) -> RealityCheckResult:
    names = tuple(sorted(fold_returns_by_candidate))
    if not names:
        raise ValueError("need at least 1 candidate")
    n = len(baseline_returns)
    if n < 4:
        raise ValueError(f"need at least 4 folds, got {n}")
    for name in names:
        if len(fold_returns_by_candidate[name]) != n:
            raise ValueError(
                f"{name!r} has {len(fold_returns_by_candidate[name])} folds, baseline has {n}"
            )
    if num_bootstrap < 100:
        raise ValueError("num_bootstrap must be >= 100")

    base = np.asarray(baseline_returns, dtype=float)
    d = np.array([np.asarray(fold_returns_by_candidate[k], dtype=float) - base for k in names]).T  # (n, K)
    block = mean_block_length if mean_block_length is not None else max(2.0, round(n ** (1 / 3)))
    if block < 1:
        raise ValueError("mean_block_length must be >= 1")

    mean_d = d.mean(axis=0)
    rng = np.random.default_rng(seed)
    idx = _stationary_indices(n, block, num_bootstrap, rng)
    boot_mean = d[idx].mean(axis=1)  # (B, K)
    boot_dev = boot_mean - mean_d  # bootstrap fluctuation of the mean

    # White: V = max_k sqrt(n) * mean_k, null distribution from centered bootstrap.
    v = math.sqrt(n) * float(mean_d.max())
    v_boot = math.sqrt(n) * boot_dev.max(axis=1)
    rc_p = float((v_boot >= v).mean())

    # Hansen SPA: studentize; recenter only candidates not clearly inferior.
    omega = boot_dev.std(axis=0) * math.sqrt(n)
    omega = np.where(omega <= 1e-12, np.inf, omega)  # zero-variance candidate cannot be superior
    t_stat = math.sqrt(n) * mean_d / omega
    t_spa = max(0.0, float(t_stat.max()))
    threshold = -math.sqrt(2 * math.log(math.log(max(n, 3))))
    mu_c = np.where(t_stat <= threshold, mean_d, 0.0)
    z_boot = math.sqrt(n) * (boot_mean - mean_d + mu_c) / omega
    # recentered at mu_c: E*[boot_mean] = mean_d, so subtract mean_d and add mu_c
    t_boot = np.maximum(0.0, z_boot.max(axis=1))
    spa_p = float((t_boot >= t_spa).mean())

    best = int(np.argmax(mean_d))
    return RealityCheckResult(
        reality_check_p_value=rc_p,
        spa_p_value=spa_p,
        best_candidate=names[best],
        best_mean_excess=float(mean_d[best]),
        num_candidates=len(names),
        num_observations=n,
        num_bootstrap=num_bootstrap,
        mean_block_length=float(block),
    )
