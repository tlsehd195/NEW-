"""Repository Protocols + InMemory reference implementations for the AI
Gateway's three persisted types, mirroring the Repository Protocol
discipline every prior phase already established.

See docs/specifications/PHASE-12-ai-gateway.md section 10.
"""

from __future__ import annotations

from typing import Optional, Protocol

from ai_gateway.models import AIRequest, AIResponse, ProviderQuotaState


class AIRequestRepository(Protocol):
    def record(self, request: AIRequest) -> AIRequest:
        """Idempotent on `request_id`."""
        ...

    def get(self, request_id: str) -> Optional[AIRequest]: ...
    def list_all(self) -> list[AIRequest]: ...


class InMemoryAIRequestRepository:
    def __init__(self) -> None:
        self._requests: dict[str, AIRequest] = {}

    def record(self, request: AIRequest) -> AIRequest:
        existing = self._requests.get(request.request_id)
        if existing is not None:
            return existing
        self._requests[request.request_id] = request
        return request

    def get(self, request_id: str) -> Optional[AIRequest]:
        return self._requests.get(request_id)

    def list_all(self) -> list[AIRequest]:
        return sorted(self._requests.values(), key=lambda r: r.requested_at)


class AIResponseRepository(Protocol):
    def record(self, response: AIResponse) -> AIResponse:
        """Idempotent on `response_id`."""
        ...

    def get(self, response_id: str) -> Optional[AIResponse]: ...
    def get_by_request(self, request_id: str) -> Optional[AIResponse]: ...
    def list_all(self) -> list[AIResponse]: ...


class InMemoryAIResponseRepository:
    def __init__(self) -> None:
        self._responses: dict[str, AIResponse] = {}
        self._by_request: dict[str, str] = {}

    def record(self, response: AIResponse) -> AIResponse:
        existing = self._responses.get(response.response_id)
        if existing is not None:
            return existing
        self._responses[response.response_id] = response
        self._by_request[response.request_id] = response.response_id
        return response

    def get(self, response_id: str) -> Optional[AIResponse]:
        return self._responses.get(response_id)

    def get_by_request(self, request_id: str) -> Optional[AIResponse]:
        rid = self._by_request.get(request_id)
        return self._responses.get(rid) if rid is not None else None

    def list_all(self) -> list[AIResponse]:
        return sorted(self._responses.values(), key=lambda r: r.responded_at)


class QuotaStateRepository(Protocol):
    def record(self, state: ProviderQuotaState) -> ProviderQuotaState:
        """Append-only -- always inserts a new observation, never
        overwrites a prior one (idempotent only on `state_id` itself, so
        recording the exact same object twice is a no-op)."""
        ...

    def get_latest(self, provider_id: str) -> Optional[ProviderQuotaState]: ...
    def get_history(self, provider_id: str) -> tuple[ProviderQuotaState, ...]: ...
    def list_all(self) -> list[ProviderQuotaState]: ...


class InMemoryQuotaStateRepository:
    def __init__(self) -> None:
        self._states: list[ProviderQuotaState] = []
        self._by_id: dict[str, ProviderQuotaState] = {}

    def record(self, state: ProviderQuotaState) -> ProviderQuotaState:
        existing = self._by_id.get(state.state_id)
        if existing is not None:
            return existing
        self._states.append(state)
        self._by_id[state.state_id] = state
        return state

    def get_history(self, provider_id: str) -> tuple[ProviderQuotaState, ...]:
        return tuple(s for s in self._states if s.provider_id == provider_id)

    def get_latest(self, provider_id: str) -> Optional[ProviderQuotaState]:
        history = self.get_history(provider_id)
        if not history:
            return None
        return max(history, key=lambda s: (s.observed_at, s.state_id))

    def list_all(self) -> list[ProviderQuotaState]:
        return sorted(self._states, key=lambda s: (s.observed_at, s.state_id))
