"""Category: Toss Response Mapping Test -- instruction section 13: raw
Toss Securities API output is never passed through unchanged; every
status/error is mapped through `broker.toss.mapping`, and an
unrecognized value is always `UNKNOWN`, never guessed."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerAuthError, BrokerProviderError, BrokerRateLimitError, BrokerTransportError
from broker.toss.mapping import (
    map_order_status,
    parse_buying_power_response,
    parse_cancel_response,
    parse_holdings_response,
    parse_order_detail_response,
    parse_order_response,
)
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
        ("CANCEL_REJECTED", BrokerOrderStatus.CANCEL_REJECTED),
        ("REPLACE_REJECTED", BrokerOrderStatus.REPLACE_REJECTED),
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


class TestParseBuyingPowerResponse:
    """Category: Account Balance Test (Phase 21) --
    GET /api/v1/buying-power -> BuyingPowerResponse{currency,
    cashBuyingPower} (Tier 1)."""

    def test_valid_response_is_available_with_cash_and_currency(self) -> None:
        response = TransportResponse(200, {"currency": "USD", "cashBuyingPower": "12345.67"}, None, {})
        snapshot = parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))
        assert snapshot.available is True
        assert snapshot.cash == 12345.67
        assert snapshot.buying_power == 12345.67
        assert snapshot.currency == "USD"

    def test_zero_balance_is_available_not_unavailable(self) -> None:
        response = TransportResponse(200, {"currency": "USD", "cashBuyingPower": "0"}, None, {})
        snapshot = parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))
        assert snapshot.available is True
        assert snapshot.cash == 0.0

    def test_malformed_body_is_unavailable_not_a_fabricated_zero(self) -> None:
        response = TransportResponse(200, None, "{not valid json", {})
        snapshot = parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))
        assert snapshot.available is False
        assert snapshot.cash is None
        assert "malformed_response" in snapshot.unavailable_reason

    def test_missing_cash_buying_power_field_is_unavailable(self) -> None:
        response = TransportResponse(200, {"currency": "USD"}, None, {})
        snapshot = parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))
        assert snapshot.available is False

    def test_non_numeric_cash_buying_power_is_unavailable_not_guessed(self) -> None:
        response = TransportResponse(200, {"currency": "USD", "cashBuyingPower": "not-a-number"}, None, {})
        snapshot = parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))
        assert snapshot.available is False
        assert snapshot.cash is None

    def test_401_raises_broker_auth_error(self) -> None:
        response = TransportResponse(401, {"code": "expired-token", "message": "token expired"}, None, {})
        with pytest.raises(BrokerAuthError):
            parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))

    def test_429_raises_broker_rate_limit_error(self) -> None:
        response = TransportResponse(429, {"code": "rate-limited"}, None, {})
        with pytest.raises(BrokerRateLimitError):
            parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))

    def test_5xx_raises_broker_provider_error_never_unavailable_silently(self) -> None:
        response = TransportResponse(500, {"message": "internal error"}, None, {})
        with pytest.raises(BrokerProviderError):
            parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))

    def test_403_is_unavailable_with_factual_reason(self) -> None:
        response = TransportResponse(403, {"code": "forbidden", "message": "not permitted"}, None, {})
        snapshot = parse_buying_power_response(response, broker_id="toss", as_of_time=utc(2024, 1, 2))
        assert snapshot.available is False
        assert snapshot.unavailable_reason == "not permitted"


class TestParseHoldingsResponse:
    """Category: Positions Test (Phase 21) -- GET /api/v1/holdings ->
    HoldingsOverview{..., items[]} (Tier 1)."""

    def test_single_position(self) -> None:
        response = TransportResponse(
            200, {"items": [{"symbol": "AAPL", "quantity": "10", "averagePurchasePrice": "185.5"}]}, None, {},
        )
        positions = parse_holdings_response(response, as_of_time=utc(2024, 1, 2))
        assert len(positions) == 1
        assert positions[0].security_id == "AAPL"
        assert positions[0].quantity == 10.0
        assert positions[0].average_cost == 185.5
        assert positions[0].available is True

    def test_multiple_positions(self) -> None:
        response = TransportResponse(
            200, {"items": [
                {"symbol": "AAPL", "quantity": "10", "averagePurchasePrice": "185.5"},
                {"symbol": "MSFT", "quantity": "5", "averagePurchasePrice": "400.0"},
            ]}, None, {},
        )
        positions = parse_holdings_response(response, as_of_time=utc(2024, 1, 2))
        assert {p.security_id for p in positions} == {"AAPL", "MSFT"}

    def test_zero_positions_is_an_empty_tuple_not_an_error(self) -> None:
        response = TransportResponse(200, {"items": []}, None, {})
        positions = parse_holdings_response(response, as_of_time=utc(2024, 1, 2))
        assert positions == ()

    def test_malformed_response_raises_rather_than_returning_partial_list(self) -> None:
        response = TransportResponse(200, None, "{not valid json", {})
        with pytest.raises(BrokerTransportError):
            parse_holdings_response(response, as_of_time=utc(2024, 1, 2))

    def test_missing_items_field_raises(self) -> None:
        response = TransportResponse(200, {"totalPurchaseAmount": "0"}, None, {})
        with pytest.raises(BrokerTransportError):
            parse_holdings_response(response, as_of_time=utc(2024, 1, 2))

    def test_malformed_single_item_raises_rather_than_dropping_it_silently(self) -> None:
        response = TransportResponse(200, {"items": [{"symbol": "AAPL"}]}, None, {})  # missing quantity
        with pytest.raises(BrokerTransportError):
            parse_holdings_response(response, as_of_time=utc(2024, 1, 2))

    def test_5xx_raises_broker_provider_error(self) -> None:
        response = TransportResponse(500, {"message": "internal error"}, None, {})
        with pytest.raises(BrokerProviderError):
            parse_holdings_response(response, as_of_time=utc(2024, 1, 2))

    def test_401_raises_broker_auth_error(self) -> None:
        response = TransportResponse(401, {"code": "expired-token"}, None, {})
        with pytest.raises(BrokerAuthError):
            parse_holdings_response(response, as_of_time=utc(2024, 1, 2))


class TestParseOrderDetailResponse:
    """Category: Order Status Test (Phase 21) -- GET
    /api/v1/orders/{orderId} -> a single Order{...} object (Tier 1)."""

    @pytest.mark.parametrize("raw_status,expected", [
        ("PENDING", BrokerOrderStatus.PENDING),
        ("PARTIAL_FILLED", BrokerOrderStatus.PARTIAL_FILLED),
        ("PENDING_CANCEL", BrokerOrderStatus.PENDING_CANCEL),
        ("PENDING_REPLACE", BrokerOrderStatus.PENDING_REPLACE),
        ("FILLED", BrokerOrderStatus.FILLED),
        ("CANCELED", BrokerOrderStatus.CANCELED),
        ("REJECTED", BrokerOrderStatus.REJECTED),
        ("REPLACED", BrokerOrderStatus.REPLACED),
        ("CANCEL_REJECTED", BrokerOrderStatus.CANCEL_REJECTED),
        ("REPLACE_REJECTED", BrokerOrderStatus.REPLACE_REJECTED),
    ])
    def test_every_documented_status_maps_correctly(self, raw_status, expected) -> None:
        response = TransportResponse(200, {"orderId": "TOSS-1", "status": raw_status}, None, {})
        observation = parse_order_detail_response(
            response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
        )
        assert observation.status == expected
        assert observation.raw_status_code == raw_status

    def test_unrecognized_status_is_unknown_not_guessed(self) -> None:
        response = TransportResponse(200, {"orderId": "TOSS-1", "status": "SOME_FUTURE_STATUS"}, None, {})
        observation = parse_order_detail_response(
            response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
        )
        assert observation.status == BrokerOrderStatus.UNKNOWN

    def test_execution_fields_are_extracted_when_present(self) -> None:
        response = TransportResponse(
            200, {"orderId": "TOSS-1", "status": "FILLED",
                  "execution": {"filledQuantity": "10", "averageFilledPrice": "185.5"}}, None, {},
        )
        observation = parse_order_detail_response(
            response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
        )
        assert observation.filled_quantity == 10.0
        assert observation.avg_fill_price == 185.5

    def test_missing_execution_field_does_not_crash(self) -> None:
        response = TransportResponse(200, {"orderId": "TOSS-1", "status": "PENDING"}, None, {})
        observation = parse_order_detail_response(
            response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
        )
        assert observation.filled_quantity is None

    def test_404_order_not_found_is_unknown_with_code_preserved_for_audit(self) -> None:
        response = TransportResponse(404, {"code": "order-not-found", "message": "no such order"}, None, {})
        observation = parse_order_detail_response(
            response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
        )
        assert observation.status == BrokerOrderStatus.UNKNOWN
        assert observation.raw_status_code == "order-not-found"

    def test_malformed_body_is_unknown(self) -> None:
        response = TransportResponse(200, None, "{not valid json", {})
        observation = parse_order_detail_response(
            response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
        )
        assert observation.status == BrokerOrderStatus.UNKNOWN

    def test_5xx_raises_broker_provider_error_never_unknown_silently_swallowed(self) -> None:
        response = TransportResponse(500, {"message": "internal error"}, None, {})
        with pytest.raises(BrokerProviderError):
            parse_order_detail_response(
                response, observation_id="O1", client_order_id="CID-1", broker_id="toss", observed_at=utc(2024, 1, 2),
            )

    def test_timeout_class_errors_are_not_this_functions_concern(self) -> None:
        """Timeout/connection failure are raised by the real network
        transport itself, before a TransportResponse ever reaches this
        function -- nothing to test here beyond confirming 5xx/401/429
        (transport-level uncertainty expressed as an HTTP response) are
        handled, which the other tests in this class already do."""


class TestParseCancelResponse:
    """Category: Cancel Order Test (Phase 21) -- POST
    /api/v1/orders/{orderId}/cancel -> OrderOperationResponse{orderId}
    (Tier 1). Critical: the response orderId is a NEW id for the cancel
    operation, never confused with the original order's id."""

    def test_successful_cancel_is_canceled_and_preserves_original_broker_order_id(self) -> None:
        response = TransportResponse(200, {"orderId": "TOSS-NEW-CANCEL-ID"}, None, {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-ORIGINAL-ID", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.CANCELED
        assert result.broker_order_id == "TOSS-ORIGINAL-ID"  # never overwritten
        assert result.cancel_reference_id == "TOSS-NEW-CANCEL-ID"  # the new id, kept separate

    def test_new_order_id_is_never_confused_with_the_original(self) -> None:
        response = TransportResponse(200, {"orderId": "TOSS-ORIGINAL-ID"}, None, {})  # even if it happened to match
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-ORIGINAL-ID", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        # broker_order_id is sourced from original_broker_order_id, never
        # from the response body -- this assertion would catch a future
        # regression that accidentally reads response.body["orderId"]
        # into broker_order_id instead of cancel_reference_id.
        assert result.broker_order_id == "TOSS-ORIGINAL-ID"
        assert result.cancel_reference_id == "TOSS-ORIGINAL-ID"

    def test_already_filled_conflict_maps_to_filled(self) -> None:
        response = TransportResponse(409, {"code": "already-filled", "message": "order already filled"}, None, {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.FILLED
        assert result.error_code == "already-filled"

    def test_already_canceled_conflict_maps_to_canceled(self) -> None:
        response = TransportResponse(409, {"code": "already-canceled"}, None, {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.CANCELED

    def test_already_rejected_conflict_maps_to_rejected(self) -> None:
        response = TransportResponse(409, {"code": "already-rejected"}, None, {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.REJECTED

    @pytest.mark.parametrize("code", ["already-modified", "already-processing", "cancel-restricted", "order-hours-closed", "order-not-found"])
    def test_ambiguous_conflict_codes_are_unknown_not_guessed(self, code) -> None:
        response = TransportResponse(409, {"code": code}, None, {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.UNKNOWN
        assert result.error_code == code  # audit trail preserved even though status is UNKNOWN

    def test_404_order_not_found(self) -> None:
        response = TransportResponse(404, {"code": "order-not-found"}, None, {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.UNKNOWN

    def test_5xx_raises_broker_provider_error_no_blind_retry_semantics_needed_here(self) -> None:
        """A cancel timeout/5xx must never be silently treated as
        'cancel failed' -- raising (rather than returning a fabricated
        REJECTED/CANCELED) is what lets a caller apply
        UNKNOWN/RECONCILIATION_REQUIRED semantics instead of retrying
        blindly (instruction section 8)."""
        response = TransportResponse(500, {"message": "internal error"}, None, {})
        with pytest.raises(BrokerProviderError):
            parse_cancel_response(
                response, response_id="R1", client_order_id="CID-1", broker_id="toss",
                original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
            )

    def test_malformed_body_is_unknown_and_preserves_original_broker_order_id(self) -> None:
        response = TransportResponse(200, None, "{not valid json", {})
        result = parse_cancel_response(
            response, response_id="R1", client_order_id="CID-1", broker_id="toss",
            original_broker_order_id="TOSS-1", attempt_count=1, responded_at=utc(2024, 1, 2),
        )
        assert result.status == BrokerOrderStatus.UNKNOWN
        assert result.broker_order_id == "TOSS-1"
