"""Repository Protocols + InMemory reference implementations for the
Broker Adapter's three persisted types, mirroring the Repository
Protocol discipline every prior phase already established.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 15.
"""

from __future__ import annotations

from typing import Optional, Protocol

from broker.models import BrokerRequestRecord, BrokerResponseRecord, OrderStatusObservation


class BrokerRequestRepository(Protocol):
    def record(self, request: BrokerRequestRecord) -> BrokerRequestRecord:
        """Idempotent on `request_id`."""
        ...

    def get(self, request_id: str) -> Optional[BrokerRequestRecord]: ...
    def list_all(self) -> list[BrokerRequestRecord]: ...


class InMemoryBrokerRequestRepository:
    def __init__(self) -> None:
        self._requests: dict[str, BrokerRequestRecord] = {}

    def record(self, request: BrokerRequestRecord) -> BrokerRequestRecord:
        existing = self._requests.get(request.request_id)
        if existing is not None:
            return existing
        self._requests[request.request_id] = request
        return request

    def get(self, request_id: str) -> Optional[BrokerRequestRecord]:
        return self._requests.get(request_id)

    def list_all(self) -> list[BrokerRequestRecord]:
        return sorted(self._requests.values(), key=lambda r: r.requested_at)


class BrokerResponseRepository(Protocol):
    def record(self, response: BrokerResponseRecord) -> BrokerResponseRecord:
        """Idempotent on `response_id`."""
        ...

    def get(self, response_id: str) -> Optional[BrokerResponseRecord]: ...
    def get_by_request(self, request_id: str) -> Optional[BrokerResponseRecord]: ...
    def list_all(self) -> list[BrokerResponseRecord]: ...


class InMemoryBrokerResponseRepository:
    def __init__(self) -> None:
        self._responses: dict[str, BrokerResponseRecord] = {}
        self._by_request: dict[str, str] = {}

    def record(self, response: BrokerResponseRecord) -> BrokerResponseRecord:
        existing = self._responses.get(response.response_id)
        if existing is not None:
            return existing
        self._responses[response.response_id] = response
        self._by_request[response.request_id] = response.response_id
        return response

    def get(self, response_id: str) -> Optional[BrokerResponseRecord]:
        return self._responses.get(response_id)

    def get_by_request(self, request_id: str) -> Optional[BrokerResponseRecord]:
        rid = self._by_request.get(request_id)
        return self._responses.get(rid) if rid is not None else None

    def list_all(self) -> list[BrokerResponseRecord]:
        return sorted(self._responses.values(), key=lambda r: r.responded_at)


class OrderStatusEventRepository(Protocol):
    def record(self, observation: OrderStatusObservation) -> OrderStatusObservation:
        """Append-only -- idempotent only on `observation_id` itself."""
        ...

    def get_latest(self, client_order_id: str) -> Optional[OrderStatusObservation]: ...
    def get_history(self, client_order_id: str) -> tuple[OrderStatusObservation, ...]: ...
    def list_all(self) -> list[OrderStatusObservation]: ...


class InMemoryOrderStatusEventRepository:
    def __init__(self) -> None:
        self._events: list[OrderStatusObservation] = []
        self._by_id: dict[str, OrderStatusObservation] = {}

    def record(self, observation: OrderStatusObservation) -> OrderStatusObservation:
        existing = self._by_id.get(observation.observation_id)
        if existing is not None:
            return existing
        self._events.append(observation)
        self._by_id[observation.observation_id] = observation
        return observation

    def get_history(self, client_order_id: str) -> tuple[OrderStatusObservation, ...]:
        return tuple(e for e in self._events if e.client_order_id == client_order_id)

    def get_latest(self, client_order_id: str) -> Optional[OrderStatusObservation]:
        history = self.get_history(client_order_id)
        if not history:
            return None
        return max(history, key=lambda e: (e.observed_at, e.observation_id))

    def list_all(self) -> list[OrderStatusObservation]:
        return sorted(self._events, key=lambda e: (e.observed_at, e.observation_id))
