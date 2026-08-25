"""Category: Toss Response Mapping Test -- instruction section 13: raw
Toss Securities API output is never passed through unchanged; every
status/error is mapped through `broker.toss.mapping`, and an
unrecognized value is always `UNKNOWN`, never guessed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerAuthError, BrokerRateLimitError
from broker.toss.mapping import map_order_status, parse_order_response
from broker.transport import TransportResponse


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class TestMapOrderStatus:
    @pytest.mark.parametrize("raw,expected", [
        ("PENDING", BrokerOrderStatus.PENDING),
        ("PARTIAL_FILLED", BrokerOrderStatus.PARTIAL_FILLED),
        ("PENDING_CANCEL", BrokerOrderStatus.PENDING_CANCEL),
        ("PENDING_REPLACE", BrokerOrderStatus.PENDING_REPLACE),
        ("FILLED", BrokerOrderStatus.FILLED),
        ("CANCELED", BrokerOrderStatus.CANCELED),
        ("REJECTED", BrokerOrderStatus.REJECTED),
        ("REPLACED", BrokerOrderStatus.REPLACED),
    ])
    def test_confirmed_status_values(self, raw, expected) -> None:
        assert map_order_status(raw) == expected

    def test_none_is_unknown(self) -> None:
        assert map_order_status(None) == BrokerOrderStatus.UNKNOWN

    def test_unrecognized_string_is_unknown_not_guessed(self) -> None:
        assert map_order_status("SOME_NEW_STATUS_TOSS_ADDED_LATER") == BrokerOrderStatus.UNKNOWN


class TestParseOrderResponse:
    def test_success_response_maps_to_filled(self) -> None:
        response = TransportResponse(200, {"status": "FILLED", "orderId": "TOSS-1", "filledQuantity": "10"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.FILLED
        assert result.broker_order_id == "TOSS-1"

    def test_401_raises_broker_auth_error(self) -> None:
        response = TransportResponse(401, {"code": "expired-token", "message": "token expired"}, None, {})
        with pytest.raises(BrokerAuthError):
            parse_order_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
                attempt_count=1, responded_at=utc(2024, 1, 2),
            )

    def test_429_raises_broker_rate_limit_error(self) -> None:
        response = TransportResponse(429, {"code": "rate-limited", "message": "too many requests"}, {"retry-after": "1"}, {})
        with pytest.raises(BrokerRateLimitError):
            parse_order_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
                attempt_count=1, responded_at=utc(2024, 1, 2),
            )

    def test_insufficient_buying_power_maps_to_rejected_with_error_code(self) -> None:
        response = TransportResponse(400, {"code": "insufficient-buying-power", "message": "not enough cash"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.REJECTED
        assert result.error_code == "insufficient-buying-power"

    def test_price_out_of_range_maps_to_rejected(self) -> None:
        response = TransportResponse(400, {"code": "price-out-of-range", "message": "bad price"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.REJECTED
        assert result.error_code == "price-out-of-range"

    def test_order_hours_closed_maps_to_rejected(self) -> None:
        response = TransportResponse(400, {"code": "order-hours-closed", "message": "market closed"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.REJECTED

    def test_malformed_body_is_unknown_never_success(self) -> None:
        response = TransportResponse(200, None, "{not valid json", {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.UNKNOWN
        assert result.error_code == "malformed_response"

    def test_unrecognized_status_string_maps_to_unknown(self) -> None:
        response = TransportResponse(200, {"status": "SOME_NEW_STATUS", "orderId": "TOSS-1"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.UNKNOWN

    def test_error_message_is_redacted_if_it_looks_like_a_credential(self) -> None:
        response = TransportResponse(400, {"code": "weird", "message": "Authorization: Bearer sk-abc123"}, None, {})
        result = parse_order_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss", operation="submit_order",
            attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert "sk-abc123" not in (result.error_message or "")
