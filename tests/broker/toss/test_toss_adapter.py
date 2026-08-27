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
from broker.transport import MockTransport, TransportResponse
from broker.toss.adapter import TossBrokerAdapter
from broker.toss.endpoints import (
    BUYING_POWER_PATH,
    CANCEL_ORDER_PATH_TEMPLATE,
    CREATE_ORDER_PATH,
    HOLDINGS_PATH,
    ORDER_DETAIL_PATH_TEMPLATE,
    TOKEN_PATH,
)
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


class _StubTransport:
    """A general-purpose routing stub for Phase 21's adapter-level
    tests -- always answers TOKEN_PATH, and dispatches every other
    GET/POST to a caller-supplied response keyed by exact path. Never
    reaches the network."""

    def __init__(self) -> None:
        self._get_responses: dict[str, TransportResponse] = {}
        self._post_responses: dict[str, TransportResponse] = {}
        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []

    def when_get(self, path: str, response: TransportResponse) -> "_StubTransport":
        self._get_responses[path] = response
        return self

    def when_post(self, path: str, response: TransportResponse) -> "_StubTransport":
        self._post_responses[path] = response
        return self

    def get(self, path, *, headers, params, timeout):
        self.get_calls.append((path, dict(params)))
        if path not in self._get_responses:
            raise AssertionError(f"_StubTransport: no GET response registered for {path!r}")
        return self._get_responses[path]

    def post(self, path, *, headers, json_body, timeout):
        self.post_calls.append((path, dict(json_body)))
        if path == TOKEN_PATH:
            return TransportResponse(200, {"access_token": "tok-abc123"}, None, {})
        if path not in self._post_responses:
            raise AssertionError(f"_StubTransport: no POST response registered for {path!r}")
        return self._post_responses[path]


def _set_toss_env(monkeypatch) -> None:
    monkeypatch.setenv("TOSS_API_KEY", "k")
    monkeypatch.setenv("TOSS_API_SECRET", "s")
    monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")


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


