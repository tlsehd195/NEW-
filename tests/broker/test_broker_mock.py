"""Category: Mock Broker / Fail-Closed / Idempotency / Account-Position
Read Test -- `MockBrokerAdapter` proves the full `BrokerAdapter`
Protocol offline, deterministically, including every fail-closed
scenario instruction section 11 requires."""

from __future__ import annotations

import pytest
from broker_helpers import make_broker_config, make_risk_checked_position, utc

from broker.enums import BrokerCapability, BrokerOrderStatus, CapabilityStatus
from broker.errors import BrokerTransportError
from broker.mock import MockBrokerAdapter
from broker.validation import build_validated_order


def _validated_order(**overrides):
    current_quantity = overrides.pop("current_quantity", 0.0)
    rcp = make_risk_checked_position(**overrides)
    result = build_validated_order(rcp, current_quantity=current_quantity, configuration_version="cfg-v1")
    assert result.validated_order is not None
    return result.validated_order


class TestSubmitOrderHappyPath:
    def test_market_order_fills_immediately(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config())
        response = broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        assert response.status == BrokerOrderStatus.FILLED
        assert response.broker_order_id is not None
        assert response.filled_quantity == order.quantity

    def test_positions_and_account_reflect_the_fill(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config(), initial_cash=100_000.0, fill_price=100.0)
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        positions = broker.get_positions(as_of=utc(2024, 1, 2, 14))
        assert positions[0].security_id == order.security_id
        assert positions[0].quantity == order.quantity
        account = broker.get_account(as_of=utc(2024, 1, 2, 14))
        assert account.cash == 100_000.0 - order.quantity * 100.0


class TestIdempotency:
    def test_resubmitting_the_same_client_order_id_does_not_duplicate(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config())
        r1 = broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        r2 = broker.submit_order(order, requested_at=utc(2024, 1, 2, 14))
        assert r1.response_id == r2.response_id
        positions = broker.get_positions(as_of=utc(2024, 1, 2, 15))
        assert positions[0].quantity == order.quantity  # not doubled


class TestCancelOrder:
    def test_cancel_unknown_client_order_id_is_unknown_status(self) -> None:
        broker = MockBrokerAdapter(make_broker_config())
        response = broker.cancel_order("CID-never-submitted", requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN
        assert response.error_code == "unknown_client_order_id"

    def test_cancel_already_filled_order_is_rejected_honestly(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config())
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        response = broker.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2, 14))
        assert response.status == BrokerOrderStatus.REJECTED
        assert response.error_code == "already_filled"


class TestOrderStatus:
    def test_status_of_never_submitted_order_is_unknown(self) -> None:
        broker = MockBrokerAdapter(make_broker_config())
        observation = broker.get_order_status("CID-never-submitted", as_of=utc(2024, 1, 2))
        assert observation.status == BrokerOrderStatus.UNKNOWN

    def test_status_after_submission_is_filled(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config())
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        observation = broker.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2, 14))
        assert observation.status == BrokerOrderStatus.FILLED

    def test_status_unknown_failure_mode_never_reports_a_concrete_status(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="status_unknown")
        broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))
        observation = broker.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2, 14))
        assert observation.status == BrokerOrderStatus.UNKNOWN


class TestFailClosedTransportUnavailable:
    def test_unavailable_broker_raises_on_submit(self) -> None:
        order = _validated_order(final_target_quantity=40.0, current_quantity=0.0)
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="unavailable")
        with pytest.raises(BrokerTransportError):
            broker.submit_order(order, requested_at=utc(2024, 1, 2, 13))

    def test_unavailable_broker_raises_on_every_operation(self) -> None:
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="unavailable")
        with pytest.raises(BrokerTransportError):
            broker.get_account(as_of=utc(2024, 1, 2))
        with pytest.raises(BrokerTransportError):
            broker.get_positions(as_of=utc(2024, 1, 2))
        with pytest.raises(BrokerTransportError):
            broker.get_order_status("CID-x", as_of=utc(2024, 1, 2))
        with pytest.raises(BrokerTransportError):
            broker.cancel_order("CID-x", requested_at=utc(2024, 1, 2))


class TestAccountUnavailablePreservesUnknown:
    def test_account_unavailable_is_never_reported_as_zero(self) -> None:
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="account_unavailable")
        account = broker.get_account(as_of=utc(2024, 1, 2))
        assert account.available is False
        assert account.cash is None  # never fabricated as 0.0
        assert account.unavailable_reason is not None

    def test_positions_unavailable_raises_never_a_fabricated_empty_holdings(self) -> None:
        # ADR-0117: an empty tuple here would be indistinguishable from
        # "zero real positions" -- a real caller (e.g. building a
        # PortfolioView) could not tell "we asked and there are none"
        # apart from "we don't actually know." get_positions() has no
        # list-level `available` field the way BrokerAccountSnapshot
        # does, so it must raise instead of silently returning ().
        broker = MockBrokerAdapter(make_broker_config(), failure_mode="account_unavailable")
        with pytest.raises(BrokerTransportError):
            broker.get_positions(as_of=utc(2024, 1, 2))


class TestCapabilities:
    def test_market_order_and_idempotency_enabled(self) -> None:
        broker = MockBrokerAdapter(make_broker_config())
        caps = broker.get_capabilities(as_of=utc(2024, 1, 2))
        assert caps.is_enabled(BrokerCapability.MARKET_ORDER)
        assert caps.is_enabled(BrokerCapability.IDEMPOTENT_CLIENT_ORDER_ID)

    def test_limit_order_and_quote_unsupported(self) -> None:
        broker = MockBrokerAdapter(make_broker_config())
        caps = broker.get_capabilities(as_of=utc(2024, 1, 2))
        assert caps.status_of(BrokerCapability.LIMIT_ORDER) == CapabilityStatus.UNSUPPORTED
        assert caps.status_of(BrokerCapability.QUOTE) == CapabilityStatus.UNSUPPORTED

    def test_undeclared_capability_defaults_to_unknown(self) -> None:
        from broker.capabilities import build_capabilities

        caps = build_capabilities("x", {}, recorded_at=utc(2024, 1, 2))
        assert caps.status_of(BrokerCapability.MARKET_ORDER) == CapabilityStatus.UNKNOWN
