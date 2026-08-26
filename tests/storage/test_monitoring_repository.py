"""Category: Persistence Test -- save, reload, idempotency, restart for
Phase 14's four Monitoring stores (docs/specifications/
PHASE-14-monitoring.md section 13)."""

from __future__ import annotations

from monitoring_helpers import utc
from storage_helpers import new_engine

from monitoring.enums import AlertSeverity, ComponentHealthStatus, DriftStatus, MonitoringComponent
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent

from storage.monitoring_repository import (
    DuckDBAlertRepository,
    DuckDBComponentHealthRepository,
    DuckDBDriftResultRepository,
    DuckDBMonitoringEventRepository,
)


def _event(event_id: str = "MONEVT-000001") -> MonitoringEvent:
    return MonitoringEvent(
        event_id=event_id, component=MonitoringComponent.DATA, event_type="data_quality_observation",
        severity=AlertSeverity.INFO, observed_at=utc(2024, 1, 2), as_of_time=utc(2024, 1, 2),
        metrics={"observation_count": 5.0, "latest_available_time": utc(2024, 1, 2)},
    )


def _health(health_id: str = "HEALTH-000001") -> ComponentHealth:
    return ComponentHealth(
        health_id=health_id, component=MonitoringComponent.RISK, status=ComponentHealthStatus.DEGRADED,
        as_of_time=utc(2024, 1, 2), reason="failure_rate=0.2000", checks={"sample_count_present": True},
    )


def _drift(drift_id: str = "DRIFT-000001") -> DriftResult:
    return DriftResult(
        drift_id=drift_id, component=MonitoringComponent.PREDICTION, metric_name="expected_return",
        status=DriftStatus.DRIFT_DETECTED, statistic=3.5, threshold=2.0, as_of_time=utc(2024, 1, 2),
        baseline_summary={"mean": 0.01, "stdev": 0.02}, current_summary={"mean": 0.1},
        sample_count_baseline=20, sample_count_current=15,
    )


def _alert(alert_id: str = "ALERT-000001") -> Alert:
    return Alert(
        alert_id=alert_id, severity=AlertSeverity.CRITICAL, component=MonitoringComponent.BROKER,
        message="broker unavailable", raised_at=utc(2024, 1, 2),
    )


