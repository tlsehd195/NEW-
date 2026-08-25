"""DuckDB persistent implementations of Phase 12's three AI Gateway
repository Protocols.

See docs/specifications/PHASE-12-ai-gateway.md section 10 and ADR-0018.
Three new tables in Phase 4's existing catalog file -- the same pattern
ADR-0010 through ADR-0017 already applied to every other Phase 5-11
dataset.

`ai_requests`/`ai_responses` trust the caller-assigned `request_id`/
`response_id` as the record's true identity and dedupe on it directly
(the same pattern Phase 5-8's `decisions`/`predictions`/
`regime_observations` tables already use) -- unlike a content-addressed
artifact (a `TrainingDataset`, a `CandidateModelArtifact`), a request/
response log has no meaningful content-based natural key: two requests
with identical payloads are two distinct events, not duplicates of one
another, so there is nothing to dedupe *by content*. `provider_quota_states`
is append-only (seq-ordered), the same `regime_observations`/
`attribution_results`/`model_status_transitions` pattern.
"""

from __future__ import annotations

from typing import Optional

from storage.engine import StorageEngine
from storage.serialization import (
    ai_request_to_payload,
    ai_response_to_payload,
    json_dumps,
    json_loads,
    payload_to_ai_request,
    payload_to_ai_response,
    payload_to_provider_quota_state,
    provider_quota_state_to_payload,
    to_utc_naive,
)

from ai_gateway.models import AIRequest, AIResponse, ProviderQuotaState


class DuckDBAIRequestRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, request: AIRequest) -> AIRequest:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM ai_requests WHERE request_id = ?", [request.request_id]
        ).fetchone()
        if existing is not None:
            return payload_to_ai_request(json_loads(existing[0]))

        payload = ai_request_to_payload(request)
        conn.execute(
            "INSERT INTO ai_requests (request_id, task_tier, prompt_template_id, prompt_template_version, "
            "requested_at, provenance, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                request.request_id, request.task_tier.value, request.prompt_template_id,
                request.prompt_template_version, to_utc_naive(request.requested_at),
                request.provenance.value, json_dumps(payload),
            ],
        )
        return request

    def get(self, request_id: str) -> Optional[AIRequest]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM ai_requests WHERE request_id = ?", [request_id]
        ).fetchone()
        return payload_to_ai_request(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[AIRequest]:
        cur = self._engine.connection.execute("SELECT payload_json FROM ai_requests ORDER BY requested_at")
        return [payload_to_ai_request(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBAIResponseRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, response: AIResponse) -> AIResponse:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM ai_responses WHERE response_id = ?", [response.response_id]
        ).fetchone()
        if existing is not None:
            return payload_to_ai_response(json_loads(existing[0]))

        payload = ai_response_to_payload(response)
        conn.execute(
            "INSERT INTO ai_responses (response_id, request_id, status, provider_id, responded_at, "
            "provenance, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                response.response_id, response.request_id, response.status.value, response.provider_id,
                to_utc_naive(response.responded_at), response.provenance.value, json_dumps(payload),
            ],
        )
        return response

    def get(self, response_id: str) -> Optional[AIResponse]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM ai_responses WHERE response_id = ?", [response_id]
        ).fetchone()
        return payload_to_ai_response(json_loads(row[0])) if row is not None else None

    def get_by_request(self, request_id: str) -> Optional[AIResponse]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM ai_responses WHERE request_id = ? ORDER BY responded_at DESC LIMIT 1",
            [request_id],
        ).fetchone()
        return payload_to_ai_response(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[AIResponse]:
        cur = self._engine.connection.execute("SELECT payload_json FROM ai_responses ORDER BY responded_at")
        return [payload_to_ai_response(json_loads(r[0])) for r in cur.fetchall()]


class DuckDBQuotaStateRepository:
    def __init__(self, engine: StorageEngine) -> None:
        self._engine = engine

    def record(self, state: ProviderQuotaState) -> ProviderQuotaState:
        conn = self._engine.connection
        existing = conn.execute(
            "SELECT payload_json FROM provider_quota_states WHERE state_id = ?", [state.state_id]
        ).fetchone()
        if existing is not None:
            return payload_to_provider_quota_state(json_loads(existing[0]))

        payload = provider_quota_state_to_payload(state)
        conn.execute(
            "INSERT INTO provider_quota_states (state_id, provider_id, observed_at, health_status, "
            "billing_status, enabled, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                state.state_id, state.provider_id, to_utc_naive(state.observed_at),
                state.health_status.value, state.billing_status.value, state.enabled, json_dumps(payload),
            ],
        )
        return state

    def get_history(self, provider_id: str) -> tuple[ProviderQuotaState, ...]:
        cur = self._engine.connection.execute(
            "SELECT payload_json FROM provider_quota_states WHERE provider_id = ? ORDER BY seq",
            [provider_id],
        )
        return tuple(payload_to_provider_quota_state(json_loads(r[0])) for r in cur.fetchall())

    def get_latest(self, provider_id: str) -> Optional[ProviderQuotaState]:
        row = self._engine.connection.execute(
            "SELECT payload_json FROM provider_quota_states WHERE provider_id = ? ORDER BY seq DESC LIMIT 1",
            [provider_id],
        ).fetchone()
        return payload_to_provider_quota_state(json_loads(row[0])) if row is not None else None

    def list_all(self) -> list[ProviderQuotaState]:
        cur = self._engine.connection.execute("SELECT payload_json FROM provider_quota_states ORDER BY seq")
        return [payload_to_provider_quota_state(json_loads(r[0])) for r in cur.fetchall()]
