"""PaperTradingSession: the orchestration layer that wraps a
`PaperBrokerAdapter` call with persistence (mirrors
`broker.pipeline.submit_validated_order`'s "call the adapter, persist
what happened" separation, Phase 13) and can rebuild an adapter's full
in-memory state from repositories after a restart (instruction section
17, 27).

The adapter itself never persists anything -- `PaperTradingSession` is
the only place `broker.paper.*` writes to a repository, so restart
safety lives here rather than inside the deterministic simulation core.

See docs/specifications/PHASE-15-paper-trading.md section 9, 14.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from broker.models import BrokerOrderResponse, OrderStatusObservation, ValidatedOrder
from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.config import PaperTradingConfig
from broker.paper.market_data import PaperMarketDataSource
from broker.paper.models import PaperFillRecord, PaperOrderRecord
from broker.paper.repository import InMemoryPaperFillRepository, InMemoryPaperOrderRepository, PaperFillRepository, PaperOrderRepository
from broker.repository import InMemoryOrderStatusEventRepository, OrderStatusEventRepository


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value


@dataclass(frozen=True)
class AccountSummary:
    """A plain, read-only snapshot for callers (Trade Journal bridging,
    ad hoc Monitoring observation) that do not need the full adapter --
    never persisted itself, always re-derived on demand from the
    adapter's own `get_account`/`get_positions`."""

    as_of_time: datetime
    cash: float
    positions: dict  # security_id -> BrokerPosition


class PaperTradingSession:
    def __init__(
        self,
        config: PaperTradingConfig,
        market_data_source: PaperMarketDataSource,
        *,
        order_repository: Optional[PaperOrderRepository] = None,
        fill_repository: Optional[PaperFillRepository] = None,
        status_repository: Optional[OrderStatusEventRepository] = None,
    ) -> None:
        self.config = config
        self.adapter = PaperBrokerAdapter(config, market_data_source)
        self._order_repository = order_repository or InMemoryPaperOrderRepository()
        self._fill_repository = fill_repository or InMemoryPaperFillRepository()
        self._status_repository = status_repository or InMemoryOrderStatusEventRepository()
        self._fill_record_ids = _IdAllocator("PAPERFILLREC")

    def _persist_new_fills(self, *, recorded_at: datetime) -> tuple[PaperFillRecord, ...]:
        persisted = []
        for client_order_id, fill_id, fill in self.adapter.pop_new_fills():
            record = PaperFillRecord(
                fill_id=fill_id, client_order_id=client_order_id, fill=fill,
                configuration_version=self.config.configuration_version(), recorded_at=recorded_at,
            )
            self._fill_repository.record(record)
            persisted.append(record)
        return tuple(persisted)

    def capture(self, client_order_id: str, *, as_of: datetime) -> tuple[PaperFillRecord, ...]:
        """Persists whatever `broker.paper.*`-specific state the adapter
        currently holds for `client_order_id` -- the order record (if
        new), its latest status, and any fills generated since the last
        `capture()`/`submit()`/`advance()` call. Exists separately from
        `submit()` so a caller that drives the adapter through
        `broker.pipeline.submit_validated_order` directly (to also get
        the generic `broker_requests`/`broker_responses` audit trail,
        Phase 13) can still sync Paper's own richer state afterward,
        without this session re-submitting the order itself."""
        order_record = self.adapter.get_order_record(client_order_id)
        if order_record is not None:
            self._order_repository.record(order_record)

        status = self.adapter.get_order_status(client_order_id, as_of=as_of)
        self._status_repository.record(status)

        return self._persist_new_fills(recorded_at=as_of)

    def submit(self, order: ValidatedOrder, *, requested_at: datetime) -> tuple[BrokerOrderResponse, tuple[PaperFillRecord, ...]]:
        response = self.adapter.submit_order(order, requested_at=requested_at)
        fills = self.capture(order.client_order_id, as_of=requested_at)
        return response, fills

    def advance(self, as_of: datetime) -> tuple[tuple[OrderStatusObservation, ...], tuple[PaperFillRecord, ...]]:
        updates = self.adapter.advance_simulation(as_of)
        for observation in updates:
            self._status_repository.record(observation)
        fills = self._persist_new_fills(recorded_at=as_of)
        return updates, fills

    def cancel(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse:
        response = self.adapter.cancel_order(client_order_id, requested_at=requested_at)
        self.capture(client_order_id, as_of=requested_at)
        return response

    def account_summary(self, *, as_of: datetime) -> AccountSummary:
        account = self.adapter.get_account(as_of=as_of)
        positions = {p.security_id: p for p in self.adapter.get_positions(as_of=as_of)}
        return AccountSummary(as_of_time=as_of, cash=account.cash if account.cash is not None else 0.0, positions=positions)

    @classmethod
    def restore(
        cls,
        config: PaperTradingConfig,
        market_data_source: PaperMarketDataSource,
        *,
        order_repository: PaperOrderRepository,
        fill_repository: PaperFillRepository,
        status_repository: OrderStatusEventRepository,
        as_of: datetime,
    ) -> "PaperTradingSession":
        """Rebuilds a fresh `PaperBrokerAdapter`'s entire in-memory state
        by replaying every persisted order (chronological by
        `requested_at`) and then every persisted fill (chronological,
        `list_all()`'s own ordering) -- never re-running failure_mode or
        cash-check logic, only reproducing what already happened
        (instruction section 17, 27)."""
        session = cls(
            config, market_data_source, order_repository=order_repository,
            fill_repository=fill_repository, status_repository=status_repository,
        )
        for order_record in order_repository.list_all():
            session.adapter.restore_order(order_record)
        for fill_record in fill_repository.list_all():
            session.adapter.restore_fill(fill_record.fill_id, fill_record.client_order_id, fill_record.fill)

        cancelled_ids = {
            obs.client_order_id for obs in status_repository.list_all()
            if obs.broker_id == config.broker_id and obs.status.value == "CANCELED"
        }
        for client_order_id in cancelled_ids:
            session.adapter.restore_cancellation(client_order_id)

        session.adapter.rebuild_status_history(as_of)
        return session
