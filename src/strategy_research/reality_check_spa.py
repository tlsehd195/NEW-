"""White's Reality Check (White 2000) and Hansen's Superior Predictive
Ability test (Hansen 2005): do any of several candidates' apparent
out-of-sample edge over a benchmark survive a test that accounts for
having tried many candidates, or is the apparent best-of-N winner what
you'd expect from data snooping alone?

Both answer a question closely related to, but distinct from, this
project's existing [[compute_pbo]]/[[compute_dsr_for_all_candidates]]
(`strategy_research.pbo_dsr`): PBO/DSR ask whether the IS-winner's rank
persists OOS (or deflate its Sharpe for the size of the trial pool).
White/Hansen instead directly bootstrap the sampling distribution of
"best candidate's mean excess return over the benchmark" under the null
that no candidate truly beats the benchmark, which is the same question
this project already asks informally via `verdict_against_buy_and_hold`
(`backtest.evidence` / `scripts/run_long_horizon_validation.py`) but
without any account for having compared many candidates at once.

This module is deliberately a SUPPLEMENTARY diagnostic, not a gate: it
is computed from the same per-fold NET returns `compute_pbo_dsr_from_
report.py` already extracts, and is recorded in the report as an
additional field alongside -- never in place of -- the existing PASS/
FAIL verdicts and evidence levels. It does not change any existing
judgement.

References (Tier 1 -- primary sources):
- White, H. (2000). "A Reality Check for Data Snooping." Econometrica,
  68(5), 1097-1126.
- Hansen, P. R. (2005). "A Test for Superior Predictive Ability."
  Journal of Business & Economic Statistics, 23(4), 365-380.
- Politis, D. N., & Romano, J. P. (1994). "The Stationary Bootstrap."
  Journal of the American Statistical Association, 89(428), 1303-1313.
  (the resampling scheme both tests above are built on, used here to
  preserve whatever short-range dependence exists across folds.)

Adaptation from the original papers, stated explicitly: both papers
operate on per-PERIOD (daily) loss/return differentials. Exactly like
`pbo_dsr.py`, this module treats each walk-forward FOLD's NET return as
one observation -- the same fold-level granularity already used
throughout this project's statistical layer, for the same reason (each
fold is already an independent, non-overlapping out-of-sample window).

Pure computation over already-computed return series -- no network
access, no wall-clock reads. Randomness is confined to the bootstrap
resampling and is always seeded by the caller."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

_normal = statistics.NormalDist()


@dataclass(frozen=True)
class RealityCheckResult:
    """`p_value` is White's Reality Check p-value: the bootstrap
    probability of seeing a max-candidate excess mean at least as large
    as the one actually observed, under the null that no candidate
    truly beats the benchmark. Low (e.g. < 0.05) means the best
    candidate's apparent edge is unlikely to be a data-snooping
    artifact."""

    p_value: float
    observed_statistic: float
    best_candidate: str
    num_bootstrap_samples: int
    num_folds: int
    candidate_names: tuple[str, ...]


@dataclass(frozen=True)
class SpaResult:
    """Hansen's SPA test, consistent p-value variant (Hansen 2005, eq.
    15-16): like Reality Check but studentizes each candidate's excess
    mean by its own bootstrap standard error and recenters poorly
    performing candidates toward zero before resampling, which makes it
    less conservative (more power) than the plain Reality Check without
    losing validity under the null."""

    p_value: float
    observed_statistic: float
    best_candidate: str
    num_bootstrap_samples: int
    num_folds: int
    candidate_names: tuple[str, ...]


def _validate_excess_returns(
    excess_returns_by_candidate: Mapping[str, Sequence[float]],
) -> tuple[tuple[str, ...], int]:
    names = tuple(sorted(excess_returns_by_candidate))
    if len(names) < 1:
        raise ValueError("need at least 1 candidate")
    n = len(excess_returns_by_candidate[names[0]])
    for name in names:
        if len(excess_returns_by_candidate[name]) != n:
            raise ValueError(
                f"all candidates must have the same fold count in the same order; "
                f"{names[0]!r} has {n}, {name!r} has {len(excess_returns_by_candidate[name])}"
            )
    if n < 2:
        raise ValueError(f"need at least 2 folds, got {n}")
    return names, n


def excess_returns_vs_benchmark(
    fold_returns_by_candidate: Mapping[str, Sequence[float]],
    benchmark_fold_returns: Sequence[float],
) -> dict[str, list[float]]:
    """`candidate_fold_return - benchmark_fold_return` for every fold,
    per candidate. The caller is responsible for ensuring every
    sequence refers to the SAME fold indices in the SAME order (exactly
    the same requirement `pbo_dsr.compute_pbo` already places on its
    own `fold_returns_by_candidate` argument)."""
    n = len(benchmark_fold_returns)
    for name, returns in fold_returns_by_candidate.items():
        if len(returns) != n:
            raise ValueError(
                f"candidate {name!r} has {len(returns)} fold returns, "
                f"benchmark has {n} -- must match"
            )
    return {
        name: [r - b for r, b in zip(returns, benchmark_fold_returns)]
        for name, returns in fold_returns_by_candidate.items()
    }


def _stationary_bootstrap_sample_indices(
    n: int, *, mean_block_length: float, rng: np.random.Generator
) -> list[int]:
    """One resampled index path of length `n` via the stationary
    bootstrap (Politis & Romano 1994): blocks of geometric-distributed
    length wrap circularly around the original series, so short-range
    dependence across adjacent folds is preserved rather than destroyed
    by i.i.d. resampling."""
    p = 1.0 / mean_block_length
    indices: list[int] = []
    current = int(rng.integers(n))
    while len(indices) < n:
        indices.append(current)
        if rng.random() < p:
            current = int(rng.integers(n))
        else:
            current = (current + 1) % n
    return indices


def white_reality_check(
    excess_returns_by_candidate: Mapping[str, Sequence[float]],
    *,
    num_bootstrap_samples: int = 2000,
    mean_block_length: float = 4.0,
    seed: int = 0,
) -> RealityCheckResult:
    """White (2000) Reality Check, eq. 2.4-2.5's bootstrap p-value.

    `excess_returns_by_candidate`: `{candidate_name: [excess_return_per_fold, ...]}`,
    i.e. already `candidate - benchmark` per fold (see
    `excess_returns_vs_benchmark`). All candidates must share the same
    fold count and order.

    `mean_block_length` is the stationary bootstrap's average block
    length in folds (Politis & Romano 1994); 4.0 is a conventional
    default for short dependent series, not tuned against any observed
    result here."""
    names, n = _validate_excess_returns(excess_returns_by_candidate)
    means = {name: statistics.mean(excess_returns_by_candidate[name]) for name in names}
    observed_statistic = max(math.sqrt(n) * means[name] for name in names)
    best_candidate = max(names, key=lambda name: means[name])

    rng = np.random.default_rng(seed)
    exceed_count = 0
    for _ in range(num_bootstrap_samples):
        idx = _stationary_bootstrap_sample_indices(n, mean_block_length=mean_block_length, rng=rng)
        boot_stat = max(
            math.sqrt(n) * (
                statistics.mean(excess_returns_by_candidate[name][i] for i in idx) - means[name]
            )
            for name in names
        )
        if boot_stat >= observed_statistic:
            exceed_count += 1

    return RealityCheckResult(
        p_value=exceed_count / num_bootstrap_samples,
        observed_statistic=observed_statistic,
        best_candidate=best_candidate,
        num_bootstrap_samples=num_bootstrap_samples,
        num_folds=n,
        candidate_names=names,
    )


def hansen_spa(
    excess_returns_by_candidate: Mapping[str, Sequence[float]],
    *,
    num_bootstrap_samples: int = 2000,
    mean_block_length: float = 4.0,
    seed: int = 0,
) -> SpaResult:
    """Hansen (2005) SPA test, consistent p-value (eq. 15-16 combined
    with the studentized statistic of eq. 7 and the recentering rule of
    eq. 16-17): studentizes each candidate's excess mean by its own
    bootstrap standard error, and recenters candidates whose observed
    mean is unlikely to be positive toward zero before resampling
    (candidates that clearly underperform contribute noise, not signal,
    to the null distribution of the best performer)."""
    names, n = _validate_excess_returns(excess_returns_by_candidate)
    means = {name: statistics.mean(excess_returns_by_candidate[name]) for name in names}

    rng = np.random.default_rng(seed)
    # Bootstrap resamples drawn once, reused to estimate both each
    # candidate's bootstrap stdev and the SPA null statistic itself --
    # standard practice (Hansen 2005 section 3) rather than drawing two
    # independent sets of samples.
    boot_index_paths = [
        _stationary_bootstrap_sample_indices(n, mean_block_length=mean_block_length, rng=rng)
        for _ in range(num_bootstrap_samples)
    ]
    boot_means: dict[str, list[float]] = {
        name: [
            statistics.mean(excess_returns_by_candidate[name][i] for i in idx)
            for idx in boot_index_paths
        ]
        for name in names
    }
    stdev_by_name = {
        name: statistics.pstdev(boot_means[name]) * math.sqrt(n) or 1e-12
        for name in names
    }

    studentized_statistic = {name: math.sqrt(n) * means[name] / stdev_by_name[name] for name in names}
    observed_statistic = max(studentized_statistic.values())
    best_candidate = max(names, key=lambda name: studentized_statistic[name])

    # Hansen's recentering rule (eq. 16, "consistent" variant): a
    # candidate whose observed mean does not clearly exceed zero is
    # pulled back to its lower bound of plausibly-zero performance
    # before resampling, instead of being left at its (noisy, possibly
    # spuriously high) observed mean -- this is what makes SPA less
    # conservative than the plain Reality Check without admitting
    # genuinely bad candidates into the null distribution at full
    # strength.
    recenter_threshold = {
        name: -math.sqrt(2 * math.log(math.log(max(n, 3))) / n) * (stdev_by_name[name] / math.sqrt(n))
        for name in names
    }
    recentered_mean = {
        name: means[name] if means[name] > recenter_threshold[name] else 0.0
        for name in names
    }

    exceed_count = 0
    for b, idx in enumerate(boot_index_paths):
        boot_stat = max(
            math.sqrt(n) * (boot_means[name][b] - recentered_mean[name]) / stdev_by_name[name]
            for name in names
        )
        if boot_stat >= observed_statistic:
            exceed_count += 1

    return SpaResult(
        p_value=exceed_count / num_bootstrap_samples,
        observed_statistic=observed_statistic,
        best_candidate=best_candidate,
        num_bootstrap_samples=num_bootstrap_samples,
        num_folds=n,
        candidate_names=names,
    )
