"""DuckDB persistent implementations of Phase 16's two genuinely new
Live Trading repository Protocols. Order status history and request/
response audit reuse Phase 13's `order_status_events`/`broker_requests`/
`broker_responses` tables unchanged -- see `broker.live.session`'s
module docstring and docs/specifications/PHASE-16-live-trading.md
section 12 for why Live needs no local order/fill ledger the way Phase
15's Paper Trading did (the real broker, not this repository, is always
authoritative for Live).

See docs/decisions/ADR-0022-live-trading.md.

`kill_switch_events`/`reconciliation_events` are both append-only
(seq-ordered), the same `provider_quota_states`/`model_status_transitions`
pattern every prior phase already uses for "one observation per point in
time" history.
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    json_dumps,
    json_loads,
    kill_switch_event_to_payload,
    payload_to_kill_switch_event,
    payload_to_reconciliation_result,
    reconciliation_result_to_payload,
    to_utc_naive,
)

from broker.live.kill_switch import KillSwitchEvent
from broker.live.reconciliation import ReconciliationResult


class DuckDBKillSwitchRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, event: KillSwitchEvent) -> KillSwitchEvent:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM kill_switch_events WHERE event_id = ?", [event.event_id]
        ).fetchone()
        if existing is not None:
            return payload_to_kill_switch_event(json_loads(existing[0]))

        payload = kill_switch_event_to_payload(event)
        conn.execute(
            "INSERT INTO kill_switch_events (event_id, engaged, reason, triggered_by, occurred_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [event.event_id, event.engaged, event.reason, event.triggered_by, to_utc_naive(event.occurred_at), json_dumps(payload)],
        )
        return event

    def get_latest(self) -> Optional[KillSwitchEvent]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM kill_switch_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return payload_to_kill_switch_event(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[KillSwitchEvent]:
        cur = self._engine.connection.execute("SELECT payload_json FROM kill_switch_events ORDER BY seq")
        return [payload_to_kill_switch_event(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBReconciliationRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, result: ReconciliationResult) -> ReconciliationResult:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM reconciliation_events WHERE reconciliation_id = ?", [result.reconciliation_id]
        ).fetchone()
        if existing is not None:
            return payload_to_reconciliation_result(json_loads(existing[0]))

        payload = reconciliation_result_to_payload(result)
        conn.execute(
            "INSERT INTO reconciliation_events (reconciliation_id, target, subject_id, status, as_of_time, "
            "payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                result.reconciliation_id, result.target, result.subject_id, result.status.value,
                to_utc_naive(result.as_of_time), json_dumps(payload),
            ],
        )
        return result

    def get_latest(self, target: str, subject_id: str) -> Optional[ReconciliationResult]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM reconciliation_events WHERE target = ? AND subject_id = ? "
            "ORDER BY seq DESC LIMIT 1",
            [target, subject_id],
        ).fetchone()
        return payload_to_reconciliation_result(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[ReconciliationResult]:
        cur = self._engine.connection.execute("SELECT payload_json FROM reconciliation_events ORDER BY seq")
        return [payload_to_reconciliation_result(json_loads(r[0])) for r in cur.fetchall()]
