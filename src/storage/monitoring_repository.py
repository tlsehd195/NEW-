"""DuckDB persistent implementations of Phase 14's four Monitoring
repository Protocols.

See docs/specifications/PHASE-14-monitoring.md section 13 and
ADR-0020. Four new tables in Phase 4's existing catalog file -- the same
pattern ADR-0010 through ADR-0019 already applied to every other Phase
5-13 dataset.

`monitoring_events`/`alerts` trust the caller-assigned `event_id`/
`alert_id` as the record's true identity and dedupe on it directly (the
same pattern `ai_requests`/`broker_requests` already use, Phase 12/13) --
two events/alerts with identical content are still two distinct
observations, not duplicates of one another. `component_health_states`/
`drift_results` are append-only (seq-ordered), the same
`provider_quota_states`/`model_status_transitions` pattern (Phase
11/12): idempotent only on the record's own `health_id`/`drift_id`,
never deduped by content.
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    alert_to_payload,
    component_health_to_payload,
    drift_result_to_payload,
    json_dumps,
    json_loads,
    monitoring_event_to_payload,
    payload_to_alert,
    payload_to_component_health,
    payload_to_drift_result,
    payload_to_monitoring_event,
    to_utc_naive,
)

from monitoring.enums import MonitoringComponent
from monitoring.models import Alert, ComponentHealth, DriftResult, MonitoringEvent


class DuckDBMonitoringEventRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, event: MonitoringEvent) -> MonitoringEvent:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM monitoring_events WHERE event_id = ?", [event.event_id]
        ).fetchone()
        if existing is not None:
            return payload_to_monitoring_event(json_loads(existing[0]))

        payload = monitoring_event_to_payload(event)
        conn.execute(
            "INSERT INTO monitoring_events (event_id, component, event_type, severity, observed_at, "
            "as_of_time, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                event.event_id, event.component.value, event.event_type, event.severity.value,
                to_utc_naive(event.observed_at), to_utc_naive(event.as_of_time), json_dumps(payload),
            ],
        )
        return event

    def get(self, event_id: str) -> Optional[MonitoringEvent]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM monitoring_events WHERE event_id = ?", [event_id]
        ).fetchone()
        return payload_to_monitoring_event(json_loads(row[0])) if row is not None else None

    def list_all(self, *, component: Optional[MonitoringComponent] = None) -> list[MonitoringEvent]:
        if component is not None:
            cur = self._engine.connection.execute(
                "SELECT payload_json FROM monitoring_events WHERE component = ? ORDER BY observed_at",
                [component.value],
            )
        else:
            cur = self._engine.connection.execute(
                "SELECT payload_json FROM monitoring_events ORDER BY observed_at"
            )
        return [payload_to_monitoring_event(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBComponentHealthRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, health: ComponentHealth) -> ComponentHealth:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM component_health_states WHERE health_id = ?", [health.health_id]
        ).fetchone()
        if existing is not None:
            return payload_to_component_health(json_loads(existing[0]))

        payload = component_health_to_payload(health)
        conn.execute(
            "INSERT INTO component_health_states (health_id, component, status, as_of_time, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            [health.health_id, health.component.value, health.status.value, to_utc_naive(health.as_of_time), json_dumps(payload)],
        )
        return health

    def get_history(self, component: MonitoringComponent) -> tuple[ComponentHealth, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM component_health_states WHERE component = ? ORDER BY seq",
            [component.value],
        )
        return tuple(payload_to_component_health(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, component: MonitoringComponent) -> Optional[ComponentHealth]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM component_health_states WHERE component = ? ORDER BY seq DESC LIMIT 1",
            [component.value],
        ).fetchone()
        return payload_to_component_health(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[ComponentHealth]:
        cur = self._engine.connection.execute("SELECT payload_json FROM component_health_states ORDER BY seq")
        return [payload_to_component_health(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBDriftResultRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, drift: DriftResult) -> DriftResult:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM drift_results WHERE drift_id = ?", [drift.drift_id]
        ).fetchone()
        if existing is not None:
            return payload_to_drift_result(json_loads(existing[0]))

        payload = drift_result_to_payload(drift)
        conn.execute(
            "INSERT INTO drift_results (drift_id, component, metric_name, status, as_of_time, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                drift.drift_id, drift.component.value, drift.metric_name, drift.status.value,
                to_utc_naive(drift.as_of_time), json_dumps(payload),
            ],
        )
        return drift

    def get_history(self, component: MonitoringComponent, metric_name: str) -> tuple[DriftResult, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM drift_results WHERE component = ? AND metric_name = ? ORDER BY seq",
            [component.value, metric_name],
        )
        return tuple(payload_to_drift_result(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, component: MonitoringComponent, metric_name: str) -> Optional[DriftResult]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM drift_results WHERE component = ? AND metric_name = ? "
            "ORDER BY seq DESC LIMIT 1",
            [component.value, metric_name],
        ).fetchone()
        return payload_to_drift_result(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[DriftResult]:
        cur = self._engine.connection.execute("SELECT payload_json FROM drift_results ORDER BY seq")
        return [payload_to_drift_result(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBAlertRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, alert: Alert) -> Alert:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM alerts WHERE alert_id = ?", [alert.alert_id]
        ).fetchone()
        if existing is not None:
            return payload_to_alert(json_loads(existing[0]))

        payload = alert_to_payload(alert)
        conn.execute(
            "INSERT INTO alerts (alert_id, severity, component, raised_at, payload_json) VALUES (?, ?, ?, ?, ?)",
            [alert.alert_id, alert.severity.value, alert.component.value, to_utc_naive(alert.raised_at), json_dumps(payload)],
        )
        return alert

    def get(self, alert_id: str) -> Optional[Alert]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM alerts WHERE alert_id = ?", [alert_id]
        ).fetchone()
        return payload_to_alert(json_loads(row[0])) if row is not None else None

    def list_all(self, *, severity: Optional[str] = None) -> list[Alert]:
        if severity is not None:
            cur = self._engine.connection.execute(
                "SELECT payload_json FROM alerts WHERE severity = ? ORDER BY raised_at", [severity]
            )
        else:
            cur = self._engine.connection.execute("SELECT payload_json FROM alerts ORDER BY raised_at")
        return [payload_to_alert(json_loads(r[0])) for r in cur.fetchall()]
