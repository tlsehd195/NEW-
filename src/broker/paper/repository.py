"""Repository Protocols + InMemory reference implementations for Paper
Trading's two genuinely new persisted types -- `PaperOrderRecord`/
`PaperFillRecord`. Order status history is *not* duplicated here: it
reuses `broker.repository.OrderStatusEventRepository`/`order_status_events`
(Phase 13) unchanged, since `OrderStatusObservation` already fits (it
carries `broker_id`, and a Paper order's `client_order_id` is globally
unique).

See docs/specifications/PHASE-15-paper-trading.md section 13.
"""

from __future__ import annotations

from typing import Optional, Protocol

from broker.paper.models import PaperFillRecord, PaperOrderRecord


class PaperOrderRepository(Protocol):
    def record(self, order: PaperOrderRecord) -> PaperOrderRecord:
        """Idempotent on `order.validated_order.client_order_id`."""
        ...

    def get(self, client_order_id: str) -> Optional[PaperOrderRecord]: ...
    def list_all(self) -> list[PaperOrderRecord]: ...


class InMemoryPaperOrderRepository:
    def __init__(self) -> None:
        self._orders: dict[str, PaperOrderRecord] = {}

    def record(self, order: PaperOrderRecord) -> PaperOrderRecord:
        client_order_id = order.validated_order.client_order_id
        existing = self._orders.get(client_order_id)
        if existing is not None:
            return existing
        self._orders[client_order_id] = order
        return order

    def get(self, client_order_id: str) -> Optional[PaperOrderRecord]:
        return self._orders.get(client_order_id)

    def list_all(self) -> list[PaperOrderRecord]:
        return sorted(self._orders.values(), key=lambda o: o.requested_at)


class PaperFillRepository(Protocol):
    def record(self, fill: PaperFillRecord) -> PaperFillRecord:
        """Append-only -- idempotent only on `fill_id` itself."""
        ...

    def get_history(self, client_order_id: str) -> tuple[PaperFillRecord, ...]: ...
    def list_all(self) -> list[PaperFillRecord]: ...


class InMemoryPaperFillRepository:
    def __init__(self) -> None:
        self._fills: list[PaperFillRecord] = []
        self._by_id: dict[str, PaperFillRecord] = {}

    def record(self, fill: PaperFillRecord) -> PaperFillRecord:
        existing = self._by_id.get(fill.fill_id)
        if existing is not None:
            return existing
        self._fills.append(fill)
        self._by_id[fill.fill_id] = fill
        return fill

    def get_history(self, client_order_id: str) -> tuple[PaperFillRecord, ...]:
        return tuple(f for f in self._fills if f.client_order_id == client_order_id)

    def list_all(self) -> list[PaperFillRecord]:
        return sorted(self._fills, key=lambda f: f.recorded_at)
