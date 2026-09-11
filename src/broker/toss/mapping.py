"""Maps Toss Securities' real order-status vocabulary and error-response
shape to this codebase's domain types -- instruction section 13: "API
response를 그대로 시스템 내부에 퍼뜨리지 말고 domain model로 변환한다."

Confirmed via research (docs/specifications/PHASE-13-toss-securities-adapter.md
"Toss API Verification"): order status values PENDING/PARTIAL_FILLED/
PENDING_CANCEL/PENDING_REPLACE (open) and FILLED/CANCELED/REJECTED/
REPLACED (closed); error response fields `code`/`message`/`data`/
`requestId`; example error codes `expired-token`/
`insufficient-buying-power`/`order-hours-closed`/`price-out-of-range`.
The exact field name for the broker's own assigned order id in a
*response* body was not independently confirmed (only the *request*
schema was), so `parse_order_response` reads it defensively (`orderId`
falling back to `id`, `None` if neither is present) rather than assuming
either is correct -- a `BrokerOrderResponse.broker_order_id=None` is
always a safe, honest outcome; a wrong guess presented as certain would
not be.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerAuthError, BrokerProviderError, BrokerRateLimitError, BrokerTransportError
from broker.models import BrokerAccountSnapshot, BrokerOrderResponse, BrokerPosition, OrderStatusObservation
from broker.transport import TransportResponse

from trade_journal.enums import TradeProvenance

_STATUS_MAP: dict[str, BrokerOrderStatus] = {
    "PENDING": BrokerOrderStatus.PENDING,
    "PARTIAL_FILLED": BrokerOrderStatus.PARTIAL_FILLED,
    "PENDING_CANCEL": BrokerOrderStatus.PENDING_CANCEL,
    "PENDING_REPLACE": BrokerOrderStatus.PENDING_REPLACE,
    "FILLED": BrokerOrderStatus.FILLED,
    "CANCELED": BrokerOrderStatus.CANCELED,
    "REJECTED": BrokerOrderStatus.REJECTED,
    "REPLACED": BrokerOrderStatus.REPLACED,
    # Phase 21 addition (Tier 1 -- the official spec's Order.status enum
    # has 10 values, not the 8 Phase 13 originally mapped; see
    # docs/operations/TOSS-API-GAP-ANALYSIS.md Phase 20 addendum).
    "CANCEL_REJECTED": BrokerOrderStatus.CANCEL_REJECTED,
    "REPLACE_REJECTED": BrokerOrderStatus.REPLACE_REJECTED,
}

# A cancel request's 409 conflict response tells us, in a few cases,
# something unambiguous about the *original* order's own true state --
# only those three are mapped; every other documented conflict/business
# code (already-modified, already-processing, cancel-restricted,
# order-hours-closed, order-not-found, or anything unrecognized) stays
# UNKNOWN rather than guessed, with error_code always preserved for
# audit (docs/operations/TOSS-API-GAP-ANALYSIS.md Phase 20 addendum).
_CANCEL_CONFLICT_STATUS_MAP: dict[str, BrokerOrderStatus] = {
    "already-filled": BrokerOrderStatus.FILLED,
    "already-canceled": BrokerOrderStatus.CANCELED,
    "already-rejected": BrokerOrderStatus.REJECTED,
}

_MAX_ERROR_MESSAGE_LENGTH = 500


def map_order_status(raw: Optional[str]) -> BrokerOrderStatus:
    """A status string this map does not recognize -- including `None`
    -- is `UNKNOWN`, never guessed at (instruction section 13: "확인할
    수 없는 상태는 UNKNOWN으로 fail-closed")."""
    if raw is None:
        return BrokerOrderStatus.UNKNOWN
    return _STATUS_MAP.get(raw, BrokerOrderStatus.UNKNOWN)


def _sanitize_message(message: Optional[str]) -> Optional[str]:
    """Truncates and never echoes anything shaped like a credential --
    the message field in a Toss error response is documented as
    human-readable text, never a header/token, but this is a defensive
    backstop in case a future response ever embedded one."""
    if message is None:
        return None
    text = str(message)[:_MAX_ERROR_MESSAGE_LENGTH]
    for marker in ("Bearer ", "Authorization:", "client_secret"):
        if marker in text:
            return "error message redacted -- contained a credential-shaped substring"
    return text


def parse_order_response(
    response: TransportResponse,
    *,
    response_id: str,
    client_order_id: str,
    broker_id: str,
    operation: str,
    attempt_count: int,
    responded_at: datetime,
    provenance: TradeProvenance = TradeProvenance.LIVE_TRADING,
    experiment_id: Optional[str] = None,
) -> BrokerOrderResponse:
    if response.status_code == 401:
        raise BrokerAuthError(_sanitize_message((response.body or {}).get("message")) or "authentication failed")
    if response.status_code == 429:
        raise BrokerRateLimitError(_sanitize_message((response.body or {}).get("message")) or "rate limited")
    if response.status_code >= 500:
        # A provider-side failure, not a broker decision about the order
        # -- REJECTED would falsely assert certainty this response never
        # gives (Phase 17 Production Safety Review finding).
        raise BrokerProviderError(
            _sanitize_message((response.body or {}).get("message")) or f"provider error: HTTP {response.status_code}"
        )

    if response.body is None:
        return BrokerOrderResponse(
            response_id=response_id, request_client_order_id=client_order_id, broker_id=broker_id,
            operation=operation, status=BrokerOrderStatus.UNKNOWN, broker_order_id=None,
            filled_quantity=None, avg_fill_price=None, error_code="malformed_response",
            error_message="response body was not valid JSON", attempt_count=attempt_count,
            latency_ms=None, responded_at=responded_at, provenance=provenance, experiment_id=experiment_id,
        )

    if response.status_code >= 400:
        code = response.body.get("code")
        return BrokerOrderResponse(
            response_id=response_id, request_client_order_id=client_order_id, broker_id=broker_id,
            operation=operation, status=BrokerOrderStatus.REJECTED, broker_order_id=None,
            filled_quantity=None, avg_fill_price=None, error_code=code,
            error_message=_sanitize_message(response.body.get("message")), attempt_count=attempt_count,
            latency_ms=None, responded_at=responded_at, provenance=provenance, experiment_id=experiment_id,
        )

    raw_status = response.body.get("status")
    status = map_order_status(raw_status)
    broker_order_id = response.body.get("orderId") or response.body.get("id")
    filled_quantity = response.body.get("filledQuantity")
    avg_fill_price = response.body.get("avgFillPrice")

    return BrokerOrderResponse(
        response_id=response_id, request_client_order_id=client_order_id, broker_id=broker_id,
        operation=operation, status=status, broker_order_id=broker_order_id,
        filled_quantity=filled_quantity, avg_fill_price=avg_fill_price, error_code=None, error_message=None,
        attempt_count=attempt_count, latency_ms=None, responded_at=responded_at,
        provenance=provenance, experiment_id=experiment_id,
    )


def _to_float_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _raise_for_transport_level_failure(response: TransportResponse) -> None:
    """Shared across every Phase 21 read-only endpoint: a 401/429/5xx is
    never a fact about the *account/position/order* -- it is the same
    transport-uncertainty class `parse_order_response` already
    distinguishes from a definitive 4xx business-rule response (Phase
    17 Production Safety Review finding, unchanged)."""
    if response.status_code == 401:
        raise BrokerAuthError(_sanitize_message((response.body or {}).get("message")) or "authentication failed")
    if response.status_code == 429:
        raise BrokerRateLimitError(_sanitize_message((response.body or {}).get("message")) or "rate limited")
    if response.status_code >= 500:
        raise BrokerProviderError(
            _sanitize_message((response.body or {}).get("message")) or f"provider error: HTTP {response.status_code}"
        )


def parse_buying_power_response(
    response: TransportResponse, *, broker_id: str, as_of_time: datetime,
) -> BrokerAccountSnapshot:
    """`GET /api/v1/buying-power` -> `BuyingPowerResponse{currency,
    cashBuyingPower}` (Tier 1, Phase 21 -- see
    docs/operations/TOSS-API-GAP-ANALYSIS.md Phase 20 addendum). A
    401/429/5xx raises (transport uncertainty); a well-formed 4xx or a
    malformed/incomplete 2xx body both become `available=False` with a
    factual `unavailable_reason` -- never a guessed cash figure
    (instruction section 6: "문서에 없는 값을 계산해서 만들어내지
    마라")."""
    _raise_for_transport_level_failure(response)

    if response.body is None:
        return BrokerAccountSnapshot(
            broker_id=broker_id, as_of_time=as_of_time, available=False,
            unavailable_reason="malformed_response: response body was not valid JSON",
        )
    if response.status_code >= 400:
        code = response.body.get("code")
        reason = _sanitize_message(response.body.get("message")) or code or f"http_{response.status_code}"
        return BrokerAccountSnapshot(broker_id=broker_id, as_of_time=as_of_time, available=False, unavailable_reason=reason)

    currency = response.body.get("currency")
    cash = _to_float_or_none(response.body.get("cashBuyingPower"))
    if currency is None or cash is None:
        return BrokerAccountSnapshot(
            broker_id=broker_id, as_of_time=as_of_time, available=False,
            unavailable_reason="malformed_response: missing or non-numeric currency/cashBuyingPower",
        )
    return BrokerAccountSnapshot(
        broker_id=broker_id, as_of_time=as_of_time, available=True, unavailable_reason=None,
        cash=cash, buying_power=cash, currency=currency,
    )


def parse_holdings_response(response: TransportResponse, *, as_of_time: datetime) -> tuple[BrokerPosition, ...]:
    """`GET /api/v1/holdings` -> `HoldingsOverview{..., items[]}` (Tier
    1, Phase 21). `items: []` on a well-formed 2xx is a genuine, honest
    "zero positions" -- not an error. Any malformed item is treated as
    the whole response being untrustworthy (raises) rather than silently
    dropping one position from a list a caller may reconcile an entire
    account against -- a partial position list presented as complete
    would be worse than an explicit failure (Phase 21 instruction
    section 7: "positions API가 빈 목록"과 "positions 조회 실패/unknown"을
    구분하라).

    **Known issue** (Phase 21 instruction section 7, explicitly not
    fixed here): `BrokerAdapter.get_positions()`'s return type,
    `tuple[BrokerPosition, ...]`, has no way to represent "positions
    read failed" separately from "zero positions" the way
    `BrokerAccountSnapshot.available=False` does for `get_account()` --
    an empty tuple is structurally ambiguous between the two. This
    function narrows that ambiguity as much as it can without changing
    the Protocol: a genuine read failure raises (`BrokerTransportError`
    or one of the auth/rate-limit/provider errors) rather than
    returning `()`, so only a *successful* empty-holdings response ever
    produces an empty tuple. `MockBrokerAdapter`'s own
    `account_unavailable` simulation used to return `()` for
    `get_positions` too -- the same ambiguity, in the test double
    rather than here -- and has since been aligned to raise as well
    (ADR-0117)."""
    _raise_for_transport_level_failure(response)

    if response.body is None:
        raise BrokerTransportError("malformed holdings response: body was not valid JSON")
    if response.status_code >= 400:
        code = response.body.get("code")
        raise BrokerTransportError(f"holdings query failed: {_sanitize_message(response.body.get('message')) or code}")

    items = response.body.get("items")
    if not isinstance(items, list):
        raise BrokerTransportError("malformed holdings response: 'items' missing or not a list")

    positions = []
    for item in items:
        symbol = item.get("symbol") if isinstance(item, dict) else None
        quantity = _to_float_or_none(item.get("quantity")) if isinstance(item, dict) else None
        if not symbol or quantity is None:
            raise BrokerTransportError(f"malformed holdings item, refusing to return a partial position list: {item!r}")
        average_cost = _to_float_or_none(item.get("averagePurchasePrice"))
        positions.append(
            BrokerPosition(
                security_id=symbol, as_of_time=as_of_time, available=True, unavailable_reason=None,
                quantity=quantity, average_cost=average_cost,
            )
        )
    return tuple(positions)


def parse_order_detail_response(
    response: TransportResponse, *, observation_id: str, client_order_id: str, broker_id: str, observed_at: datetime,
) -> OrderStatusObservation:
    """`GET /api/v1/orders/{orderId}` -> a single `Order{...}` object
    (Tier 1, Phase 21 -- see broker.toss.endpoints.
    ORDER_DETAIL_PATH_TEMPLATE's docstring for why this endpoint,
    not the list one, is used here)."""
    _raise_for_transport_level_failure(response)

    if response.body is None:
        return OrderStatusObservation(
            observation_id=observation_id, client_order_id=client_order_id, broker_id=broker_id,
            broker_order_id=None, status=BrokerOrderStatus.UNKNOWN, filled_quantity=None, avg_fill_price=None,
            observed_at=observed_at, raw_status_code=None,
        )
    if response.status_code >= 400:
        # 404 order-not-found and any other documented 4xx here are a
        # definitive "we asked and got an error," but none of them
        # unambiguously map to a BrokerOrderStatus value -- UNKNOWN,
        # with the real code preserved via raw_status_code for audit.
        code = response.body.get("code")
        return OrderStatusObservation(
            observation_id=observation_id, client_order_id=client_order_id, broker_id=broker_id,
            broker_order_id=None, status=BrokerOrderStatus.UNKNOWN, filled_quantity=None, avg_fill_price=None,
            observed_at=observed_at, raw_status_code=code,
        )

    raw_status = response.body.get("status")
    status = map_order_status(raw_status)
    broker_order_id = response.body.get("orderId")
    execution = response.body.get("execution") or {}
    filled_quantity = _to_float_or_none(execution.get("filledQuantity"))
    avg_fill_price = _to_float_or_none(execution.get("averageFilledPrice"))
    return OrderStatusObservation(
        observation_id=observation_id, client_order_id=client_order_id, broker_id=broker_id,
        broker_order_id=broker_order_id, status=status, filled_quantity=filled_quantity,
        avg_fill_price=avg_fill_price, observed_at=observed_at, raw_status_code=raw_status,
    )


def parse_cancel_response(
    response: TransportResponse,
    *,
    response_id: str,
    client_order_id: str,
    broker_id: str,
    original_broker_order_id: Optional[str],
    attempt_count: int,
    responded_at: datetime,
    provenance: TradeProvenance = TradeProvenance.LIVE_TRADING,
    experiment_id: Optional[str] = None,
) -> BrokerOrderResponse:
    """`POST /api/v1/orders/{orderId}/cancel` -> `OrderOperationResponse
    {orderId}` (Tier 1, Phase 21). **Critical semantics preserved**: the
    response `orderId` is a newly issued id for the cancel operation
    itself, never confused with the original order's id --
    `broker_order_id` on the returned `BrokerOrderResponse` always
    stays `original_broker_order_id` (the order this response is
    about), while the new id (if the broker returned one) is carried
    separately in `cancel_reference_id`. See
    `broker.models.BrokerOrderResponse.cancel_reference_id`."""
    _raise_for_transport_level_failure(response)

    if response.body is None:
        return BrokerOrderResponse(
            response_id=response_id, request_client_order_id=client_order_id, broker_id=broker_id,
            operation="cancel_order", status=BrokerOrderStatus.UNKNOWN, broker_order_id=original_broker_order_id,
            filled_quantity=None, avg_fill_price=None, error_code="malformed_response",
            error_message="response body was not valid JSON", attempt_count=attempt_count, latency_ms=None,
            responded_at=responded_at, provenance=provenance, experiment_id=experiment_id,
        )

    if response.status_code >= 400:
        code = response.body.get("code")
        status = _CANCEL_CONFLICT_STATUS_MAP.get(code, BrokerOrderStatus.UNKNOWN)
        return BrokerOrderResponse(
            response_id=response_id, request_client_order_id=client_order_id, broker_id=broker_id,
            operation="cancel_order", status=status, broker_order_id=original_broker_order_id,
            filled_quantity=None, avg_fill_price=None, error_code=code,
            error_message=_sanitize_message(response.body.get("message")), attempt_count=attempt_count,
            latency_ms=None, responded_at=responded_at, provenance=provenance, experiment_id=experiment_id,
        )

    # A 2xx cancel response carries no status field of its own (only
    # {orderId}, the new cancel-operation id) -- a successful call to
    # this specific endpoint is interpreted as CANCELED, matching the
    # endpoint's own name/semantics (mirrors broker.mock.
    # MockBrokerAdapter.cancel_order's successful-path return value).
    cancel_reference_id = response.body.get("orderId")
    return BrokerOrderResponse(
        response_id=response_id, request_client_order_id=client_order_id, broker_id=broker_id,
        operation="cancel_order", status=BrokerOrderStatus.CANCELED, broker_order_id=original_broker_order_id,
        filled_quantity=None, avg_fill_price=None, error_code=None, error_message=None,
        attempt_count=attempt_count, latency_ms=None, responded_at=responded_at,
        provenance=provenance, experiment_id=experiment_id, cancel_reference_id=cancel_reference_id,
    )
