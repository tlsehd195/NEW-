"""Category: Toss Adapter Test -- `TossBrokerAdapter` requires
`BrokerExecutionMode.LIVE` at construction, only implements
`submit_order` against the one confirmed endpoint, and declares every
unconfirmed operation `CapabilityStatus.UNKNOWN`/raises
`BrokerCapabilityError` rather than guessing a path. Always uses
`MockTransport` -- never the real network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from broker_helpers import make_risk_checked_position

from broker.config import BrokerConfig
from broker.enums import BrokerCapability, BrokerExecutionMode, BrokerOrderStatus, CapabilityStatus
from broker.errors import BrokerCapabilityError
from broker.transport import MockTransport, TransportResponse
from broker.toss.adapter import TossBrokerAdapter
from broker.toss.endpoints import CREATE_ORDER_PATH, TOKEN_PATH
from broker.validation import build_validated_order


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _live_config(**overrides) -> BrokerConfig:
    fields = dict(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)
    fields.update(overrides)
    return BrokerConfig(**fields)


def _order():
    rcp = make_risk_checked_position(final_target_quantity=40.0)
    return build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1").validated_order


class _RoutingTransport:
    """Returns a different response depending on which path is called
    -- `TossAuthClient.fetch_access_token()` calls `TOKEN_PATH` before
    `TossBrokerAdapter.submit_order` calls `CREATE_ORDER_PATH`, so a
    single fixed `response_body` (as `MockTransport` provides) cannot
    exercise both in one test."""

    def __init__(self, *, order_response_body: dict) -> None:
        self._order_response_body = order_response_body
        self.call_count = 0

    def post(self, path, *, headers, json_body, timeout):
        self.call_count += 1
        if path == TOKEN_PATH:
            return TransportResponse(200, {"access_token": "tok-abc123"}, None, {})
        assert path == CREATE_ORDER_PATH
        return TransportResponse(200, self._order_response_body, None, {})

    def get(self, path, *, headers, params, timeout):
        raise NotImplementedError


class TestConstructionRequiresLiveMode:
    def test_offline_config_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            TossBrokerAdapter(BrokerConfig(), MockTransport())

    def test_live_config_is_accepted(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        adapter = TossBrokerAdapter(_live_config(), MockTransport())
        assert adapter.broker_id == "mock-broker"


class TestSubmitOrder:
    def test_successful_submission(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        transport = _RoutingTransport(order_response_body={"status": "FILLED", "orderId": "TOSS-1"})
        adapter = TossBrokerAdapter(_live_config(), transport)
        response = adapter.submit_order(_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED
        assert response.broker_order_id == "TOSS-1"

    def test_missing_credentials_raises_before_transport_call(self, monkeypatch) -> None:
        monkeypatch.delenv("TOSS_API_KEY", raising=False)
        monkeypatch.delenv("TOSS_API_SECRET", raising=False)
        monkeypatch.delenv("TOSS_ACCOUNT_ID", raising=False)
        transport = MockTransport()
        adapter = TossBrokerAdapter(_live_config(), transport)
        from broker.errors import BrokerAuthError

        with pytest.raises(BrokerAuthError):
            adapter.submit_order(_order(), requested_at=utc(2024, 1, 2))
        assert transport.call_count == 0


class TestUnsupportedOperations:
    def _adapter(self, monkeypatch) -> TossBrokerAdapter:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        return TossBrokerAdapter(_live_config(), MockTransport())

    def test_cancel_order_is_unsupported(self, monkeypatch) -> None:
        adapter = self._adapter(monkeypatch)
        with pytest.raises(BrokerCapabilityError):
            adapter.cancel_order("CID-1", requested_at=utc(2024, 1, 2))

    def test_get_order_status_is_unsupported(self, monkeypatch) -> None:
        adapter = self._adapter(monkeypatch)
        with pytest.raises(BrokerCapabilityError):
            adapter.get_order_status("CID-1", as_of=utc(2024, 1, 2))

    def test_get_account_is_unsupported(self, monkeypatch) -> None:
        adapter = self._adapter(monkeypatch)
        with pytest.raises(BrokerCapabilityError):
            adapter.get_account(as_of=utc(2024, 1, 2))

    def test_get_positions_is_unsupported(self, monkeypatch) -> None:
        adapter = self._adapter(monkeypatch)
        with pytest.raises(BrokerCapabilityError):
            adapter.get_positions(as_of=utc(2024, 1, 2))


class TestCapabilities:
    def test_market_order_enabled_cancel_unknown(self, monkeypatch) -> None:
        adapter = self._adapter_for_capabilities(monkeypatch)
        caps = adapter.get_capabilities(as_of=utc(2024, 1, 2))
        assert caps.status_of(BrokerCapability.MARKET_ORDER) == CapabilityStatus.ENABLED
        assert caps.status_of(BrokerCapability.CANCEL_ORDER) == CapabilityStatus.UNKNOWN
        assert caps.status_of(BrokerCapability.ORDER_STATUS) == CapabilityStatus.UNKNOWN
        assert caps.status_of(BrokerCapability.ACCOUNT_BALANCE) == CapabilityStatus.UNKNOWN

    def _adapter_for_capabilities(self, monkeypatch) -> TossBrokerAdapter:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        return TossBrokerAdapter(_live_config(), MockTransport())
