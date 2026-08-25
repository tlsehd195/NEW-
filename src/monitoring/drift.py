"""Deterministic baseline drift detectors -- PROJECT_MASTER_PLAN.md
section 11.6: "Drift가 감지되면 자동으로 모델을 교체하지 않고,
Monitoring/Alerting을 거쳐 재검증 프로세스를 트리거한다." Every function
here only ever produces an *observation* (`DriftStatus.NO_DRIFT`/
`DRIFT_DETECTED`/`UNKNOWN`) -- nothing in this module (or anywhere else
in `monitoring.*`) replaces a model, changes a risk limit, or halts
trading.

See docs/specifications/PHASE-14-monitoring.md section 10.

Statistically simple and deterministic by design (instruction section
10: "초기 구현은 통계적으로 단순하고 deterministic한 방법을 사용하라") --
mean shift (z-score against baseline stdev), variance shift (ratio of
sample variances), and a bucket-frequency-difference statistic
documented as a simplified, not textbook-exact, PSI (ADR-0020). All
three return `UNKNOWN` when either sample is below
`MonitoringConfig.min_drift_sample_count` -- never a guessed verdict
from too little data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from monitoring.config import MonitoringConfig
from monitoring.enums import DriftStatus, MonitoringComponent
from monitoring.models import DriftResult


def _finite(value: Optional[float]) -> bool:
    if value is None:
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def _clean(values: Sequence[float]) -> list[float]:
    return [v for v in values if _finite(v)]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _variance(values: Sequence[float]) -> float:
    mean = _mean(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _unknown(
    drift_id: str, component: MonitoringComponent, metric_name: str, *, as_of_time: datetime,
    config: MonitoringConfig, reason: str, sample_count_baseline: Optional[int], sample_count_current: Optional[int],
) -> DriftResult:
    return DriftResult(
        drift_id=drift_id, component=component, metric_name=metric_name, status=DriftStatus.UNKNOWN,
        statistic=None, threshold=None, as_of_time=as_of_time,
        sample_count_baseline=sample_count_baseline, sample_count_current=sample_count_current,
        configuration_version=config.configuration_version(), reason=reason,
    )


def detect_mean_shift(
    baseline: Sequence[float], current: Sequence[float], *, component: MonitoringComponent, metric_name: str,
    config: MonitoringConfig, as_of_time: datetime, drift_id: str,
) -> DriftResult:
    baseline_clean, current_clean = _clean(baseline), _clean(current)
    n_base, n_cur = len(baseline_clean), len(current_clean)

    if n_base < config.min_drift_sample_count or n_cur < config.min_drift_sample_count:
        return _unknown(
            drift_id, component, metric_name, as_of_time=as_of_time, config=config,
            reason="insufficient_sample", sample_count_baseline=n_base, sample_count_current=n_cur,
        )

    baseline_mean = _mean(baseline_clean)
    baseline_var = _variance(baseline_clean)
    baseline_stdev = baseline_var**0.5
    if baseline_stdev == 0:
        return _unknown(
            drift_id, component, metric_name, as_of_time=as_of_time, config=config,
            reason="zero_baseline_stdev", sample_count_baseline=n_base, sample_count_current=n_cur,
        )

    current_mean = _mean(current_clean)
    z_score = abs(current_mean - baseline_mean) / baseline_stdev
    status = DriftStatus.DRIFT_DETECTED if z_score >= config.mean_shift_z_threshold else DriftStatus.NO_DRIFT

    return DriftResult(
        drift_id=drift_id, component=component, metric_name=metric_name, status=status,
        statistic=z_score, threshold=config.mean_shift_z_threshold, as_of_time=as_of_time,
        baseline_summary={"mean": baseline_mean, "stdev": baseline_stdev},
        current_summary={"mean": current_mean},
        sample_count_baseline=n_base, sample_count_current=n_cur,
        configuration_version=config.configuration_version(),
        reason=f"z_score={z_score:.4f}_threshold={config.mean_shift_z_threshold}",
    )


def detect_variance_shift(
    baseline: Sequence[float], current: Sequence[float], *, component: MonitoringComponent, metric_name: str,
    config: MonitoringConfig, as_of_time: datetime, drift_id: str,
) -> DriftResult:
    baseline_clean, current_clean = _clean(baseline), _clean(current)
    n_base, n_cur = len(baseline_clean), len(current_clean)

    if n_base < config.min_drift_sample_count or n_cur < config.min_drift_sample_count:
        return _unknown(
            drift_id, component, metric_name, as_of_time=as_of_time, config=config,
            reason="insufficient_sample", sample_count_baseline=n_base, sample_count_current=n_cur,
        )

    baseline_var = _variance(baseline_clean)
    current_var = _variance(current_clean)
    if baseline_var == 0 or current_var == 0:
        return _unknown(
            drift_id, component, metric_name, as_of_time=as_of_time, config=config,
            reason="zero_variance", sample_count_baseline=n_base, sample_count_current=n_cur,
        )

    ratio = max(current_var, baseline_var) / min(current_var, baseline_var)
    status = DriftStatus.DRIFT_DETECTED if ratio >= config.variance_shift_ratio_threshold else DriftStatus.NO_DRIFT

    return DriftResult(
        drift_id=drift_id, component=component, metric_name=metric_name, status=status,
        statistic=ratio, threshold=config.variance_shift_ratio_threshold, as_of_time=as_of_time,
        baseline_summary={"variance": baseline_var}, current_summary={"variance": current_var},
        sample_count_baseline=n_base, sample_count_current=n_cur,
        configuration_version=config.configuration_version(),
        reason=f"variance_ratio={ratio:.4f}_threshold={config.variance_shift_ratio_threshold}",
    )


def detect_distribution_shift(
    baseline: Sequence[float], current: Sequence[float], *, component: MonitoringComponent, metric_name: str,
    config: MonitoringConfig, as_of_time: datetime, drift_id: str,
) -> DriftResult:
    """A simplified, deterministic bucket-frequency-difference
    statistic -- equal-width buckets spanning the *baseline*'s own
    [min, max] range (never the current window's range, so the bucket
    edges are a pure function of the baseline alone). Documented as
    "PSI-like," not a textbook Population Stability Index (ADR-0020) --
    values outside the baseline range fall into the nearest edge
    bucket rather than being dropped, so no observation is silently
    excluded."""
    baseline_clean, current_clean = _clean(baseline), _clean(current)
    n_base, n_cur = len(baseline_clean), len(current_clean)

    if n_base < config.min_drift_sample_count or n_cur < config.min_drift_sample_count:
        return _unknown(
            drift_id, component, metric_name, as_of_time=as_of_time, config=config,
            reason="insufficient_sample", sample_count_baseline=n_base, sample_count_current=n_cur,
        )

    lo, hi = min(baseline_clean), max(baseline_clean)
    if lo == hi:
        return _unknown(
            drift_id, component, metric_name, as_of_time=as_of_time, config=config,
            reason="degenerate_baseline_range", sample_count_baseline=n_base, sample_count_current=n_cur,
        )

    bucket_count = config.distribution_shift_bucket_count
    width = (hi - lo) / bucket_count

    def bucket_of(value: float) -> int:
        if value <= lo:
            return 0
        if value >= hi:
            return bucket_count - 1
        return min(bucket_count - 1, int((value - lo) / width))

    baseline_freq = [0] * bucket_count
    for v in baseline_clean:
        baseline_freq[bucket_of(v)] += 1
    current_freq = [0] * bucket_count
    for v in current_clean:
        current_freq[bucket_of(v)] += 1

    statistic = sum(
        abs(b / n_base - c / n_cur) for b, c in zip(baseline_freq, current_freq)
    )
    status = DriftStatus.DRIFT_DETECTED if statistic >= config.distribution_shift_threshold else DriftStatus.NO_DRIFT

    return DriftResult(
        drift_id=drift_id, component=component, metric_name=metric_name, status=status,
        statistic=statistic, threshold=config.distribution_shift_threshold, as_of_time=as_of_time,
        baseline_summary={"bucket_frequencies": baseline_freq, "range": [lo, hi]},
        current_summary={"bucket_frequencies": current_freq},
        sample_count_baseline=n_base, sample_count_current=n_cur,
        configuration_version=config.configuration_version(),
        reason=f"bucket_frequency_difference={statistic:.4f}_threshold={config.distribution_shift_threshold}",
    )
