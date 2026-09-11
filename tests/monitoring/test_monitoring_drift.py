"""Category: Drift Test -- no-drift/mean-shift/variance-shift/
distribution-shift/insufficient-sample/deterministic-replay. Every
detector produces an observation only (`DriftStatus`), never an action;
`UNKNOWN` whenever a sample is degenerate or below
`MonitoringConfig.min_drift_sample_count`."""

from __future__ import annotations

from monitoring_helpers import make_config, utc

import pytest

from monitoring.config import MonitoringConfig
from monitoring.drift import detect_distribution_shift, detect_mean_shift, detect_variance_shift
from monitoring.enums import DriftStatus, MonitoringComponent


class TestMeanShift:
    def test_no_drift_when_means_close(self) -> None:
        config = make_config(min_drift_sample_count=10)
        baseline = [1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 1.0, 1.1, 0.9, 1.0]
        current = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        result = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.NO_DRIFT

    def test_drift_detected_on_large_shift(self) -> None:
        config = make_config(min_drift_sample_count=10, mean_shift_z_threshold=2.0)
        baseline = [1.0, 1.1, 0.9, 1.0, 1.05, 0.95, 1.0, 1.1, 0.9, 1.0]
        current = [10.0] * 10
        result = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.DRIFT_DETECTED

    def test_unknown_when_insufficient_sample(self) -> None:
        config = make_config(min_drift_sample_count=10)
        result = detect_mean_shift(
            [1.0, 2.0], [1.0, 2.0], component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.UNKNOWN
        assert result.reason == "insufficient_sample"

    def test_unknown_when_baseline_stdev_zero(self) -> None:
        config = make_config(min_drift_sample_count=5)
        result = detect_mean_shift(
            [1.0] * 5, [2.0] * 5, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.UNKNOWN
        assert result.reason == "zero_baseline_stdev"

    def test_non_finite_values_are_excluded(self) -> None:
        config = make_config(min_drift_sample_count=5)
        baseline = [1.0, 1.0, 1.0, 1.0, 1.0, float("nan")]
        current = [1.0, 1.0, 1.0, 1.0, 1.0]
        result = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.sample_count_baseline == 5


class TestVarianceShift:
    def test_no_drift_when_variances_close(self) -> None:
        config = make_config(min_drift_sample_count=5, variance_shift_ratio_threshold=2.0)
        baseline = [1.0, 2.0, 3.0, 4.0, 5.0]
        current = [1.1, 2.1, 3.1, 4.1, 5.1]
        result = detect_variance_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_volatility",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.NO_DRIFT

    def test_drift_detected_on_large_variance_ratio(self) -> None:
        config = make_config(min_drift_sample_count=5, variance_shift_ratio_threshold=2.0)
        baseline = [1.0, 1.0, 1.0, 1.0, 1.0001]
        current = [1.0, 100.0, -100.0, 50.0, -50.0]
        result = detect_variance_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_volatility",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.DRIFT_DETECTED

    def test_unknown_when_zero_variance(self) -> None:
        config = make_config(min_drift_sample_count=5)
        result = detect_variance_shift(
            [1.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], component=MonitoringComponent.PREDICTION,
            metric_name="expected_volatility", config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.UNKNOWN
        assert result.reason == "zero_variance"


class TestDistributionShift:
    def test_no_drift_for_identical_distributions(self) -> None:
        config = make_config(min_drift_sample_count=10, distribution_shift_threshold=0.25)
        baseline = [float(i) for i in range(10)]
        current = [float(i) for i in range(10)]
        result = detect_distribution_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="confidence",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.NO_DRIFT

    def test_drift_detected_when_current_concentrated_in_one_bucket(self) -> None:
        config = make_config(min_drift_sample_count=10, distribution_shift_threshold=0.25)
        baseline = [float(i) for i in range(10)]
        current = [0.0] * 10
        result = detect_distribution_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="confidence",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.DRIFT_DETECTED

    def test_unknown_when_baseline_range_degenerate(self) -> None:
        config = make_config(min_drift_sample_count=5)
        result = detect_distribution_shift(
            [1.0] * 5, [1.0, 2.0, 3.0, 4.0, 5.0], component=MonitoringComponent.PREDICTION,
            metric_name="confidence", config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.UNKNOWN
        assert result.reason == "degenerate_baseline_range"

    def test_values_outside_baseline_range_clamp_not_dropped(self) -> None:
        config = make_config(min_drift_sample_count=5, distribution_shift_bucket_count=5)
        baseline = [0.0, 1.0, 2.0, 3.0, 4.0]
        current = [-100.0, 200.0, 2.0, 2.0, 2.0]
        result = detect_distribution_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="confidence",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert sum(result.current_summary["bucket_frequencies"]) == 5

    def test_unknown_when_insufficient_sample(self) -> None:
        config = make_config(min_drift_sample_count=10)
        result = detect_distribution_shift(
            [1.0, 2.0], [1.0, 2.0], component=MonitoringComponent.PREDICTION, metric_name="confidence",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status == DriftStatus.UNKNOWN


class TestMinDriftSampleCountFloor:
    def test_a_threshold_of_one_is_rejected_at_construction(self) -> None:
        # detect_mean_shift/detect_variance_shift compute sample
        # variance with an (n - 1) denominator; a threshold of 1 would
        # let a single-sample window pass the sample-size gate and
        # then crash with ZeroDivisionError instead of producing
        # DriftStatus.UNKNOWN (ADR-0115).
        with pytest.raises(ValueError, match="min_drift_sample_count"):
            MonitoringConfig(min_drift_sample_count=1)

    def test_a_threshold_of_two_is_the_lowest_accepted_value(self) -> None:
        config = MonitoringConfig(min_drift_sample_count=2)
        result = detect_mean_shift(
            [1.0, 1.0], [2.0, 2.0], component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert result.status in (DriftStatus.NO_DRIFT, DriftStatus.DRIFT_DETECTED, DriftStatus.UNKNOWN)


class TestDeterministicReplay:
    def test_same_inputs_produce_identical_drift_result(self) -> None:
        config = make_config(min_drift_sample_count=5)
        baseline = [1.0, 2.0, 3.0, 4.0, 5.0]
        current = [2.0, 3.0, 4.0, 5.0, 6.0]

        r1 = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        r2 = detect_mean_shift(
            baseline, current, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            config=config, as_of_time=utc(2024, 1, 2), drift_id="D1",
        )
        assert r1 == r2
