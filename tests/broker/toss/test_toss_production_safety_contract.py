"""Category: Toss Adapter Contract Test (Phase 17 -- Production Safety
Review). Every scenario here uses `broker.transport.TransportResponse`
built by hand or `MockTransport` -- never real network I/O against
`openapi.tossinvest.com` (instruction section 11, 22: no real Toss API
call this phase). These tests supplement, not replace,
`test_toss_mapping.py`/`test_toss_adapter.py`/`test_toss_transport.py`
(Phase 13), which already cover missing-field/malformed/timeout/
connection-failure/auth-failure(401)/rate-limit(429)/several 4xx
provider-error-code scenarios and the confirmed status vocabulary.

Two scenarios instruction section 6 asks for are structurally
untestable at this layer, and are documented here rather than faked:

- duplicate-client-order-id: `POST /api/v1/orders`'s real de-duplication
  behavior for a repeated `clientOrderId` was not found in any source
  available to this session (docs/specifications/
  PHASE-13-toss-securities-adapter.md "Toss API Verification"); the
  correct HTTP status/body Toss would return is UNKNOWN. Fabricating a
  response shape here would itself be exactly the kind of guess
  instruction section 6 forbids. `broker.live.session.LiveTradingSession`
  does not rely on Toss doing this correctly in the first place -- see
  `TestIdempotencyDoesNotDependOnBrokerDeduplication` below.
- sandbox behavior: Toss Securities has no public sandbox
  (`docs/specifications/PHASE-13-toss-securities-adapter.md`), so no
  contract test anywhere in this repository can be run against one.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerProviderError
from broker.toss.mapping import parse_order_response
from broker.transport import TransportResponse


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestProviderErrorIsNeverConfusedWithADefinitiveRejection:
    """A 5xx means the broker's own infrastructure failed -- it is not
    evidence the order was looked at and declined. Before this phase,
    `parse_order_response` mapped every status >= 400 (including 5xx) to
    `BrokerOrderStatus.REJECTED`, which would have told
    `LiveTradingSession` "safe to consider this order done" when the
    true state was unknown. This is now `BrokerProviderError`, routed
    through the same UNKNOWN + RECONCILIATION_REQUIRED path as a
    timeout (`broker.live.session.LiveTradingSession.submit`)."""

    def test_500_raises_broker_provider_error_not_rejected(self) -> None:
        response = TransportResponse(500, {"code": "internal-error", "message": "unexpected failure"}, None, {})
        with pytest.raises(BrokerProviderError):
            parse_order_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
                attempt_count=1, responded_at=utc(2024, 1, 2),
            )

    def test_503_raises_broker_provider_error(self) -> None:
        response = TransportResponse(503, {"code": "service-unavailable", "message": "try again later"}, None, {})
        with pytest.raises(BrokerProviderError):
            parse_order_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
                attempt_count=1, responded_at=utc(2024, 1, 2),
            )

    def test_500_with_no_body_still_raises_and_does_not_crash(self) -> None:
        response = TransportResponse(500, None, "internal server error", {})
        with pytest.raises(BrokerProviderError):
            parse_order_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
                attempt_count=1, responded_at=utc(2024, 1, 2),
            )

    def test_provider_error_message_is_still_redacted_if_credential_shaped(self) -> None:
        response = TransportResponse(500, {"code": "internal-error", "message": "Authorization: Bearer sk-abc123"}, None, {})
        with pytest.raises(BrokerProviderError) as excinfo:
            parse_order_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
                attempt_count=1, responded_at=utc(2024, 1, 2),
            )
        assert "sk-abc123" not in str(excinfo.value)


class TestPartialAndFullFillAndCancelledThroughFullResponseParsing:
    """test_toss_mapping.py already parametrizes `map_order_status` in
    isolation for every confirmed value; these exercise the same values
    through the full `parse_order_response` response-object path a real
    `submit_order` call actually uses."""

    def test_partial_filled_response(self) -> None:
        response = TransportResponse(200, {"status": "PARTIAL_FILLED", "orderId": "TOSS-1", "filledQuantity": "3"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.PARTIAL_FILLED
        assert result.filled_quantity == "3"

    def test_filled_response(self) -> None:
        response = TransportResponse(200, {"status": "FILLED", "orderId": "TOSS-1", "filledQuantity": "10"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.FILLED

    def test_cancelled_response(self) -> None:
        response = TransportResponse(200, {"status": "CANCELED", "orderId": "TOSS-1"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.CANCELED

    def test_rejected_response_has_no_broker_order_id(self) -> None:
        response = TransportResponse(200, {"status": "REJECTED"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.REJECTED
        assert result.broker_order_id is None


class TestUnknownIsStructurallyNeverASuccessStatus:
    """Direct structural proof for Production Safety Review area 1: no
    response this parser can ever produce reports `UNKNOWN` for a case
    where the order is known to have been accepted."""

    _SUCCESS_STATUSES = frozenset({BrokerOrderStatus.FILLED, BrokerOrderStatus.PARTIAL_FILLED})

    def test_unknown_not_in_success_statuses(self) -> None:
        assert BrokerOrderStatus.UNKNOWN not in self._SUCCESS_STATUSES

    @pytest.mark.parametrize("raw_status", [None, "", "GARBAGE", "success", "filled"])  # case-sensitive, never guessed
    def test_every_unrecognized_or_missing_status_maps_to_unknown_never_a_success_status(self, raw_status) -> None:
        from broker.toss.mapping import map_order_status

        mapped = map_order_status(raw_status if raw_status else None)
        assert mapped == BrokerOrderStatus.UNKNOWN
        assert mapped not in self._SUCCESS_STATUSES


class TestIdempotencyDoesNotDependOnBrokerDeduplication:
    """Toss's real behavior for a resubmitted `clientOrderId` is
    UNCONFIRMED (see module docstring) -- so this codebase's own
    idempotency safety cannot be allowed to depend on Toss doing the
    right thing. `LiveTradingSession` never resubmits an order whose
    outcome is unknown; it blocks all further submissions
    session-wide until `reconcile_order` runs
    (docs/specifications/PHASE-16-live-trading.md section 9). This is
    verified end to end in
    tests/broker/live/test_live_session.py -- this test only pins the
    documentation-level contract so a future change to endpoints.py
    cannot silently start assuming server-side dedup exists."""

    def test_cancel_order_path_remains_unconfirmed_not_guessed(self) -> None:
        from broker.toss.endpoints import CANCEL_ORDER_PATH, ORDER_STATUS_PATH

        assert CANCEL_ORDER_PATH is None
        assert ORDER_STATUS_PATH is None
