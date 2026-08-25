"""Repository Protocols + InMemory reference implementations for
Monitoring's four persisted types, mirroring the Repository Protocol
discipline every prior phase already established.

See docs/specifications/PHASE-14-monitoring.md section 13.
"""

from __future__ import annotations

from typing import Optional, Protocol

from monitoring.enums import MonitoringComponent
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent


class MonitoringEventRepository(Protocol):
    def record(self, event: MonitoringEvent) -> MonitoringEvent:
        """Idempotent on `event_id`."""
        ...

    def get(self, event_id: str) -> Optional[MonitoringEvent]: ...
    def list_all(self, *, component: Optional[MonitoringComponent] = None) -> list[MonitoringEvent]: ...


class InMemoryMonitoringEventRepository:
    def __init__(self) -> None:
        self._events: dict[str, MonitoringEvent] = {}

    def record(self, event: MonitoringEvent) -> MonitoringEvent:
        existing = self._events.get(event.event_id)
        if existing is not None:
            return existing
        self._events[event.event_id] = event
        return event

    def get(self, event_id: str) -> Optional[MonitoringEvent]:
        return self._events.get(event_id)

    def list_all(self, *, component: Optional[MonitoringComponent] = None) -> list[MonitoringEvent]:
        results = list(self._events.values())
        if component is not None:
            results = [e for e in results if e.component == component]
        return sorted(results, key=lambda e: e.observed_at)


class ComponentHealthRepository(Protocol):
    def record(self, health: ComponentHealth) -> ComponentHealth:
        """Append-only -- idempotent only on `health_id` itself."""
        ...

    def get_latest(self, component: MonitoringComponent) -> Optional[ComponentHealth]: ...
    def get_history(self, component: MonitoringComponent) -> tuple[ComponentHealth, ...]: ...
    def list_all(self) -> list[ComponentHealth]: ...


class InMemoryComponentHealthRepository:
    def __init__(self) -> None:
        self._history: list[ComponentHealth] = []
        self._by_id: dict[str, ComponentHealth] = {}

    def record(self, health: ComponentHealth) -> ComponentHealth:
        existing = self._by_id.get(health.health_id)
        if existing is not None:
            return existing
        self._history.append(health)
        self._by_id[health.health_id] = health
        return health

    def get_history(self, component: MonitoringComponent) -> tuple[ComponentHealth, ...]:
        return tuple(h for h in self._history if h.component == component)

    def get_latest(self, component: MonitoringComponent) -> Optional[ComponentHealth]:
        history = self.get_history(component)
        if not history:
            return None
        return max(history, key=lambda h: (h.as_of_time, h.health_id))

    def list_all(self) -> list[ComponentHealth]:
        return sorted(self._history, key=lambda h: (h.as_of_time, h.health_id))


class DriftResultRepository(Protocol):
    def record(self, drift: DriftResult) -> DriftResult:
        """Append-only -- idempotent only on `drift_id` itself."""
        ...

    def get_latest(self, component: MonitoringComponent, metric_name: str) -> Optional[DriftResult]: ...
    def get_history(self, component: MonitoringComponent, metric_name: str) -> tuple[DriftResult, ...]: ...
    def list_all(self) -> list[DriftResult]: ...


class InMemoryDriftResultRepository:
    def __init__(self) -> None:
        self._results: list[DriftResult] = []
        self._by_id: dict[str, DriftResult] = {}

    def record(self, drift: DriftResult) -> DriftResult:
        existing = self._by_id.get(drift.drift_id)
        if existing is not None:
            return existing
        self._results.append(drift)
        self._by_id[drift.drift_id] = drift
        return drift

    def get_history(self, component: MonitoringComponent, metric_name: str) -> tuple[DriftResult, ...]:
        return tuple(d for d in self._results if d.component == component and d.metric_name == metric_name)

    def get_latest(self, component: MonitoringComponent, metric_name: str) -> Optional[DriftResult]:
        history = self.get_history(component, metric_name)
        if not history:
            return None
        return max(history, key=lambda d: (d.as_of_time, d.drift_id))

    def list_all(self) -> list[DriftResult]:
        return sorted(self._results, key=lambda d: (d.as_of_time, d.drift_id))


class AlertRepository(Protocol):
    def record(self, alert: Alert) -> Alert:
        """Append-only -- idempotent on `alert_id`."""
        ...

    def get(self, alert_id: str) -> Optional[Alert]: ...
    def list_all(self, *, severity: Optional[str] = None) -> list[Alert]: ...


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self._alerts: dict[str, Alert] = {}

    def record(self, alert: Alert) -> Alert:
        existing = self._alerts.get(alert.alert_id)
        if existing is not None:
            return existing
        self._alerts[alert.alert_id] = alert
        return alert

    def get(self, alert_id: str) -> Optional[Alert]:
        return self._alerts.get(alert_id)

    def list_all(self, *, severity: Optional[str] = None) -> list[Alert]:
        results = list(self._alerts.values())
        if severity is not None:
            results = [a for a in results if a.severity.value == severity]
        return sorted(results, key=lambda a: a.raised_at)