class TestGetAccount:
    """Category: Account Balance Test (Phase 21) --
    TossBrokerAdapter.get_account() against BUYING_POWER_PATH."""

    def test_successful_balance_query(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(
            BUYING_POWER_PATH, TransportResponse(200, {"currency": "USD", "cashBuyingPower": "50000.0"}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)
        snapshot = adapter.get_account(as_of=utc(2024, 1, 2))
        assert snapshot.available is True
        assert snapshot.cash == 50000.0
        assert snapshot.currency == "USD"
        # the currency query param requested is USD -- this system is
        # US-equity-only (ADR-0025/ADR-0026), never KRW (see
        # docs/operations/MARKET-DATA-FX-REFERENCE.md)
        assert transport.get_calls[0][1]["currency"] == "USD"

    def test_zero_balance_query(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(
            BUYING_POWER_PATH, TransportResponse(200, {"currency": "USD", "cashBuyingPower": "0"}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)
        snapshot = adapter.get_account(as_of=utc(2024, 1, 2))
        assert snapshot.available is True
        assert snapshot.cash == 0.0

    def test_unavailable_via_5xx_raises_never_a_fabricated_snapshot(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(BUYING_POWER_PATH, TransportResponse(500, {"message": "down"}, None, {}))
        adapter = TossBrokerAdapter(_live_config(), transport)
        from broker.errors import BrokerProviderError

        with pytest.raises(BrokerProviderError):
            adapter.get_account(as_of=utc(2024, 1, 2))

    def test_malformed_response_is_available_false(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(BUYING_POWER_PATH, TransportResponse(200, None, "not json", {}))
        adapter = TossBrokerAdapter(_live_config(), transport)
        snapshot = adapter.get_account(as_of=utc(2024, 1, 2))
        assert snapshot.available is False
        assert snapshot.cash is None


class TestGetPositions:
    """Category: Positions Test (Phase 21) --
    TossBrokerAdapter.get_positions() against HOLDINGS_PATH."""

    def test_multiple_positions(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(
            HOLDINGS_PATH,
            TransportResponse(200, {"items": [
                {"symbol": "AAPL", "quantity": "10", "averagePurchasePrice": "185.5"},
                {"symbol": "MSFT", "quantity": "3", "averagePurchasePrice": "400.0"},
            ]}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)
        positions = adapter.get_positions(as_of=utc(2024, 1, 2))
        assert {p.security_id for p in positions} == {"AAPL", "MSFT"}

    def test_zero_positions_is_empty_tuple(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(HOLDINGS_PATH, TransportResponse(200, {"items": []}, None, {}))
        adapter = TossBrokerAdapter(_live_config(), transport)
        assert adapter.get_positions(as_of=utc(2024, 1, 2)) == ()

    def test_5xx_raises_never_silently_returns_empty_tuple(self, monkeypatch) -> None:
        """The known ambiguity between "zero positions" and "positions
        unavailable" both being () (instruction section 7) means a real
        failure must never also collapse to () -- it must raise, so at
        least an exception distinguishes it from a genuine empty
        holdings response."""
        _set_toss_env(monkeypatch)
        transport = _StubTransport().when_get(HOLDINGS_PATH, TransportResponse(500, {"message": "down"}, None, {}))
        adapter = TossBrokerAdapter(_live_config(), transport)
        from broker.errors import BrokerProviderError

        with pytest.raises(BrokerProviderError):
            adapter.get_positions(as_of=utc(2024, 1, 2))


class TestGetOrderStatus:
    """Category: Order Status Test (Phase 21) --
    TossBrokerAdapter.get_order_status() against
    ORDER_DETAIL_PATH_TEMPLATE, keyed by the broker_order_id learned
    from a prior submit_order call (client_order_id -> orderId is not a
    documented Toss query parameter -- see the adapter's
    _order_id_map docstring)."""

    def test_never_submitted_client_order_id_is_unknown_not_guessed(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        adapter = TossBrokerAdapter(_live_config(), _StubTransport())
        observation = adapter.get_order_status("CID-NEVER-SUBMITTED", as_of=utc(2024, 1, 2))
        assert observation.status == BrokerOrderStatus.UNKNOWN
        assert observation.broker_order_id is None

    def test_status_query_after_submit_uses_the_learned_broker_order_id(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "PENDING", "orderId": "TOSS-1"}, None, {}))
        transport.when_get(
            ORDER_DETAIL_PATH_TEMPLATE.format(order_id="TOSS-1"),
            TransportResponse(200, {"orderId": "TOSS-1", "status": "FILLED",
                                     "execution": {"filledQuantity": "40", "averageFilledPrice": "100.0"}}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)
        adapter.submit_order(_order(), requested_at=utc(2024, 1, 2))

        observation = adapter.get_order_status(_order().client_order_id, as_of=utc(2024, 1, 3))
        assert observation.status == BrokerOrderStatus.FILLED
        assert observation.broker_order_id == "TOSS-1"
        assert observation.filled_quantity == 40.0


class TestCancelOrder:
    """Category: Cancel Order Test (Phase 21) --
    TossBrokerAdapter.cancel_order() against
    CANCEL_ORDER_PATH_TEMPLATE."""

    def test_never_submitted_client_order_id_is_unknown_no_blind_call(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport()
        adapter = TossBrokerAdapter(_live_config(), transport)
        response = adapter.cancel_order("CID-NEVER-SUBMITTED", requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN
        assert response.error_code == "unknown_client_order_id"
        assert transport.post_calls == []  # no blind call against a guessed orderId

    def test_successful_cancel_after_submit(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "PENDING", "orderId": "TOSS-1"}, None, {}))
        transport.when_post(
            CANCEL_ORDER_PATH_TEMPLATE.format(order_id="TOSS-1"),
            TransportResponse(200, {"orderId": "TOSS-NEW-CANCEL-ID"}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)
        order = _order()
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))

        response = adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 3))
        assert response.status == BrokerOrderStatus.CANCELED
        assert response.broker_order_id == "TOSS-1"  # the original order's id, unchanged
        assert response.cancel_reference_id == "TOSS-NEW-CANCEL-ID"  # the new id, kept separate

    def test_double_cancel_is_safe_second_call_reports_the_same_conflict_outcome(self, monkeypatch) -> None:
        """No client-side cancel dedup exists in TossBrokerAdapter --
        each cancel_order call always re-issues a POST when a
        broker_order_id is known. This is safe because Toss's own API
        is idempotent by construction here: cancelling an
        already-cancelled order returns a 409 already-canceled
        conflict, which parse_cancel_response already maps to a
        definitive CANCELED status (not a duplicate action, not an
        error) -- see _CANCEL_CONFLICT_STATUS_MAP."""
        _set_toss_env(monkeypatch)
        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "PENDING", "orderId": "TOSS-1"}, None, {}))
        transport.when_post(
            CANCEL_ORDER_PATH_TEMPLATE.format(order_id="TOSS-1"),
            TransportResponse(409, {"code": "already-canceled"}, None, {}),
        )
        adapter = TossBrokerAdapter(_live_config(), transport)
        order = _order()
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 3))
        second = adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 4))
        assert second.status == BrokerOrderStatus.CANCELED

    def test_cancel_5xx_raises_no_blind_retry(self, monkeypatch) -> None:
        _set_toss_env(monkeypatch)
        transport = _StubTransport()
        transport.when_post(CREATE_ORDER_PATH, TransportResponse(200, {"status": "PENDING", "orderId": "TOSS-1"}, None, {}))
        transport.when_post(CANCEL_ORDER_PATH_TEMPLATE.format(order_id="TOSS-1"), TransportResponse(500, {"message": "down"}, None, {}))
        adapter = TossBrokerAdapter(_live_config(), transport)
        order = _order()
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))

        from broker.errors import BrokerProviderError

        with pytest.raises(BrokerProviderError):
            adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 3))
        assert transport.post_calls.count((CANCEL_ORDER_PATH_TEMPLATE.format(order_id="TOSS-1"), {})) == 1  # not retried


class TestCapabilities:
    def test_market_order_enabled_others_still_unknown_even_though_implemented(self, monkeypatch) -> None:
        """Phase 21: cancel_order/get_order_status/get_account/
        get_positions are all implemented in code now, but
        get_capabilities() must still report UNKNOWN for them -- code
        existing is not the same as operational verification against a
        real account (instruction section 11, 26). Flipping these to
        ENABLED without that verification would silently change
        evaluate_safety_gate's behavior, which this phase must not do."""
        adapter = self._adapter_for_capabilities(monkeypatch)
        caps = adapter.get_capabilities(as_of=utc(2024, 1, 2))
        assert caps.status_of(BrokerCapability.MARKET_ORDER) == CapabilityStatus.ENABLED
        assert caps.status_of(BrokerCapability.CANCEL_ORDER) == CapabilityStatus.UNKNOWN
        assert caps.status_of(BrokerCapability.ORDER_STATUS) == CapabilityStatus.UNKNOWN
        assert caps.status_of(BrokerCapability.ACCOUNT_BALANCE) == CapabilityStatus.UNKNOWN
        assert caps.status_of(BrokerCapability.POSITIONS) == CapabilityStatus.UNKNOWN

    def _adapter_for_capabilities(self, monkeypatch) -> TossBrokerAdapter:
        _set_toss_env(monkeypatch)
        return TossBrokerAdapter(_live_config(), MockTransport())
