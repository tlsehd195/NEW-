"""Category: Persistence Test (in-memory) -- idempotency, append-only
history, and latest/history lookups for the four InMemory Monitoring
repositories."""

from __future__ import annotations

from monitoring_helpers import utc

from monitoring.enums import AlertSeverity, ComponentHealthStatus, DriftStatus, MonitoringComponent
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent
from monitoring.repository import (
    InMemoryAlertRepository,
    InMemoryComponentHealthRepository,
    InMemoryDriftResultRepository,
    InMemoryMonitoringEventRepository,
)


class TestMonitoringEventRepository:
    def test_record_is_idempotent_on_event_id(self) -> None:
        repo = InMemoryMonitoringEventRepository()
        event = MonitoringEvent(
            event_id="E1", component=MonitoringComponent.DATA, event_type="data_quality_observation",
            severity=AlertSeverity.INFO, observed_at=utc(2024, 1, 2), as_of_time=utc(2024, 1, 2),
        )
        repo.record(event)
        repo.record(event)
        assert len(repo.list_all()) == 1

    def test_list_all_filters_by_component(self) -> None:
        repo = InMemoryMonitoringEventRepository()
        repo.record(MonitoringEvent(event_id="E1", component=MonitoringComponent.DATA, event_type="t", severity=AlertSeverity.INFO, observed_at=utc(2024, 1, 2), as_of_time=utc(2024, 1, 2)))
        repo.record(MonitoringEvent(event_id="E2", component=MonitoringComponent.BROKER, event_type="t", severity=AlertSeverity.INFO, observed_at=utc(2024, 1, 2), as_of_time=utc(2024, 1, 2)))
        assert len(repo.list_all(component=MonitoringComponent.DATA)) == 1


class TestComponentHealthRepository:
    def test_append_only_history_and_latest(self) -> None:
        repo = InMemoryComponentHealthRepository()
        h1 = ComponentHealth(health_id="H1", component=MonitoringComponent.RISK, status=ComponentHealthStatus.HEALTHY, as_of_time=utc(2024, 1, 1), reason="ok")
        h2 = ComponentHealth(health_id="H2", component=MonitoringComponent.RISK, status=ComponentHealthStatus.DEGRADED, as_of_time=utc(2024, 1, 2), reason="degraded")
        repo.record(h1)
        repo.record(h2)
        assert len(repo.get_history(MonitoringComponent.RISK)) == 2
        assert repo.get_latest(MonitoringComponent.RISK) == h2

    def test_idempotent_on_health_id(self) -> None:
        repo = InMemoryComponentHealthRepository()
        h1 = ComponentHealth(health_id="H1", component=MonitoringComponent.RISK, status=ComponentHealthStatus.HEALTHY, as_of_time=utc(2024, 1, 1), reason="ok")
        repo.record(h1)
        repo.record(h1)
        assert len(repo.get_history(MonitoringComponent.RISK)) == 1

    def test_get_latest_none_when_empty(self) -> None:
        repo = InMemoryComponentHealthRepository()
        assert repo.get_latest(MonitoringComponent.RISK) is None


class TestDriftResultRepository:
    def test_append_only_history_and_latest_scoped_by_metric_name(self) -> None:
        repo = InMemoryDriftResultRepository()
        d1 = DriftResult(drift_id="D1", component=MonitoringComponent.PREDICTION, metric_name="expected_return", status=DriftStatus.NO_DRIFT, statistic=0.1, threshold=2.0, as_of_time=utc(2024, 1, 1))
        d2 = DriftResult(drift_id="D2", component=MonitoringComponent.PREDICTION, metric_name="expected_return", status=DriftStatus.DRIFT_DETECTED, statistic=3.0, threshold=2.0, as_of_time=utc(2024, 1, 2))
        d3 = DriftResult(drift_id="D3", component=MonitoringComponent.PREDICTION, metric_name="confidence", status=DriftStatus.NO_DRIFT, statistic=0.1, threshold=2.0, as_of_time=utc(2024, 1, 2))
        repo.record(d1)
        repo.record(d2)
        repo.record(d3)
        assert len(repo.get_history(MonitoringComponent.PREDICTION, "expected_return")) == 2
        assert repo.get_latest(MonitoringComponent.PREDICTION, "expected_return") == d2
        assert len(repo.get_history(MonitoringComponent.PREDICTION, "confidence")) == 1


class TestAlertRepository:
    def test_idempotent_on_alert_id(self) -> None:
        repo = InMemoryAlertRepository()
        alert = Alert(alert_id="A1", severity=AlertSeverity.WARNING, component=MonitoringComponent.RISK, message="m", raised_at=utc(2024, 1, 2))
        repo.record(alert)
        repo.record(alert)
        assert len(repo.list_all()) == 1

    def test_list_all_filters_by_severity(self) -> None:
        repo = InMemoryAlertRepository()
        repo.record(Alert(alert_id="A1", severity=AlertSeverity.WARNING, component=MonitoringComponent.RISK, message="m1", raised_at=utc(2024, 1, 2)))
        repo.record(Alert(alert_id="A2", severity=AlertSeverity.CRITICAL, component=MonitoringComponent.RISK, message="m2", raised_at=utc(2024, 1, 2)))
        assert len(repo.list_all(severity="WARNING")) == 1