class TestMonitoringEventPersistence:
    def test_record_and_get_round_trips_including_nested_datetime_metric(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBMonitoringEventRepository(engine)
        event = _event()
        repo.record(event)
        fetched = repo.get(event.event_id)
        assert fetched == event
        assert fetched.metrics["latest_available_time"] == utc(2024, 1, 2)
        engine.close()

    def test_recording_the_same_event_id_twice_is_idempotent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBMonitoringEventRepository(engine)
        event = _event()
        repo.record(event)
        repo.record(event)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_list_all_filters_by_component(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBMonitoringEventRepository(engine)
        repo.record(_event("E1"))
        other = MonitoringEvent(
            event_id="E2", component=MonitoringComponent.BROKER, event_type="broker_observation",
            severity=AlertSeverity.INFO, observed_at=utc(2024, 1, 2), as_of_time=utc(2024, 1, 2),
        )
        repo.record(other)
        assert len(repo.list_all(component=MonitoringComponent.DATA)) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        event = _event()
        DuckDBMonitoringEventRepository(engine).record(event)
        engine.close()

        engine2 = new_engine(tmp_path)
        assert DuckDBMonitoringEventRepository(engine2).get(event.event_id) == event

    def test_account_component_event_from_collect_account_persists_and_survives_restart(self, tmp_path) -> None:
        """Phase 17 Production Safety Review -- proves the new
        MonitoringComponent.ACCOUNT event (monitoring.collectors.
        collect_account) round-trips through this same generic,
        unmodified repository, not just an in-memory assertion. No
        schema change was needed: `component` is a plain TEXT column
        with no CHECK constraint restricting its values."""
        from monitoring.collectors import collect_account
        from monitoring.config import MonitoringConfig

        engine = new_engine(tmp_path)
        repo = DuckDBMonitoringEventRepository(engine)
        health_repo = DuckDBComponentHealthRepository(engine)

        event, health = collect_account(
            [(utc(2024, 1, 2), 1_000_000.0), (utc(2024, 1, 3), 950_000.0)], initial_cash=1_000_000.0,
            as_of_time=utc(2024, 1, 3), observed_at=utc(2024, 1, 3), config=MonitoringConfig(min_sample_count=1),
            event_id="ACCEVT-PERSIST-1", health_id="ACCHEALTH-PERSIST-1", max_drawdown=0.20,
        )
        repo.record(event)
        health_repo.record(health)
        engine.close()

        engine2 = new_engine(tmp_path)
        reloaded_event = DuckDBMonitoringEventRepository(engine2).get(event.event_id)
        assert reloaded_event.component == MonitoringComponent.ACCOUNT
        assert reloaded_event.metrics["pnl"] == -50_000.0
        reloaded_health = DuckDBComponentHealthRepository(engine2).get_latest(MonitoringComponent.ACCOUNT)
        assert reloaded_health.component == MonitoringComponent.ACCOUNT
        assert reloaded_health.status == ComponentHealthStatus.HEALTHY  # 5% drawdown, under the 20% max
        engine2.close()
        engine2.close()


class TestComponentHealthPersistence:
    def test_append_only_history_and_latest(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBComponentHealthRepository(engine)
        h1 = ComponentHealth(health_id="H1", component=MonitoringComponent.RISK, status=ComponentHealthStatus.HEALTHY, as_of_time=utc(2024, 1, 1), reason="ok")
        h2 = ComponentHealth(health_id="H2", component=MonitoringComponent.RISK, status=ComponentHealthStatus.DEGRADED, as_of_time=utc(2024, 1, 2), reason="degraded")
        repo.record(h1)
        repo.record(h2)
        assert len(repo.get_history(MonitoringComponent.RISK)) == 2
        assert repo.get_latest(MonitoringComponent.RISK) == h2
        engine.close()

    def test_idempotent_on_health_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBComponentHealthRepository(engine)
        health = _health()
        repo.record(health)
        repo.record(health)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        health = _health()
        DuckDBComponentHealthRepository(engine).record(health)
        engine.close()

        engine2 = new_engine(tmp_path)
        assert DuckDBComponentHealthRepository(engine2).get_latest(MonitoringComponent.RISK) == health
        engine2.close()


class TestDriftResultPersistence:
    def test_append_only_history_scoped_by_metric_name(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDriftResultRepository(engine)
        d1 = _drift("D1")
        d2 = DriftResult(drift_id="D2", component=MonitoringComponent.PREDICTION, metric_name="confidence", status=DriftStatus.NO_DRIFT, statistic=0.1, threshold=2.0, as_of_time=utc(2024, 1, 2))
        repo.record(d1)
        repo.record(d2)
        assert len(repo.get_history(MonitoringComponent.PREDICTION, "expected_return")) == 1
        assert repo.get_latest(MonitoringComponent.PREDICTION, "expected_return") == d1
        engine.close()

    def test_idempotent_on_drift_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBDriftResultRepository(engine)
        drift = _drift()
        repo.record(drift)
        repo.record(drift)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        drift = _drift()
        DuckDBDriftResultRepository(engine).record(drift)
        engine.close()

        engine2 = new_engine(tmp_path)
        assert DuckDBDriftResultRepository(engine2).get_latest(MonitoringComponent.PREDICTION, "expected_return") == drift
        engine2.close()


class TestAlertPersistence:
    def test_record_and_get(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAlertRepository(engine)
        alert = _alert()
        repo.record(alert)
        assert repo.get(alert.alert_id) == alert
        engine.close()

    def test_idempotent_on_alert_id(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAlertRepository(engine)
        alert = _alert()
        repo.record(alert)
        repo.record(alert)
        assert len(repo.list_all()) == 1
        engine.close()

    def test_list_all_filters_by_severity(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBAlertRepository(engine)
        repo.record(_alert("A1"))
        repo.record(Alert(alert_id="A2", severity=AlertSeverity.WARNING, component=MonitoringComponent.RISK, message="m", raised_at=utc(2024, 1, 2)))
        assert len(repo.list_all(severity="CRITICAL")) == 1
        engine.close()

    def test_survives_restart(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        alert = _alert()
        DuckDBAlertRepository(engine).record(alert)
        engine.close()

        engine2 = new_engine(tmp_path)
        assert DuckDBAlertRepository(engine2).get(alert.alert_id) == alert
        engine2.close()
