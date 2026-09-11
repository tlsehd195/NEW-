"""MonitoringConfig: every threshold Monitoring uses, kept out of code
-- the same discipline `risk.config`/`ai_gateway.config`/`broker.config`
already established.

See docs/specifications/PHASE-14-monitoring.md section 6.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class MonitoringConfig:
    version: str = "monitoring_config_v1"

    # -- generic sample-size gate: below this, any metric/health/drift
    # result is UNKNOWN rather than computed from too little data --
    min_sample_count: int = 5

    # -- failure-rate-based health (Broker/AI Gateway/Risk rejections) --
    degraded_failure_rate_threshold: float = 0.10
    unavailable_failure_rate_threshold: float = 0.50

    # -- data quality --
    stale_data_max_age_seconds: float = 172_800.0  # 2 days
    degraded_invalid_rate_threshold: float = 0.05
    unavailable_invalid_rate_threshold: float = 0.25

    # -- existence/production health (Prediction/Decision/Regime/Learning
    # "is this component still producing output at all") --
    degraded_min_expected_count: int = 1

    # -- drift detection --
    min_drift_sample_count: int = 10
    mean_shift_z_threshold: float = 2.0
    variance_shift_ratio_threshold: float = 2.0
    distribution_shift_bucket_count: int = 5
    distribution_shift_threshold: float = 0.25  # simple bucket-frequency-difference statistic, documented as not true PSI (ADR-0020)

    def __post_init__(self) -> None:
        if self.min_sample_count <= 0:
            raise ValueError("min_sample_count must be positive")
        if not 0.0 <= self.degraded_failure_rate_threshold <= 1.0:
            raise ValueError("degraded_failure_rate_threshold must be in [0, 1]")
        if not 0.0 <= self.unavailable_failure_rate_threshold <= 1.0:
            raise ValueError("unavailable_failure_rate_threshold must be in [0, 1]")
        if self.unavailable_failure_rate_threshold < self.degraded_failure_rate_threshold:
            raise ValueError("unavailable_failure_rate_threshold must be >= degraded_failure_rate_threshold")
        if self.stale_data_max_age_seconds <= 0:
            raise ValueError("stale_data_max_age_seconds must be positive")
        if self.degraded_min_expected_count < 0:
            raise ValueError("degraded_min_expected_count must not be negative")
        if self.min_drift_sample_count < 2:
            # detect_mean_shift/detect_variance_shift compute sample
            # variance with an (n - 1) denominator; a threshold of 1
            # would let a single-sample window pass the sample-size
            # gate and then crash with ZeroDivisionError instead of
            # producing DriftStatus.UNKNOWN (ADR-0115).
            raise ValueError("min_drift_sample_count must be at least 2")
        if self.mean_shift_z_threshold <= 0:
            raise ValueError("mean_shift_z_threshold must be positive")
        if self.variance_shift_ratio_threshold <= 1.0:
            raise ValueError("variance_shift_ratio_threshold must be greater than 1.0")
        if self.distribution_shift_bucket_count < 2:
            raise ValueError("distribution_shift_bucket_count must be at least 2")
        if not 0.0 <= self.distribution_shift_threshold <= 2.0:
            raise ValueError("distribution_shift_threshold must be in [0, 2]")

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_MONITORING_CONFIG = MonitoringConfig()
