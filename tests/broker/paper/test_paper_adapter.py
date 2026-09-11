"""Category: Unit Test -- order lifecycle, fill calculation, partial
fill, idempotency, failure modes, cash/position accounting for
`PaperBrokerAdapter`."""

from __future__ import annotations

import pytest

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.enums import BrokerOrderStatus
from broker.errors import BrokerAuthError, BrokerRateLimitError, BrokerTimeoutError, BrokerTransportError
from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.market_data import InMemoryPaperMarketDataSource

from backtest.enums import OrderSide


def _adapter(config=None, bars=()):
    config = config or make_paper_config()
    mds = InMemoryPaperMarketDataSource(list(bars))
    return PaperBrokerAdapter(config, mds), mds


class TestGetAccountCurrency:
    def test_paper_account_currency_is_usd_not_krw(self) -> None:
        # ADR-0117: Paper accounting is natively USD-denominated
        # (PortfolioAccounting/PriceBar price exclusively in USD,
        # ADR-0025/ADR-0026 -- see broker.paper.us_longterm_config's own
        # docstring) -- get_account used to hardcode currency="KRW",
        # mislabeling every real Paper account snapshot's currency.
        adapter, _ = _adapter()
        account = adapter.get_account(as_of=utc(2024, 1, 2))
        assert account.currency == "USD"


class TestNormalFill:
    def test_market_order_fills_against_reference_bar(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED
        assert response.filled_quantity == 10.0
        assert response.avg_fill_price is not None and response.avg_fill_price > 100.0  # BUY pays through spread+slippage

    def test_sell_price_is_below_reference(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        buy = make_validated_order(client_order_id="CID-B", side=OrderSide.BUY, quantity=10.0)
        adapter.submit_order(buy, requested_at=utc(2024, 1, 2))
        sell = make_validated_order(client_order_id="CID-S", side=OrderSide.SELL, quantity=5.0)
        response = adapter.submit_order(sell, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED
        assert response.avg_fill_price < 100.0


class TestPartialFill:
    def test_low_volume_bar_produces_partial_fill_then_completes(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10),
            bars=[make_bar(timestamp=utc(2024, 1, 2), available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        order = make_validated_order(quantity=250.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PARTIAL_FILLED
        assert response.filled_quantity == 100.0

        mds.register(make_bar(timestamp=utc(2024, 1, 3), available_time=utc(2024, 1, 3), volume=1_000.0))
        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates[-1].status == BrokerOrderStatus.PARTIAL_FILLED
        assert updates[-1].filled_quantity == 200.0

        mds.register(make_bar(timestamp=utc(2024, 1, 4), available_time=utc(2024, 1, 4), volume=1_000.0))
        updates2 = adapter.advance_simulation(utc(2024, 1, 4))
        assert updates2[-1].status == BrokerOrderStatus.FILLED
        assert updates2[-1].filled_quantity == 250.0

    def test_partial_fill_disabled_fills_nothing_until_full_liquidity(self) -> None:
        adapter, mds = _adapter(
            config=make_paper_config(max_participation=0.10, partial_fill_enabled=False),
            bars=[make_bar(available_time=utc(2024, 1, 2), volume=1_000.0)],
        )
        order = make_validated_order(quantity=250.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING
        assert response.filled_quantity is None

    def test_no_data_available_keeps_order_pending(self) -> None:
        adapter, _ = _adapter(bars=[])
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.PENDING
        assert response.filled_quantity is None


class TestIdempotency:
    def test_duplicate_submission_returns_same_logical_order(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        r1 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        r2 = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert r1.status == r2.status == BrokerOrderStatus.FILLED
        assert r1.filled_quantity == r2.filled_quantity
        # no double fill -- position reflects exactly one fill of 10 shares
        positions = adapter.get_positions(as_of=utc(2024, 1, 2))
        assert positions[0].quantity == 10.0


class TestCancellation:
    def test_cancel_open_order(self) -> None:
        adapter, _ = _adapter(bars=[])  # no data -- stays PENDING
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        response = adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.CANCELED
        status = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.CANCELED

    def test_cannot_cancel_filled_order(self) -> None:
        adapter, _ = _adapter(bars=[make_bar(available_time=utc(2024, 1, 2))])
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        response = adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED
        assert response.error_code == "already_filled"

    def test_cancel_unknown_order_id(self) -> None:
        adapter, _ = _adapter(bars=[])
        response = adapter.cancel_order("CID-NEVER-SUBMITTED", requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN


class TestFailureModes:
    def test_rejected_mode_rejects_new_orders(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="rejected"), bars=[make_bar(available_time=utc(2024, 1, 2))])
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.REJECTED
        assert response.error_code == "simulated_rejection"

    def test_timeout_mode_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="timeout"))
        with pytest.raises(BrokerTimeoutError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))

    def test_auth_mode_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="auth"))
        with pytest.raises(BrokerAuthError):
            adapter.get_account(as_of=utc(2024, 1, 2))

    def test_rate_limit_mode_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="rate_limit"))
        with pytest.raises(BrokerRateLimitError):
            adapter.get_positions(as_of=utc(2024, 1, 2))

    def test_unavailable_mode_raises_on_every_call(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="unavailable"))
        with pytest.raises(BrokerTransportError):
            adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        with pytest.raises(BrokerTransportError):
            adapter.get_account(as_of=utc(2024, 1, 2))

    def test_malformed_mode_returns_unknown_never_raises(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="malformed"), bars=[make_bar(available_time=utc(2024, 1, 2))])
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.UNKNOWN
        assert response.error_code == "malformed_response"
        # no fill was ever applied
        assert adapter.get_positions(as_of=utc(2024, 1, 2)) == ()

    def test_unknown_status_mode_never_confirms_fill_via_status_query(self) -> None:
        adapter, _ = _adapter(config=make_paper_config(failure_mode="unknown_status"), bars=[make_bar(available_time=utc(2024, 1, 2))])
        response = adapter.submit_order(make_validated_order(), requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.FILLED  # submission itself succeeds
        status = adapter.get_order_status("CID-000001", as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.UNKNOWN  # but status queries cannot confirm it
        assert status.status != BrokerOrderStatus.FILLED


class TestCapabilities:
    def test_capabilities_do_not_claim_limit_order_support(self) -> None:
        adapter, _ = _adapter()
        capabilities = adapter.get_capabilities(as_of=utc(2024, 1, 2))
        from broker.enums import BrokerCapability, CapabilityStatus

        assert capabilities.status_of(BrokerCapability.LIMIT_ORDER) == CapabilityStatus.UNSUPPORTED
        assert capabilities.is_enabled(BrokerCapability.MARKET_ORDER)
