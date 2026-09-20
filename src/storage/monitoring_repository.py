"""DuckDBMonitoringEventRepository / DuckDBComponentHealthRepository /
DuckDBDriftResultRepository / DuckDBAlertRepository: persistent
implementations of Phase 14's four Monitoring repository Protocols
(`monitoring.repository`).

These four classes have existed since Phase 14 -- the real gap the
independent audit found (Step 10, P2) was never their absence, but that
a repo-wide grep turned up zero production callers of any of them
outside their own test file: every real `collectors.py`/`pipeline.py`
computation this project ever ran was exercised by a test and then
discarded, never actually persisted by anything resembling a real
caller. `scripts/run_monitoring_sweep.py` is that first real caller --
installing the "lab instrument" the independent audit found had never
been connected to the "factory floor."

While tracing that gap, `get_latest`/`get_history`/`list_all` on
`DuckDBComponentHealthRepository`/`DuckDBDriftResultRepository` were
found to order by insertion `seq` alone, not by the record's own
`as_of_time` -- correct only when every record happens to be inserted
in chronological order. A sweep that processes several days in one run,
or a future backfill, can insert out of order, so `get_latest` could
silently return a stale record. Fixed to order by `as_of_time, seq`.
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
        if row is None:
            return None
        return payload_to_monitoring_event(json_loads(row[0]))

    def list_all(self, *, component: Optional[MonitoringComponent] = None) -> list[MonitoringEvent]:
        sql = "SELECT payload_json FROM monitoring_events WHERE 1=1"
        params: list = []
        if component is not None:
            sql += " AND component = ?"
            params.append(component.value)
        sql += " ORDER BY observed_at"
        cur = self._engine.connection.execute(sql, params)
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
            "SELECT payload_json FROM component_health_states WHERE component = ? ORDER BY as_of_time, seq",
            [component.value],
        )
        return tuple(payload_to_component_health(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, component: MonitoringComponent) -> Optional[ComponentHealth]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM component_health_states WHERE component = ? "
            "ORDER BY as_of_time DESC, seq DESC LIMIT 1",
            [component.value],
        ).fetchone()
        if row is None:
            return None
        return payload_to_component_health(json_loads(row[0]))

    def list_all(self) -> list[ComponentHealth]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM component_health_states ORDER BY as_of_time, seq"
        )
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
            "SELECT payload_json FROM drift_results WHERE component = ? AND metric_name = ? "
            "ORDER BY as_of_time, seq",
            [component.value, metric_name],
        )
        return tuple(payload_to_drift_result(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, component: MonitoringComponent, metric_name: str) -> Optional[DriftResult]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM drift_results WHERE component = ? AND metric_name = ? "
            "ORDER BY as_of_time DESC, seq DESC LIMIT 1",
            [component.value, metric_name],
        ).fetchone()
        if row is None:
            return None
        return payload_to_drift_result(json_loads(row[0]))

    def list_all(self) -> list[DriftResult]:
        cur = self._engine.connection.execute("SELECT payload_json FROM drift_results ORDER BY as_of_time, seq")
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
        if row is None:
            return None
        return payload_to_alert(json_loads(row[0]))

    def list_all(self, *, severity: Optional[str] = None) -> list[Alert]:
        sql = "SELECT payload_json FROM alerts WHERE 1=1"
        params: list = []
        if severity is not None:
            sql += " AND severity = ?"
            params.append(severity)
        sql += " ORDER BY raised_at"
        cur = self._engine.connection.execute(sql, params)
        return [payload_to_alert(json_loads(r[0])) for r in cur.fetchall()]
