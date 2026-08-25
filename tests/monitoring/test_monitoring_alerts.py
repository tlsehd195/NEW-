"""Category: Alerting Test -- INFO never raises an alert; WARNING/
CRITICAL/UNKNOWN do. Pure, deterministic mapping only -- no
side-effecting notification call."""

from __future__ import annotations

from monitoring_helpers import utc

from monitoring.alerts import raise_alert_from_drift, raise_alert_from_event, raise_alert_from_health, severity_for_health_status
from monitoring.enums import AlertSeverity, ComponentHealthStatus, DriftStatus, MonitoringComponent
from monitoring.models import ComponentHealth, DriftResult, MonitoringEvent


def _event(severity: AlertSeverity) -> MonitoringEvent:
    return MonitoringEvent(
        event_id="MONEVT-1", component=MonitoringComponent.BROKER, event_type="broker_observation",
        severity=severity, observed_at=utc(2024, 1, 2), as_of_time=utc(2024, 1, 2),
    )


class TestSeverityForHealthStatus:
    def test_mapping_is_exhaustive_and_correct(self) -> None:
        assert severity_for_health_status(ComponentHealthStatus.HEALTHY) == AlertSeverity.INFO
        assert severity_for_health_status(ComponentHealthStatus.DEGRADED) == AlertSeverity.WARNING
        assert severity_for_health_status(ComponentHealthStatus.UNAVAILABLE) == AlertSeverity.CRITICAL
        assert severity_for_health_status(ComponentHealthStatus.UNKNOWN) == AlertSeverity.UNKNOWN


class TestRaiseAlertFromEvent:
    def test_info_never_raises(self) -> None:
        assert raise_alert_from_event(_event(AlertSeverity.INFO), alert_id="A1", raised_at=utc(2024, 1, 2)) is None

    def test_warning_raises(self) -> None:
        alert = raise_alert_from_event(_event(AlertSeverity.WARNING), alert_id="A1", raised_at=utc(2024, 1, 2))
        assert alert is not None
        assert alert.severity == AlertSeverity.WARNING

    def test_critical_raises(self) -> None:
        alert = raise_alert_from_event(_event(AlertSeverity.CRITICAL), alert_id="A1", raised_at=utc(2024, 1, 2))
        assert alert is not None
        assert alert.severity == AlertSeverity.CRITICAL

    def test_unknown_raises_unknown_severity(self) -> None:
        alert = raise_alert_from_event(_event(AlertSeverity.UNKNOWN), alert_id="A1", raised_at=utc(2024, 1, 2))
        assert alert is not None
        assert alert.severity == AlertSeverity.UNKNOWN


class TestRaiseAlertFromHealth:
    def test_healthy_never_raises(self) -> None:
        health = ComponentHealth(
            health_id="H1", component=MonitoringComponent.RISK, status=ComponentHealthStatus.HEALTHY,
            as_of_time=utc(2024, 1, 2), reason="ok",
        )
        assert raise_alert_from_health(health, alert_id="A1", raised_at=utc(2024, 1, 2)) is None

    def test_unavailable_raises_critical(self) -> None:
        health = ComponentHealth(
            health_id="H1", component=MonitoringComponent.RISK, status=ComponentHealthStatus.UNAVAILABLE,
            as_of_time=utc(2024, 1, 2), reason="down",
        )
        alert = raise_alert_from_health(health, alert_id="A1", raised_at=utc(2024, 1, 2))
        assert alert is not None
        assert alert.severity == AlertSeverity.CRITICAL


class TestRaiseAlertFromDrift:
    def test_no_drift_never_raises(self) -> None:
        drift = DriftResult(
            drift_id="D1", component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            status=DriftStatus.NO_DRIFT, statistic=0.1, threshold=2.0, as_of_time=utc(2024, 1, 2),
        )
        assert raise_alert_from_drift(drift, alert_id="A1", raised_at=utc(2024, 1, 2)) is None

    def test_drift_detected_raises_warning_not_critical(self) -> None:
        """A drift observation triggers re-validation, never an
        automatic action -- so it is WARNING, not CRITICAL
        (PROJECT_MASTER_PLAN.md section 11.6)."""
        drift = DriftResult(
            drift_id="D1", component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            status=DriftStatus.DRIFT_DETECTED, statistic=5.0, threshold=2.0, as_of_time=utc(2024, 1, 2),
        )
        alert = raise_alert_from_drift(drift, alert_id="A1", raised_at=utc(2024, 1, 2))
        assert alert is not None
        assert alert.severity == AlertSeverity.WARNING

    def test_unknown_drift_raises_unknown_severity(self) -> None:
        drift = DriftResult(
            drift_id="D1", component=MonitoringComponent.PREDICTION, metric_name="expected_return",
            status=DriftStatus.UNKNOWN, statistic=None, threshold=None, as_of_time=utc(2024, 1, 2),
        )
        alert = raise_alert_from_drift(drift, alert_id="A1", raised_at=utc(2024, 1, 2))
        assert alert is not None
        assert alert.severity == AlertSeverity.UNKNOWN
