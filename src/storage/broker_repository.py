"""DuckDB persistent implementations of Phase 13's three Broker Adapter
repository Protocols.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 15
and ADR-0019. Three new tables in Phase 4's existing catalog file --
the same pattern ADR-0010 through ADR-0018 already applied to every
other Phase 5-12 dataset. `broker_requests`/`broker_responses` trust the
caller-assigned id and dedupe on it directly (the same Phase 5-8/12
`decisions`/`predictions`/`ai_requests` pattern -- a request/response
log has no meaningful content-based natural key). `order_status_events`
is append-only (seq-ordered), the same `regime_observations`/
`provider_quota_states` pattern.

Nothing in `payload`/`metadata` ever contains a resolved secret --
nothing that constructs a `BrokerRequestRecord`/`BrokerResponseRecord`
anywhere in `broker.*` has access to one in the first place
(`broker.toss.auth` resolves credentials only for the HTTP call itself
and never returns them).
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    broker_request_to_payload,
    broker_response_to_payload,
    json_dumps,
    json_loads,
    order_status_observation_to_payload,
    payload_to_broker_request,
    payload_to_broker_response,
    payload_to_order_status_observation,
    to_utc_naive,
)

from broker.models import BrokerRequestRecord, BrokerResponseRecord, OrderStatusObservation


class DuckDBBrokerRequestRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, request: BrokerRequestRecord) -> BrokerRequestRecord:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM broker_requests WHERE request_id = ?", [request.request_id]
        ).fetchone()
        if existing is not None:
            return payload_to_broker_request(json_loads(existing[0]))

        payload = broker_request_to_payload(request)
        conn.execute(
            "INSERT INTO broker_requests (request_id, broker_id, operation, execution_mode, "
            "client_order_id, decision_id, sizing_id, risk_assessment_id, requested_at, provenance, "
            "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                request.request_id, request.broker_id, request.operation, request.execution_mode,
                request.client_order_id, request.decision_id, request.sizing_id, request.risk_assessment_id,
                to_utc_naive(request.requested_at), request.provenance.value, json_dumps(payload),
            ],
        )
        return request

    def get(self, request_id: str) -> Optional[BrokerRequestRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM broker_requests WHERE request_id = ?", [request_id]
        ).fetchone()
        return payload_to_broker_request(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[BrokerRequestRecord]:
        cur = self._engine.connection.execute("SELECT payload_json FROM broker_requests ORDER BY requested_at")
        return [payload_to_broker_request(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBBrokerResponseRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, response: BrokerResponseRecord) -> BrokerResponseRecord:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM broker_responses WHERE response_id = ?", [response.response_id]
        ).fetchone()
        if existing is not None:
            return payload_to_broker_response(json_loads(existing[0]))

        payload = broker_response_to_payload(response)
        conn.execute(
            "INSERT INTO broker_responses (response_id, request_id, broker_id, operation, status, "
            "broker_order_id, responded_at, provenance, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                response.response_id, response.request_id, response.broker_id, response.operation,
                response.status, response.broker_order_id, to_utc_naive(response.responded_at),
                response.provenance.value, json_dumps(payload),
            ],
        )
        return response

    def get(self, response_id: str) -> Optional[BrokerResponseRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM broker_responses WHERE response_id = ?", [response_id]
        ).fetchone()
        return payload_to_broker_response(json_loads(row[0])) if row is not None else None

    def get_by_request(self, request_id: str) -> Optional[BrokerResponseRecord]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM broker_responses WHERE request_id = ? ORDER BY responded_at DESC LIMIT 1",
            [request_id],
        ).fetchone()
        return payload_to_broker_response(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[BrokerResponseRecord]:
        cur = self._engine.connection.execute("SELECT payload_json FROM broker_responses ORDER BY responded_at")
        return [payload_to_broker_response(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBOrderStatusEventRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, observation: OrderStatusObservation) -> OrderStatusObservation:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM order_status_events WHERE observation_id = ?", [observation.observation_id]
        ).fetchone()
        if existing is not None:
            return payload_to_order_status_observation(json_loads(existing[0]))

        payload = order_status_observation_to_payload(observation)
        conn.execute(
            "INSERT INTO order_status_events (observation_id, client_order_id, broker_id, status, "
            "observed_at, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            [
                observation.observation_id, observation.client_order_id, observation.broker_id,
                observation.status.value, to_utc_naive(observation.observed_at), json_dumps(payload),
            ],
        )
        return observation

    def get_history(self, client_order_id: str) -> tuple[OrderStatusObservation, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM order_status_events WHERE client_order_id = ? ORDER BY seq",
            [client_order_id],
        )
        return tuple(payload_to_order_status_observation(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, client_order_id: str) -> Optional[OrderStatusObservation]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM order_status_events WHERE client_order_id = ? ORDER BY seq DESC LIMIT 1",
            [client_order_id],
        ).fetchone()
        return payload_to_order_status_observation(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[OrderStatusObservation]:
        cur = self._engine.connection.execute("SELECT payload_json FROM order_status_events ORDER BY seq")
        return [payload_to_order_status_observation(json_loads(r[0])) for r in cur.fetchall()]
