"""Category: Health Test -- healthy/degraded/unavailable/unknown/
missing-dependency verdicts from `health.py`'s deterministic evaluators.
`UNKNOWN` is never silently coerced to `HEALTHY`."""

from __future__ import annotations

from monitoring_helpers import make_config, utc

from monitoring.enums import ComponentHealthStatus, MonitoringComponent
from monitoring.health import (
    evaluate_data_health,
    evaluate_existence_health,
    evaluate_health_from_failure_rate,
    evaluate_pipeline_health,
)
from monitoring.models import ComponentHealth


class TestFailureRateHealth:
    def test_healthy_below_degraded_threshold(self) -> None:
        config = make_config()
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.01, sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

    def test_degraded_between_thresholds(self) -> None:
        config = make_config()
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.2, sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.DEGRADED

    def test_unavailable_above_unavailable_threshold(self) -> None:
        config = make_config()
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.9, sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE

    def test_unknown_when_sample_count_missing(self) -> None:
        config = make_config()
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.01, sample_count=None, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN
        assert health.checks["sample_count_present"] is False

    def test_unknown_when_sample_count_insufficient(self) -> None:
        config = make_config(min_sample_count=5)
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=0.01, sample_count=2, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN

    def test_unknown_when_failure_rate_non_finite(self) -> None:
        config = make_config()
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=None, sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN

    def test_unknown_never_coerced_to_healthy(self) -> None:
        config = make_config()
        health = evaluate_health_from_failure_rate(
            MonitoringComponent.BROKER, failure_rate=float("nan"), sample_count=10, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status != ComponentHealthStatus.HEALTHY
        assert health.status == ComponentHealthStatus.UNKNOWN


class TestExistenceHealth:
    def test_healthy_when_count_meets_minimum(self) -> None:
        config = make_config(degraded_min_expected_count=1)
        health = evaluate_existence_health(
            MonitoringComponent.DECISION, count=5.0, config=config, as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

    def test_unavailable_when_count_zero(self) -> None:
        config = make_config()
        health = evaluate_existence_health(
            MonitoringComponent.DECISION, count=0.0, config=config, as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE

    def test_unknown_when_count_is_none(self) -> None:
        config = make_config()
        health = evaluate_existence_health(
            MonitoringComponent.DECISION, count=None, config=config, as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN

    def test_hold_and_no_trade_decisions_do_not_degrade_health(self) -> None:
        """NO_TRADE/HOLD are legitimate Decision outputs -- existence
        health only checks that the layer *produced* output, never what
        it produced."""
        config = make_config(degraded_min_expected_count=1)
        health = evaluate_existence_health(
            MonitoringComponent.DECISION, count=3.0, config=config, as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY


class TestDataHealth:
    def test_healthy_within_thresholds(self) -> None:
        config = make_config()
        health = evaluate_data_health(
            invalid_rate=0.0, stale_seconds=10.0, observation_count=10.0, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.HEALTHY

    def test_unavailable_above_invalid_rate_threshold(self) -> None:
        config = make_config()
        health = evaluate_data_health(
            invalid_rate=0.9, stale_seconds=10.0, observation_count=10.0, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNAVAILABLE

    def test_degraded_when_stale(self) -> None:
        config = make_config(stale_data_max_age_seconds=100.0)
        health = evaluate_data_health(
            invalid_rate=0.0, stale_seconds=1_000.0, observation_count=10.0, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.DEGRADED

    def test_unknown_when_observation_count_insufficient(self) -> None:
        config = make_config(min_sample_count=5)
        health = evaluate_data_health(
            invalid_rate=0.0, stale_seconds=10.0, observation_count=1.0, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN

    def test_unknown_when_observation_count_none(self) -> None:
        config = make_config()
        health = evaluate_data_health(
            invalid_rate=0.0, stale_seconds=10.0, observation_count=None, config=config,
            as_of_time=utc(2024, 1, 2), health_id="H1",
        )
        assert health.status == ComponentHealthStatus.UNKNOWN


class TestPipelineHealth:
    def test_worst_of_aggregation(self) -> None:
        config = make_config()
        healths = [
            ComponentHealth(health_id="H1", component=MonitoringComponent.DATA, status=ComponentHealthStatus.HEALTHY, as_of_time=utc(2024, 1, 2), reason="ok"),
            ComponentHealth(health_id="H2", component=MonitoringComponent.RISK, status=ComponentHealthStatus.DEGRADED, as_of_time=utc(2024, 1, 2), reason="degraded"),
            ComponentHealth(health_id="H3", component=MonitoringComponent.BROKER, status=ComponentHealthStatus.UNAVAILABLE, as_of_time=utc(2024, 1, 2), reason="down"),
        ]
        pipeline = evaluate_pipeline_health(healths, as_of_time=utc(2024, 1, 2), health_id="P1", config=config)
        assert pipeline.status == ComponentHealthStatus.UNAVAILABLE

    def test_unavailable_outranks_unknown_outranks_degraded(self) -> None:
        config = make_config()
        healths = [
            ComponentHealth(health_id="H1", component=MonitoringComponent.DATA, status=ComponentHealthStatus.DEGRADED, as_of_time=utc(2024, 1, 2), reason="degraded"),
            ComponentHealth(health_id="H2", component=MonitoringComponent.RISK, status=ComponentHealthStatus.UNKNOWN, as_of_time=utc(2024, 1, 2), reason="unknown"),
        ]
        pipeline = evaluate_pipeline_health(healths, as_of_time=utc(2024, 1, 2), health_id="P1", config=config)
        assert pipeline.status == ComponentHealthStatus.UNKNOWN

    def test_empty_input_is_unknown_not_healthy(self) -> None:
        config = make_config()
        pipeline = evaluate_pipeline_health([], as_of_time=utc(2024, 1, 2), health_id="P1", config=config)
        assert pipeline.status == ComponentHealthStatus.UNKNOWN
        assert pipeline.reason == "no_components_observed"

    def test_all_healthy_is_healthy(self) -> None:
        config = make_config()
        healths = [
            ComponentHealth(health_id="H1", component=MonitoringComponent.DATA, status=ComponentHealthStatus.HEALTHY, as_of_time=utc(2024, 1, 2), reason="ok"),
        ]
        pipeline = evaluate_pipeline_health(healths, as_of_time=utc(2024, 1, 2), health_id="P1", config=config)
        assert pipeline.status == ComponentHealthStatus.HEALTHY
