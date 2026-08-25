"""Broker Adapter data models.

See docs/specifications/PHASE-13-toss-securities-adapter.md sections 4,
5, 13, 14, 15.

**Structural boundary enforcement**: no type in this module has a
`target_weight`, `risk_budget`, `expected_return`, `prediction`, or
other Prediction/Decision/Sizing/Risk-authoritative-output field --
`ValidatedOrder` only ever *carries* the lineage ids
(`decision_id`/`sizing_id`/`risk_assessment_id`) those upstream layers
already produced, it never recomputes or overrides them
(`tests/broker/test_broker_boundary.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from broker.enums import BrokerCapability, BrokerOrderStatus, CapabilityStatus, OrderValidationStatus

from backtest.enums import OrderSide, OrderType

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: Optional[datetime]) -> None:
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class ValidatedOrder:
    """The single authoritative order intent a `BrokerAdapter` may act
    on -- always built by `broker.validation.build_validated_order` from
    an already risk-approved `risk.models.RiskCheckedPosition`, never
    constructed ad hoc from a raw prediction/decision. `client_order_id`
    is deterministic (instruction section 12): the same
    decision/sizing/risk/symbol/side/quantity/as_of_time always produces
    the same id, so a retried submission is recognizable as the same
    logical order rather than silently duplicated."""

    client_order_id: str
    security_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType  # always OrderType.MARKET this phase -- see broker.validation
    as_of_time: datetime

    decision_id: str
    sizing_id: str
    risk_assessment_id: str

    configuration_version: str
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.client_order_id:
            raise ValueError("ValidatedOrder.client_order_id must not be empty")
        if not self.security_id:
            raise ValueError("ValidatedOrder.security_id must not be empty")
        if not (self.quantity > 0 and self.quantity == self.quantity and self.quantity != float("inf")):
            raise ValueError(f"ValidatedOrder.quantity must be a positive finite number, got {self.quantity!r}")
        if not self.decision_id or not self.sizing_id or not self.risk_assessment_id:
            raise ValueError("ValidatedOrder requires non-empty decision_id/sizing_id/risk_assessment_id")
        _require_aware("ValidatedOrder.as_of_time", self.as_of_time)


@dataclass(frozen=True)
class OrderValidationResult:
    """Always returned by `broker.validation.build_validated_order` --
    never an exception for a rejected (as opposed to malformed-input)
    case, mirroring `learning.cleaning.DataCleaner`'s "always return a
    verdict, never silently drop" discipline. `status ==
    VALIDATION_REJECTED` is instruction section 5's required, explicit
    terminal state -- a rejected order is never silently coerced into
    a submittable one."""

    status: OrderValidationStatus
    validated_order: Optional[ValidatedOrder]
    reason: str  # "ok" or the specific failed check name
    checks: dict

    def __post_init__(self) -> None:
        if self.status == OrderValidationStatus.ACCEPTED and self.validated_order is None:
            raise ValueError("OrderValidationResult.status == ACCEPTED requires validated_order to be set")
        if self.status == OrderValidationStatus.VALIDATION_REJECTED and self.validated_order is not None:
            raise ValueError("OrderValidationResult.status == VALIDATION_REJECTED must not carry a validated_order")


@dataclass(frozen=True)
class BrokerOrderResponse:
    """The outcome of one `submit_order`/`cancel_order` call. Always
    exactly one of `status == UNKNOWN` (whenever the adapter cannot
    positively confirm what happened -- transport failure, malformed
    broker response, disconnected mid-call) or a concrete
    `BrokerOrderStatus`; never a fabricated `FILLED`/`ACCEPTED`
    (instruction section 11: "unknown broker response ≠ success")."""

    response_id: str  # "BROKRESP-000001"
    request_client_order_id: str
    broker_id: str
    operation: str  # "submit_order" | "cancel_order"
    status: BrokerOrderStatus
    broker_order_id: Optional[str]
    filled_quantity: Optional[float]
    avg_fill_price: Optional[float]
    error_code: Optional[str]
    error_message: Optional[str]  # sanitized -- never contains a credential (tests/broker/test_broker_secret_safety.py)
    attempt_count: int
    latency_ms: Optional[float]
    responded_at: datetime
    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.request_client_order_id:
            raise ValueError("BrokerOrderResponse requires non-empty response_id/request_client_order_id")
        _require_aware("BrokerOrderResponse.responded_at", self.responded_at)
        if self.attempt_count < 0:
            raise ValueError("BrokerOrderResponse.attempt_count must not be negative")


@dataclass(frozen=True)
class OrderStatusObservation:
    """One observed status for one order at one point in time --
    append-only, mirrors `ai_gateway.models.ProviderQuotaState`'s "one
    observation per point in time" pattern (Phase 12). An order's
    *current* status is always its most recent observation, never a
    mutated single record."""

    observation_id: str  # "OSTAT-000001"
    client_order_id: str
    broker_id: str
    broker_order_id: Optional[str]
    status: BrokerOrderStatus
    filled_quantity: Optional[float]
    avg_fill_price: Optional[float]
    observed_at: datetime
    raw_status_code: Optional[str]  # the literal string the broker returned, for audit -- never used directly as BrokerOrderStatus without going through broker.<vendor>.mapping

    def __post_init__(self) -> None:
        if not self.observation_id or not self.client_order_id:
            raise ValueError("OrderStatusObservation requires non-empty observation_id/client_order_id")
        _require_aware("OrderStatusObservation.observed_at", self.observed_at)


@dataclass(frozen=True)
class BrokerAccountSnapshot:
    """Instruction section 14: an unavailable/incomplete read is
    preserved as `available=False`, never defaulted to "0원" or any
    other guessed value."""

    broker_id: str
    as_of_time: datetime
    available: bool
    unavailable_reason: Optional[str]
    cash: Optional[float] = None
    buying_power: Optional[float] = None
    currency: Optional[str] = None

    def __post_init__(self) -> None:
        _require_aware("BrokerAccountSnapshot.as_of_time", self.as_of_time)
        if self.available and self.unavailable_reason is not None:
            raise ValueError("BrokerAccountSnapshot.available=True must not carry an unavailable_reason")
        if not self.available and self.unavailable_reason is None:
            raise ValueError("BrokerAccountSnapshot.available=False requires a factual unavailable_reason")
        if not self.available and (self.cash is not None or self.buying_power is not None):
            raise ValueError("BrokerAccountSnapshot.available=False must not carry cash/buying_power values")


@dataclass(frozen=True)
class BrokerPosition:
    security_id: str
    as_of_time: datetime
    available: bool
    unavailable_reason: Optional[str]
    quantity: Optional[float] = None
    average_cost: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.security_id:
            raise ValueError("BrokerPosition.security_id must not be empty")
        _require_aware("BrokerPosition.as_of_time", self.as_of_time)
        if self.available and self.unavailable_reason is not None:
            raise ValueError("BrokerPosition.available=True must not carry an unavailable_reason")
        if not self.available and self.unavailable_reason is None:
            raise ValueError("BrokerPosition.available=False requires a factual unavailable_reason")
        if not self.available and self.quantity is not None:
            raise ValueError("BrokerPosition.available=False must not carry a quantity value")


@dataclass(frozen=True)
class BrokerCapabilities:
    broker_id: str
    capabilities: dict[BrokerCapability, CapabilityStatus]
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.broker_id:
            raise ValueError("BrokerCapabilities.broker_id must not be empty")
        _require_aware("BrokerCapabilities.recorded_at", self.recorded_at)

    def status_of(self, capability: BrokerCapability) -> CapabilityStatus:
        return self.capabilities.get(capability, CapabilityStatus.UNKNOWN)

    def is_enabled(self, capability: BrokerCapability) -> bool:
        return self.status_of(capability) == CapabilityStatus.ENABLED


@dataclass(frozen=True)
class BrokerRequestRecord:
    """A generic, uniform audit log entry for *every* `BrokerAdapter`
    call (submit/cancel/status/account/positions) -- mirrors
    `ai_gateway.models.AIRequest`'s role (Phase 12). `payload` is
    already redaction-safe by construction: nothing that builds this
    record ever has access to a resolved secret value in the first
    place (`broker.toss.auth` resolves credentials only for the HTTP
    call itself, never returning them to any caller that could put them
    here)."""

    request_id: str  # "BROKREQ-000001"
    broker_id: str
    operation: str
    execution_mode: str
    client_order_id: Optional[str]
    decision_id: Optional[str]
    sizing_id: Optional[str]
    risk_assessment_id: Optional[str]
    configuration_version: str
    requested_at: datetime
    provenance: TradeProvenance
    payload: dict = field(default_factory=dict)
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.request_id or not self.broker_id or not self.operation:
            raise ValueError("BrokerRequestRecord requires non-empty request_id/broker_id/operation")
        _require_aware("BrokerRequestRecord.requested_at", self.requested_at)


@dataclass(frozen=True)
class BrokerResponseRecord:
    response_id: str  # "BROKRESLOG-000001"
    request_id: str
    broker_id: str
    operation: str
    status: str
    broker_order_id: Optional[str]
    error_code: Optional[str]
    attempt_count: int
    latency_ms: Optional[float]
    responded_at: datetime
    provenance: TradeProvenance
    metadata: dict = field(default_factory=dict)
    experiment_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.response_id or not self.request_id:
            raise ValueError("BrokerResponseRecord requires non-empty response_id/request_id")
        _require_aware("BrokerResponseRecord.responded_at", self.responded_at)
