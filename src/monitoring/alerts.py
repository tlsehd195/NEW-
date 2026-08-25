"""raise_alert_from_event: PROJECT_MASTER_PLAN.md section 12.5 --
"Critical event 발생 시 기록 및 알림 가능한 구조를 만든다." A pure,
deterministic mapping from an already-computed `MonitoringEvent`/
`ComponentHealth`/`DriftResult` to an `Alert` -- never a side-effecting
notification call (email/messenger providers are explicitly deferred,
matching the master plan's own "초기에는 logging 중심으로 구현" phrasing).
An `Alert`, once raised, is never mutated or cancelled by anything in
this package.

See docs/specifications/PHASE-14-monitoring.md section 9.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from monitoring.enums import AlertSeverity, ComponentHealthStatus, DriftStatus, MonitoringComponent
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent

from trade_journal.enums import TradeProvenance

_ALERT_WORTHY_SEVERITIES = frozenset({AlertSeverity.WARNING, AlertSeverity.CRITICAL, AlertSeverity.UNKNOWN})

_HEALTH_STATUS_TO_SEVERITY = {
    ComponentHealthStatus.HEALTHY: AlertSeverity.INFO,
    ComponentHealthStatus.DEGRADED: AlertSeverity.WARNING,
    ComponentHealthStatus.UNAVAILABLE: AlertSeverity.CRITICAL,
    ComponentHealthStatus.UNKNOWN: AlertSeverity.UNKNOWN,
}


def severity_for_health_status(status: ComponentHealthStatus) -> AlertSeverity:
    return _HEALTH_STATUS_TO_SEVERITY[status]


def raise_alert_from_event(
    event: MonitoringEvent, *, alert_id: str, raised_at: datetime,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
) -> Optional[Alert]:
    """`None` when `event.severity == INFO` -- an alert-worthy event is
    `WARNING`/`CRITICAL`/`UNKNOWN` only; a routine `INFO` observation is
    never escalated into an alert."""
    if event.severity not in _ALERT_WORTHY_SEVERITIES:
        return None
    return Alert(
        alert_id=alert_id, severity=event.severity, component=event.component,
        message=event.message or f"{event.event_type} raised {event.severity.value}",
        raised_at=raised_at, event_id=event.event_id, provenance=provenance, experiment_id=event.experiment_id,
    )


def raise_alert_from_health(
    health: ComponentHealth, *, alert_id: str, raised_at: datetime,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
) -> Optional[Alert]:
    severity = severity_for_health_status(health.status)
    if severity not in _ALERT_WORTHY_SEVERITIES:
        return None
    return Alert(
        alert_id=alert_id, severity=severity, component=health.component,
        message=f"component health {health.status.value}: {health.reason}",
        raised_at=raised_at, event_id=health.event_id, provenance=provenance,
    )


def raise_alert_from_drift(
    drift: DriftResult, *, alert_id: str, raised_at: datetime,
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION,
) -> Optional[Alert]:
    """`DriftStatus.NO_DRIFT` never raises an alert. `DRIFT_DETECTED`
    raises `WARNING` (an observation to review, not a `CRITICAL`
    automatic-action trigger -- PROJECT_MASTER_PLAN.md section 11.6).
    `UNKNOWN` raises `UNKNOWN` severity, itself worth surfacing."""
    if drift.status == DriftStatus.NO_DRIFT:
        return None
    severity = AlertSeverity.WARNING if drift.status == DriftStatus.DRIFT_DETECTED else AlertSeverity.UNKNOWN
    return Alert(
        alert_id=alert_id, severity=severity, component=drift.component,
        message=f"drift {drift.status.value} on {drift.metric_name}: {drift.reason}",
        raised_at=raised_at, event_id=None, provenance=provenance,
    )
