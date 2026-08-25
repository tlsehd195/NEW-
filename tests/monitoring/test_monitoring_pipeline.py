"""Category: Integration Test (in-package) -- `pipeline.py` ties every
component's `(MonitoringEvent, ComponentHealth)` pair into one
end-to-end pipeline health, and raises alerts consistently with
`alerts.py`'s own rules."""

from __future__ import annotations

from monitoring_helpers import make_bar, make_broker_response, make_config, utc

from monitoring.collectors import collect_broker, collect_data_quality
from monitoring.enums import ComponentHealthStatus
from monitoring.pipeline import assemble_pipeline_observation


def _alert_id_factory():
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"ALERT-{counter['n']:06d}"

    return factory


class TestAssemblePipelineObservation:
    def test_all_healthy_components_produce_healthy_pipeline_and_no_alerts(self) -> None:
        config = make_config(min_sample_count=1)
        as_of = utc(2024, 1, 2)
        bars = [make_bar(available_time=as_of)]
        responses = [make_broker_response(status="PENDING")]

        dq_event, dq_health = collect_data_quality(bars, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")
        br_event, br_health = collect_broker(responses, as_of_time=as_of, observed_at=as_of, config=config, event_id="E2", health_id="H2")

        observation = assemble_pipeline_observation(
            [(dq_event, dq_health), (br_event, br_health)], as_of_time=as_of, observed_at=as_of, config=config,
            pipeline_health_id="P1", alert_id_factory=_alert_id_factory(),
        )
        assert observation.pipeline_health.status == ComponentHealthStatus.HEALTHY
        assert observation.alerts == ()

    def test_one_unavailable_component_raises_a_critical_alert(self) -> None:
        config = make_config(min_sample_count=1, unavailable_failure_rate_threshold=0.5)
        as_of = utc(2024, 1, 2)
        responses = [make_broker_response(response_id=f"B{i}", status="ERROR") for i in range(3)]

        br_event, br_health = collect_broker(responses, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")

        observation = assemble_pipeline_observation(
            [(br_event, br_health)], as_of_time=as_of, observed_at=as_of, config=config,
            pipeline_health_id="P1", alert_id_factory=_alert_id_factory(),
        )
        assert observation.pipeline_health.status == ComponentHealthStatus.UNAVAILABLE
        from monitoring.enums import AlertSeverity

        assert any(a.severity == AlertSeverity.CRITICAL for a in observation.alerts)

    def test_alert_ids_are_unique_and_caller_assigned(self) -> None:
        config = make_config(min_sample_count=1, unavailable_failure_rate_threshold=0.5)
        as_of = utc(2024, 1, 2)
        responses = [make_broker_response(response_id=f"B{i}", status="ERROR") for i in range(3)]

        br_event, br_health = collect_broker(responses, as_of_time=as_of, observed_at=as_of, config=config, event_id="E1", health_id="H1")

        observation = assemble_pipeline_observation(
            [(br_event, br_health)], as_of_time=as_of, observed_at=as_of, config=config,
            pipeline_health_id="P1", alert_id_factory=_alert_id_factory(),
        )
        alert_ids = [a.alert_id for a in observation.alerts]
        assert len(alert_ids) == len(set(alert_ids))
        assert all(aid.startswith("ALERT-") for aid in alert_ids)
