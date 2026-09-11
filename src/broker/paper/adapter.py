"""PaperBrokerAdapter: a fully simulated, deterministic
`broker.protocol.BrokerAdapter` implementation. Never imports
`broker.toss.*`, never reads `os.environ`/`os.getenv`, never opens a
socket -- every outcome is computed locally from a caller-supplied
`PaperMarketDataSource` and `PaperTradingConfig`
(`tests/broker/paper/test_paper_boundary.py`).

Mirrors `broker.mock.MockBrokerAdapter`'s self-contained, in-memory,
no-repository-dependency design (Phase 13) -- persistence is the
orchestration layer's job (`broker.paper.session.PaperTradingSession`),
not the adapter's, matching how `broker.pipeline.submit_validated_order`
already separates "call the adapter" from "persist what happened."

See docs/specifications/PHASE-15-paper-trading.md section 8, 9.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Optional

from broker.capabilities import build_capabilities
from broker.enums import BrokerCapability, BrokerOrderStatus, CapabilityStatus
from broker.errors import BrokerAuthError, BrokerRateLimitError, BrokerTimeoutError, BrokerTransportError
from broker.models import BrokerAccountSnapshot, BrokerCapabilities, BrokerOrderResponse, BrokerPosition, OrderStatusObservation, ValidatedOrder
from broker.paper.config import PaperTradingConfig
from broker.paper.execution import simulate_fill
from broker.paper.market_data import PaperMarketDataSource
from broker.paper.models import PaperFillRecord, PaperOrderRecord

from backtest.enums import OrderSide
from backtest.fills import Fill
from backtest.portfolio import PortfolioAccounting


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value

    def advance_past(self, existing_id: str) -> None:
        """Used only during rehydration (`restore_fill`) so a freshly
        allocated id after a restart can never collide with one a prior
        process already persisted."""
        suffix = existing_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            self._next_id = max(self._next_id, int(suffix) + 1)


_TRANSPORT_FAILURE_MODES = {
    "unavailable": BrokerTransportError,
    "timeout": BrokerTimeoutError,
    "auth": BrokerAuthError,
    "rate_limit": BrokerRateLimitError,
}


class PaperBrokerAdapter:
    def __init__(self, config: PaperTradingConfig, market_data_source: PaperMarketDataSource) -> None:
        self.broker_id = config.broker_id
        self._config = config
        self._market_data_source = market_data_source
        self._cost_model = config.transaction_cost_model()
        self._slippage_model = config.slippage_model()
        self._accounting = PortfolioAccounting(config.initial_cash)

        self._orders: dict[str, PaperOrderRecord] = {}
        self._fills: dict[str, list[tuple[str, Fill]]] = {}
        self._cancelled: set[str] = set()
        self._status_history: dict[str, list[OrderStatusObservation]] = {}
        self._pending_fill_events: list[tuple[str, str, Fill]] = []

        self._response_ids = _IdAllocator("PAPERRESP")
        self._observation_ids = _IdAllocator("PAPEROSTAT")
        self._fill_ids = _IdAllocator("PAPERFILL")

    @property
    def accounting(self) -> PortfolioAccounting:
        """Phase 18 addition -- read-only access to the same
        `backtest.portfolio.PortfolioAccounting` instance this adapter
        already uses internally (Phase 2, unmodified), so a Performance
        Report can be computed from `value_series`/`closed_trades`/
        `turnover()`/`transaction_costs` directly rather than a second,
        duplicate accounting system. Callers wanting a real equity
        curve for performance metrics must call
        `adapter.accounting.mark_to_market(prices, as_of)` themselves at
        each valuation point -- this adapter never calls it on its own
        (no behavior change for any existing caller)."""
        return self._accounting

    # -- rehydration (restart safety) -- never re-runs failure_mode/
    # cash-check logic, only replays what already happened. --

    def restore_order(self, record: PaperOrderRecord) -> None:
        self._orders[record.validated_order.client_order_id] = record
        self._fills.setdefault(record.validated_order.client_order_id, [])

    def restore_fill(self, fill_id: str, client_order_id: str, fill: Fill) -> None:
        self._accounting.apply_fill(fill)
        self._fills.setdefault(client_order_id, []).append((fill_id, fill))
        self._fill_ids.advance_past(fill_id)

    def restore_cancellation(self, client_order_id: str) -> None:
        self._cancelled.add(client_order_id)

    def restore_observation_id_watermark(self, observation_id: str) -> None:
        """Session 37 (ADR-0115, external review N-6): advances
        `_observation_ids` past an already-persisted `observation_id`
        from a prior process run -- call once per row already in
        `status_repository` before `rebuild_status_history()`, the same
        `advance_past` seeding `restore_fill` already does for
        `_fill_ids`. Without this, a fresh process's first freshly
        generated observation_id always starts back at
        "PAPEROSTAT-000001"; if that collides with one already
        persisted, `storage.broker_repository.
        DuckDBOrderStatusEventRepository.record()`'s natural-key dedup
        on `observation_id` silently returns the STALE prior-run row
        instead of persisting the newly rebuilt one -- so every status
        query after a restart could keep reading pre-restart history
        indefinitely, not the correctly-rebuilt current state."""
        self._observation_ids.advance_past(observation_id)

    def rebuild_status_history(self, as_of: datetime) -> None:
        """Call once after every `restore_order`/`restore_fill`/
        `restore_cancellation` -- rebuilds `get_order_status`'s history
        purely from the now-restored order/fill/cancellation state."""
        for client_order_id in self._orders:
            self._record_status(client_order_id, as_of=as_of)

    @property
    def cash(self) -> float:
        return self._accounting.cash

    def get_order_record(self, client_order_id: str) -> Optional[PaperOrderRecord]:
        return self._orders.get(client_order_id)

    # -- internal helpers --

    def _check_transport_failure(self) -> None:
        mode = self._config.failure_mode
        exc_type = _TRANSPORT_FAILURE_MODES.get(mode)
        if exc_type is not None:
            raise exc_type(f"simulated {mode} for {self.broker_id!r}")

    def _current_status(self, client_order_id: str) -> BrokerOrderStatus:
        if client_order_id in self._cancelled:
            return BrokerOrderStatus.CANCELED
        record = self._orders[client_order_id]
        if record.initial_status == BrokerOrderStatus.REJECTED:
            return BrokerOrderStatus.REJECTED
        total_filled = sum(f.quantity for _, f in self._fills.get(client_order_id, []))
        if total_filled <= 0:
            return BrokerOrderStatus.PENDING
        if total_filled >= record.validated_order.quantity:
            return BrokerOrderStatus.FILLED
        return BrokerOrderStatus.PARTIAL_FILLED

    def _record_status(self, client_order_id: str, *, as_of: datetime) -> OrderStatusObservation:
        status = self._current_status(client_order_id)
        fills = self._fills.get(client_order_id, [])
        total_filled = sum(f.quantity for _, f in fills)
        avg_price = (sum(f.price * f.quantity for _, f in fills) / total_filled) if total_filled > 0 else None
        observation = OrderStatusObservation(
            observation_id=self._observation_ids.allocate(), client_order_id=client_order_id,
            broker_id=self.broker_id,
            broker_order_id=None if status == BrokerOrderStatus.REJECTED else f"PAPERORD-{client_order_id}",
            status=status, filled_quantity=(total_filled if total_filled > 0 else None), avg_fill_price=avg_price,
            observed_at=as_of, raw_status_code=status.value,
        )
        self._status_history.setdefault(client_order_id, []).append(observation)
        return observation

    def _response_for(self, client_order_id: str, at: datetime, *, error_code: Optional[str] = None) -> BrokerOrderResponse:
        record = self._orders[client_order_id]
        order = record.validated_order
        status = self._current_status(client_order_id)
        fills = self._fills.get(client_order_id, [])
        total_filled = sum(f.quantity for _, f in fills)
        avg_price = (sum(f.price * f.quantity for _, f in fills) / total_filled) if total_filled > 0 else None
        return BrokerOrderResponse(
            response_id=self._response_ids.allocate(), request_client_order_id=client_order_id,
            broker_id=self.broker_id, operation="submit_order", status=status,
            broker_order_id=None if status == BrokerOrderStatus.REJECTED else f"PAPERORD-{client_order_id}",
            filled_quantity=(total_filled if total_filled > 0 else None), avg_fill_price=avg_price,
            error_code=error_code or record.rejection_reason,
            error_message=error_code or record.rejection_reason,
            attempt_count=1, latency_ms=0.0, responded_at=at,
            provenance=order.provenance, experiment_id=order.experiment_id,
        )

    def _reject(self, order: ValidatedOrder, requested_at: datetime, reason: str) -> BrokerOrderResponse:
        record = PaperOrderRecord(
            validated_order=order, requested_at=requested_at, initial_status=BrokerOrderStatus.REJECTED,
            rejection_reason=reason, configuration_version=self._config.configuration_version(),
        )
        self._orders[order.client_order_id] = record
        self._fills[order.client_order_id] = []
        self._record_status(order.client_order_id, as_of=requested_at)
        return self._response_for(order.client_order_id, requested_at)

    def _attempt_fill(self, client_order_id: str, *, as_of: datetime) -> None:
        record = self._orders[client_order_id]
        if client_order_id in self._cancelled or record.initial_status == BrokerOrderStatus.REJECTED:
            return
        order = record.validated_order
        already_filled = sum(f.quantity for _, f in self._fills.get(client_order_id, []))
        remaining = order.quantity - already_filled
        if remaining <= 0:
            return

        bar = self._market_data_source.get_reference_bar(order.security_id, as_of=as_of)
        if bar is None:
            return  # no data available yet -- stays PENDING/PARTIAL_FILLED, never guesses a price

        fill = simulate_fill(
            order_id=order.client_order_id, security_id=order.security_id, side=order.side,
            remaining_quantity=remaining, bar=bar, cost_model=self._cost_model, slippage_model=self._slippage_model,
            max_participation=self._config.max_participation, partial_fill_enabled=self._config.partial_fill_enabled,
            decision_time=order.as_of_time, execution_time=as_of,
        )
        if fill is None:
            return

        if order.side == OrderSide.BUY:
            actual_notional = fill.price * fill.quantity
            if actual_notional + fill.commission > self._accounting.cash:
                if already_filled <= 0:
                    self._orders[client_order_id] = replace(
                        record, initial_status=BrokerOrderStatus.REJECTED, rejection_reason="insufficient_cash",
                    )
                    self._record_status(client_order_id, as_of=as_of)
                return  # fail closed either way -- no fill this attempt

        fill_id = self._fill_ids.allocate()
        self._accounting.apply_fill(fill)
        self._fills.setdefault(client_order_id, []).append((fill_id, fill))
        self._pending_fill_events.append((client_order_id, fill_id, fill))
        self._record_status(client_order_id, as_of=as_of)

    def pop_new_fills(self) -> tuple[tuple[str, str, Fill], ...]:
        """Returns and clears every `(client_order_id, fill_id, Fill)`
        generated since the last call -- the one piece of information
        `BrokerOrderResponse`/`OrderStatusObservation` do not carry
        (only an aggregate `filled_quantity`/`avg_fill_price`), so a
        caller wanting the full cost-broken-down fill history reads it
        here rather than the adapter persisting it itself."""
        events = tuple(self._pending_fill_events)
        self._pending_fill_events.clear()
        return events

    # -- BrokerAdapter Protocol --

    def submit_order(self, order: ValidatedOrder, *, requested_at: datetime) -> BrokerOrderResponse:
        existing = self._orders.get(order.client_order_id)
        if existing is not None:
            return self._response_for(order.client_order_id, requested_at)  # idempotent replay

        if self._config.failure_mode == "malformed":
            return BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=order.client_order_id,
                broker_id=self.broker_id, operation="submit_order", status=BrokerOrderStatus.UNKNOWN,
                broker_order_id=None, filled_quantity=None, avg_fill_price=None,
                error_code="malformed_response", error_message="simulated malformed broker response",
                attempt_count=1, latency_ms=0.0, responded_at=requested_at,
                provenance=order.provenance, experiment_id=order.experiment_id,
            )
        self._check_transport_failure()

        if self._config.maximum_order_quantity is not None and order.quantity > self._config.maximum_order_quantity:
            return self._reject(order, requested_at, "maximum_order_quantity_exceeded")

        reference_bar = self._market_data_source.get_reference_bar(order.security_id, as_of=requested_at)
        if self._config.maximum_notional is not None and reference_bar is not None:
            if order.quantity * reference_bar.close > self._config.maximum_notional:
                return self._reject(order, requested_at, "maximum_notional_exceeded")

        if order.side == OrderSide.SELL and not self._config.allow_short:
            current_quantity = self._accounting.snapshot_view(requested_at).quantity_of(order.security_id)
            if order.quantity > current_quantity:
                return self._reject(order, requested_at, "insufficient_position")

        if self._config.failure_mode == "rejected":
            return self._reject(order, requested_at, "simulated_rejection")

        record = PaperOrderRecord(
            validated_order=order, requested_at=requested_at, initial_status=BrokerOrderStatus.PENDING,
            rejection_reason=None, configuration_version=self._config.configuration_version(),
        )
        self._orders[order.client_order_id] = record
        self._fills[order.client_order_id] = []
        self._record_status(order.client_order_id, as_of=requested_at)

        self._attempt_fill(order.client_order_id, as_of=requested_at)

        return self._response_for(order.client_order_id, requested_at)

    def advance_simulation(self, as_of: datetime) -> tuple[OrderStatusObservation, ...]:
        """Not part of `BrokerAdapter` -- Paper-Trading-specific
        orchestration hook a driving loop calls to let still-open orders
        attempt further fills as simulated time (and therefore market
        data availability) moves forward. Returns every status
        observation whose status actually changed this call."""
        updates: list[OrderStatusObservation] = []
        for client_order_id, record in list(self._orders.items()):
            if client_order_id in self._cancelled or record.initial_status == BrokerOrderStatus.REJECTED:
                continue
            status_before = self._current_status(client_order_id)
            if status_before == BrokerOrderStatus.FILLED:
                continue
            history_len_before = len(self._status_history.get(client_order_id, ()))
            self._attempt_fill(client_order_id, as_of=as_of)
            history = self._status_history.get(client_order_id, ())
            if len(history) > history_len_before:
                updates.append(history[-1])
        return tuple(updates)

    def cancel_order(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse:
        self._check_transport_failure()
        record = self._orders.get(client_order_id)
        if record is None:
            return BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=client_order_id,
                broker_id=self.broker_id, operation="cancel_order", status=BrokerOrderStatus.UNKNOWN,
                broker_order_id=None, filled_quantity=None, avg_fill_price=None,
                error_code="unknown_client_order_id", error_message="no order was ever submitted with this client_order_id",
                attempt_count=1, latency_ms=0.0, responded_at=requested_at,
            )

        status = self._current_status(client_order_id)
        if status in (BrokerOrderStatus.FILLED, BrokerOrderStatus.REJECTED, BrokerOrderStatus.CANCELED):
            return self._response_for(
                client_order_id, requested_at,
                error_code="already_filled" if status == BrokerOrderStatus.FILLED else "not_cancellable",
            )

        self._cancelled.add(client_order_id)
        self._record_status(client_order_id, as_of=requested_at)
        return self._response_for(client_order_id, requested_at)

    def get_order_status(self, client_order_id: str, *, as_of: datetime) -> OrderStatusObservation:
        if self._config.failure_mode == "unknown_status":
            return OrderStatusObservation(
                observation_id=self._observation_ids.allocate(), client_order_id=client_order_id,
                broker_id=self.broker_id, broker_order_id=None, status=BrokerOrderStatus.UNKNOWN,
                filled_quantity=None, avg_fill_price=None, observed_at=as_of, raw_status_code=None,
            )
        history = self._status_history.get(client_order_id)
        if not history:
            return OrderStatusObservation(
                observation_id=self._observation_ids.allocate(), client_order_id=client_order_id,
                broker_id=self.broker_id, broker_order_id=None, status=BrokerOrderStatus.UNKNOWN,
                filled_quantity=None, avg_fill_price=None, observed_at=as_of, raw_status_code=None,
            )
        return history[-1]

    def get_account(self, *, as_of: datetime) -> BrokerAccountSnapshot:
        self._check_transport_failure()
        snapshot = self._accounting.snapshot_view(as_of)
        return BrokerAccountSnapshot(
            broker_id=self.broker_id, as_of_time=as_of, available=True, unavailable_reason=None,
            cash=snapshot.cash, buying_power=snapshot.cash, currency="KRW",
        )

    def get_positions(self, *, as_of: datetime) -> tuple[BrokerPosition, ...]:
        self._check_transport_failure()
        snapshot = self._accounting.snapshot_view(as_of)
        return tuple(
            BrokerPosition(
                security_id=sid, as_of_time=as_of, available=True, unavailable_reason=None,
                quantity=pos.quantity, average_cost=pos.average_cost,
            )
            for sid, pos in snapshot.positions.items()
        )

    def get_capabilities(self, *, as_of: datetime) -> BrokerCapabilities:
        return build_capabilities(
            self.broker_id,
            {
                BrokerCapability.MARKET_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.CANCEL_ORDER: CapabilityStatus.ENABLED,
                BrokerCapability.ORDER_STATUS: CapabilityStatus.ENABLED,
                BrokerCapability.ACCOUNT_BALANCE: CapabilityStatus.ENABLED,
                BrokerCapability.POSITIONS: CapabilityStatus.ENABLED,
                BrokerCapability.IDEMPOTENT_CLIENT_ORDER_ID: CapabilityStatus.ENABLED,
                BrokerCapability.LIMIT_ORDER: CapabilityStatus.UNSUPPORTED,
                BrokerCapability.QUOTE: CapabilityStatus.UNSUPPORTED,
            },
            recorded_at=as_of,
        )
