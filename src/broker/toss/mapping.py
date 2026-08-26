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
from broker.errors import BrokerAuthError, BrokerProviderError, BrokerRateLimitError
from broker.models import BrokerOrderResponse
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
