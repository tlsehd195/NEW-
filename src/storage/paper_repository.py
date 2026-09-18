"""DuckDB persistent implementations of Phase 15's two genuinely new
Paper Trading repository Protocols. Order status history reuses
`storage.broker_repository.DuckDBOrderStatusEventRepository`/
`order_status_events` unchanged (Phase 13) -- see
`broker.paper.repository`'s module docstring for why.

See docs/specifications/PHASE-15-paper-trading.md section 13 and
ADR-0021.

`paper_orders` trusts the caller-assigned `client_order_id` and dedupes
on it directly (the same `ai_requests`/`broker_requests` pattern).
`paper_fills` is append-only (seq-ordered), the same
`provider_quota_states`/`model_status_transitions` pattern.
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    json_dumps,
    json_loads,
    paper_applied_corporate_action_record_to_payload,
    paper_fill_record_to_payload,
    paper_order_record_to_payload,
    payload_to_paper_applied_corporate_action_record,
    payload_to_paper_fill_record,
    payload_to_paper_order_record,
    to_utc_naive,
)

from broker.paper.models import PaperAppliedCorporateActionRecord, PaperFillRecord, PaperOrderRecord


class DuckDBPaperOrderRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, order: PaperOrderRecord) -> PaperOrderRecord:
        conn = self._engine.connection
        client_order_id = order.validated_order.client_order_id
        existing = conn.execute(
            "SELECT payload_json FROM paper_orders WHERE client_order_id = ?", [client_order_id]
        ).fetchone()
        if existing is not None:
            return payload_to_paper_order_record(json_loads(existing[0]))

        payload = paper_order_record_to_payload(order)
        conn.execute(
            "INSERT INTO paper_orders (client_order_id, security_id, side, quantity, initial_status, "
            "requested_at, decision_id, sizing_id, risk_assessment_id, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                client_order_id, order.validated_order.security_id, order.validated_order.side.value,
                order.validated_order.quantity, order.initial_status.value, to_utc_naive(order.requested_at),
                order.validated_order.decision_id, order.validated_order.sizing_id,
                order.validated_order.risk_assessment_id, json_dumps(payload),
            ],
        )
        return order

    def get(self, client_order_id: str) -> Optional[PaperOrderRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM paper_orders WHERE client_order_id = ?", [client_order_id]
        ).fetchone()
        return payload_to_paper_order_record(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[PaperOrderRecord]:
        cur = self._engine.connection.execute("SELECT payload_json FROM paper_orders ORDER BY requested_at")
        return [payload_to_paper_order_record(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBPaperFillRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, fill: PaperFillRecord) -> PaperFillRecord:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM paper_fills WHERE fill_id = ?", [fill.fill_id]
        ).fetchone()
        if existing is not None:
            return payload_to_paper_fill_record(json_loads(existing[0]))

        payload = paper_fill_record_to_payload(fill)
        conn.execute(
            "INSERT INTO paper_fills (fill_id, client_order_id, security_id, side, quantity, price, "
            "recorded_at, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                fill.fill_id, fill.client_order_id, fill.fill.security_id, fill.fill.side.value,
                fill.fill.quantity, fill.fill.price, to_utc_naive(fill.recorded_at), json_dumps(payload),
            ],
        )
        return fill

    def get_history(self, client_order_id: str) -> tuple[PaperFillRecord, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM paper_fills WHERE client_order_id = ? ORDER BY seq", [client_order_id]
        )
        return tuple(payload_to_paper_fill_record(json_loads(r[0])) for r in cur.fetchall())

    def list_all(self) -> list[PaperFillRecord]:
        cur = self._engine.connection.execute("SELECT payload_json FROM paper_fills ORDER BY seq")
        return [payload_to_paper_fill_record(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBPaperCorporateActionRepository:
    """Persisted, cross-restart idempotency ledger for `broker.paper.
    adapter.PaperBrokerAdapter.apply_corporate_actions` -- see ADR-0155.
    `record()` dedupes on `source_record_id` (the primary key), never
    twice, mirroring `paper_orders`' own idempotent-on-natural-key
    pattern rather than `paper_fills`' append-only one."""

    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, record: PaperAppliedCorporateActionRecord) -> PaperAppliedCorporateActionRecord:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM paper_applied_corporate_actions WHERE source_record_id = ?",
            [record.source_record_id],
        ).fetchone()
        if existing is not None:
            return payload_to_paper_applied_corporate_action_record(json_loads(existing[0]))

        payload = paper_applied_corporate_action_record_to_payload(record)
        conn.execute(
            "INSERT INTO paper_applied_corporate_actions "
            "(source_record_id, security_id, action_type, applied_at, payload_json) VALUES (?, ?, ?, ?, ?)",
            [
                record.source_record_id, record.action.security_id, record.action.action_type.value,
                to_utc_naive(record.applied_at), json_dumps(payload),
            ],
        )
        return record

    def get(self, source_record_id: str) -> Optional[PaperAppliedCorporateActionRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM paper_applied_corporate_actions WHERE source_record_id = ?",
            [source_record_id],
        ).fetchone()
        return payload_to_paper_applied_corporate_action_record(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[PaperAppliedCorporateActionRecord]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM paper_applied_corporate_actions ORDER BY applied_at"
        )
        return [payload_to_paper_applied_corporate_action_record(json_loads(r[0])) for r in cur.fetchall()]
