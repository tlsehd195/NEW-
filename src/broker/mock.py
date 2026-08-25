"""MockBrokerAdapter: the only `BrokerAdapter` implementation this
project's own tests, backtests, or any Phase 0-13 pipeline may ever
call -- deterministic, fully offline, no network, no credential ever
read (instruction section 11, 18: "실제 주문을 발생시키지 않는 것이
절대 조건이다"). Mirrors `ai_gateway.provider.MockProviderAdapter`'s
role in Phase 12: prove the `BrokerAdapter` Protocol end to end before
any real integration is trusted.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 9,
18.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from broker.capabilities import build_capabilities
from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerOrderStatus, CapabilityStatus
from broker.errors import BrokerTransportError
from broker.models import BrokerAccountSnapshot, BrokerCapabilities, BrokerOrderResponse, BrokerPosition, OrderStatusObservation, ValidatedOrder

from backtest.enums import OrderSide


class _IdAllocator:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next_id = 1

    def allocate(self) -> str:
        value = f"{self._prefix}-{self._next_id:06d}"
        self._next_id += 1
        return value


class MockBrokerAdapter:
    """`failure_mode` deterministically simulates instruction section
    11/18's fail-closed and backtest-integration scenarios: `None`
    (accepted -- MARKET orders fill immediately, in full, at a fixed
    deterministic price), `"rejected"` (the order is refused outright,
    no position/cash change), `"partial_fill"` (exactly half the
    requested quantity fills), `"unavailable"` (every call raises
    `BrokerTransportError`, simulating "broker unavailable"/timeout at
    the domain level), `"account_unavailable"` (`get_account`/
    `get_positions` report `available=False`), `"status_unknown"`
    (`get_order_status` always reports `UNKNOWN`)."""

    def __init__(
        self,
        config: BrokerConfig,
        *,
        failure_mode: Optional[str] = None,
        initial_cash: float = 100_000.0,
        initial_positions: Optional[dict[str, float]] = None,
        fill_price: float = 100.0,
    ) -> None:
        self.broker_id = config.broker_id
        self._config = config
        self._failure_mode = failure_mode
        self._cash = initial_cash
        self._positions: dict[str, float] = dict(initial_positions or {})
        self._fill_price = fill_price
        self._orders: dict[str, BrokerOrderResponse] = {}
        self._status_history: dict[str, list[OrderStatusObservation]] = {}
        self._response_ids = _IdAllocator("BROKRESP")
        self._observation_ids = _IdAllocator("OSTAT")

    def _check_available(self) -> None:
        if self._failure_mode == "unavailable":
            raise BrokerTransportError(f"simulated broker unavailable for {self.broker_id!r}")

    def _record_status(self, order: ValidatedOrder, response: BrokerOrderResponse, *, observed_at: datetime) -> None:
        observation = OrderStatusObservation(
            observation_id=self._observation_ids.allocate(), client_order_id=order.client_order_id,
            broker_id=self.broker_id, broker_order_id=response.broker_order_id, status=response.status,
            filled_quantity=response.filled_quantity, avg_fill_price=response.avg_fill_price,
            observed_at=observed_at, raw_status_code=response.status.value,
        )
        self._status_history.setdefault(order.client_order_id, []).append(observation)

    def submit_order(self, order: ValidatedOrder, *, requested_at: datetime) -> BrokerOrderResponse:
        self._check_available()

        existing = self._orders.get(order.client_order_id)
        if existing is not None:
            return existing  # idempotent replay -- never resubmits a logically identical order

        broker_order_id = f"TOSSORD-{len(self._orders) + 1:08d}"

        if self._failure_mode == "rejected":
            response = BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=order.client_order_id,
                broker_id=self.broker_id, operation="submit_order", status=BrokerOrderStatus.REJECTED,
                broker_order_id=None, filled_quantity=None, avg_fill_price=None,
                error_code="simulated_rejection", error_message="simulated broker rejection",
                attempt_count=1, latency_ms=0.0, responded_at=requested_at,
                provenance=order.provenance, experiment_id=order.experiment_id,
            )
            self._orders[order.client_order_id] = response
            self._record_status(order, response, observed_at=requested_at)
            return response

        if self._failure_mode == "partial_fill":
            filled = order.quantity / 2.0
            response = BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=order.client_order_id,
                broker_id=self.broker_id, operation="submit_order", status=BrokerOrderStatus.PARTIAL_FILLED,
                broker_order_id=broker_order_id, filled_quantity=filled, avg_fill_price=self._fill_price,
                error_code=None, error_message=None, attempt_count=1, latency_ms=0.0,
                responded_at=requested_at, provenance=order.provenance, experiment_id=order.experiment_id,
            )
            self._orders[order.client_order_id] = response
            self._record_status(order, response, observed_at=requested_at)
            delta = filled if order.side == OrderSide.BUY else -filled
            self._positions[order.security_id] = self._positions.get(order.security_id, 0.0) + delta
            self._cash -= delta * self._fill_price
            return response

        response = BrokerOrderResponse(
            response_id=self._response_ids.allocate(), request_client_order_id=order.client_order_id,
            broker_id=self.broker_id, operation="submit_order", status=BrokerOrderStatus.FILLED,
            broker_order_id=broker_order_id, filled_quantity=order.quantity, avg_fill_price=self._fill_price,
            error_code=None, error_message=None, attempt_count=1, latency_ms=0.0,
            responded_at=requested_at, provenance=order.provenance, experiment_id=order.experiment_id,
        )
        self._orders[order.client_order_id] = response
        self._record_status(order, response, observed_at=requested_at)

        delta = order.quantity if order.side == OrderSide.BUY else -order.quantity
        self._positions[order.security_id] = self._positions.get(order.security_id, 0.0) + delta
        self._cash -= delta * self._fill_price
        return response

    def cancel_order(self, client_order_id: str, *, requested_at: datetime) -> BrokerOrderResponse:
        self._check_available()

        existing = self._orders.get(client_order_id)
        if existing is None:
            return BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=client_order_id,
                broker_id=self.broker_id, operation="cancel_order", status=BrokerOrderStatus.UNKNOWN,
                broker_order_id=None, filled_quantity=None, avg_fill_price=None,
                error_code="unknown_client_order_id", error_message="no order was ever submitted with this client_order_id",
                attempt_count=1, latency_ms=0.0, responded_at=requested_at,
            )

        if existing.status == BrokerOrderStatus.FILLED:
            # MockBrokerAdapter fills MARKET orders immediately -- nothing left to cancel, an honest response
            return BrokerOrderResponse(
                response_id=self._response_ids.allocate(), request_client_order_id=client_order_id,
                broker_id=self.broker_id, operation="cancel_order", status=BrokerOrderStatus.REJECTED,
                broker_order_id=existing.broker_order_id, filled_quantity=existing.filled_quantity,
                avg_fill_price=existing.avg_fill_price, error_code="already_filled",
                error_message="order already filled, nothing to cancel", attempt_count=1, latency_ms=0.0,
                responded_at=requested_at, provenance=existing.provenance, experiment_id=existing.experiment_id,
            )

        cancelled = BrokerOrderResponse(
            response_id=self._response_ids.allocate(), request_client_order_id=client_order_id,
            broker_id=self.broker_id, operation="cancel_order", status=BrokerOrderStatus.CANCELED,
            broker_order_id=existing.broker_order_id, filled_quantity=existing.filled_quantity,
            avg_fill_price=existing.avg_fill_price, error_code=None, error_message=None,
            attempt_count=1, latency_ms=0.0, responded_at=requested_at,
            provenance=existing.provenance, experiment_id=existing.experiment_id,
        )
        self._orders[client_order_id] = cancelled
        return cancelled

    def get_order_status(self, client_order_id: str, *, as_of: datetime) -> OrderStatusObservation:
        self._check_available()
        if self._failure_mode == "status_unknown":
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
        self._check_available()
        if self._failure_mode == "account_unavailable":
            return BrokerAccountSnapshot(
                broker_id=self.broker_id, as_of_time=as_of, available=False,
                unavailable_reason="simulated account read failure",
            )
        return BrokerAccountSnapshot(
            broker_id=self.broker_id, as_of_time=as_of, available=True, unavailable_reason=None,
            cash=self._cash, buying_power=self._cash, currency="KRW",
        )

    def get_positions(self, *, as_of: datetime) -> tuple[BrokerPosition, ...]:
        self._check_available()
        if self._failure_mode == "account_unavailable":
            return ()
        return tuple(
            BrokerPosition(
                security_id=security_id, as_of_time=as_of, available=True, unavailable_reason=None,
                quantity=quantity, average_cost=self._fill_price,
            )
            for security_id, quantity in self._positions.items()
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
