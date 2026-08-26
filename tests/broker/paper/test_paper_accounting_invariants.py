"""Category: Accounting Invariants -- instruction section 33. Cash never
goes negative, positions never go negative (long-only default), filled
quantity never exceeds requested, a cancelled/filled order cannot
receive further fills, UNKNOWN is never treated as FILLED, transaction
costs are never negative, and slippage always moves the price against
the trader."""

from __future__ import annotations

from paper_helpers import make_bar, make_paper_config, make_validated_order, utc

from broker.enums import BrokerOrderStatus
from broker.paper.adapter import PaperBrokerAdapter
from broker.paper.market_data import InMemoryPaperMarketDataSource

from backtest.enums import OrderSide


class TestCashNeverNegative:
    def test_insufficient_cash_rejects_rather_than_overdrawing(self) -> None:
        config = make_paper_config(initial_cash=100.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), close=100.0)])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)  # notional ~1000, far above 100 cash
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.REJECTED
        assert adapter.get_account(as_of=utc(2024, 1, 2)).cash >= 0

    def test_cash_never_negative_across_many_buys(self) -> None:
        config = make_paper_config(initial_cash=10_000.0, max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), close=100.0, volume=1_000_000.0)])
        adapter = PaperBrokerAdapter(config, mds)
        for i in range(20):
            order = make_validated_order(client_order_id=f"CID-{i:03d}", quantity=10.0)
            adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert adapter.get_account(as_of=utc(2024, 1, 2)).cash >= 0


class TestPositionNeverNegativeWithoutShort:
    def test_sell_exceeding_holding_is_rejected(self) -> None:
        config = make_paper_config(allow_short=False)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2))])
        adapter = PaperBrokerAdapter(config, mds)
        sell = make_validated_order(side=OrderSide.SELL, quantity=10.0)
        response = adapter.submit_order(sell, requested_at=utc(2024, 1, 2))
        assert response.status == BrokerOrderStatus.REJECTED
        assert response.error_code == "insufficient_position"
        assert adapter.get_positions(as_of=utc(2024, 1, 2)) == ()


class TestFilledQuantityNeverExceedsRequested:
    def test_filled_quantity_capped_at_requested(self) -> None:
        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        response = adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        assert response.filled_quantity <= order.quantity


class TestTerminalStatesRejectFurtherFills:
    def test_cancelled_order_never_receives_a_later_fill(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([])  # no data -- order stays PENDING
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        adapter.cancel_order(order.client_order_id, requested_at=utc(2024, 1, 2))

        mds.register(make_bar(available_time=utc(2024, 1, 3)))
        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates == ()
        status = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 3))
        assert status.status == BrokerOrderStatus.CANCELED
        assert adapter.get_positions(as_of=utc(2024, 1, 3)) == ()

    def test_filled_order_never_receives_a_later_fill(self) -> None:
        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), volume=1_000_000.0)])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))

        mds.register(make_bar(available_time=utc(2024, 1, 3), volume=1_000_000.0))
        updates = adapter.advance_simulation(utc(2024, 1, 3))
        assert updates == ()
        positions = adapter.get_positions(as_of=utc(2024, 1, 3))
        assert positions[0].quantity == 10.0

    def test_rejected_order_never_receives_a_fill(self) -> None:
        config = make_paper_config(failure_mode="rejected")
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2))])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        updates = adapter.advance_simulation(utc(2024, 1, 2))
        assert updates == ()
        assert adapter.get_positions(as_of=utc(2024, 1, 2)) == ()


class TestUnknownNeverTreatedAsFilled:
    def test_unknown_status_is_never_equal_to_filled(self) -> None:
        config = make_paper_config(failure_mode="unknown_status")
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2))])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        status = adapter.get_order_status(order.client_order_id, as_of=utc(2024, 1, 2))
        assert status.status == BrokerOrderStatus.UNKNOWN
        assert status.status != BrokerOrderStatus.FILLED


class TestCostsNeverNegative:
    def test_commission_spread_slippage_are_non_negative(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2))])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        _, _, fill = adapter.pop_new_fills()[0]
        assert fill.commission >= 0
        assert fill.spread_cost >= 0
        assert fill.slippage_cost >= 0


class TestSlippageDirectionConsistentWithSide:
    def test_buy_execution_price_never_below_reference(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), close=100.0)])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(side=OrderSide.BUY, quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        _, _, fill = adapter.pop_new_fills()[0]
        assert fill.price >= fill.reference_price

    def test_sell_execution_price_never_above_reference(self) -> None:
        config = make_paper_config()
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), close=100.0)])
        adapter = PaperBrokerAdapter(config, mds)
        buy = make_validated_order(client_order_id="CID-B", side=OrderSide.BUY, quantity=10.0)
        adapter.submit_order(buy, requested_at=utc(2024, 1, 2))
        adapter.pop_new_fills()
        sell = make_validated_order(client_order_id="CID-S", side=OrderSide.SELL, quantity=5.0)
        adapter.submit_order(sell, requested_at=utc(2024, 1, 2))
        _, _, fill = adapter.pop_new_fills()[0]
        assert fill.price <= fill.reference_price


class TestEquityEqualsCashPlusMarketValue:
    def test_cost_basis_equity_plus_commission_equals_initial_cash(self) -> None:
        """`cash + cost_basis_value` is short of `initial_cash` by
        exactly the commission paid -- commission is a real expense, not
        represented in `average_cost` (which only reflects
        price/slippage/spread, matching `backtest.portfolio.
        PortfolioAccounting.apply_fill`'s own convention, Phase 2)."""
        config = make_paper_config(max_participation=1.0)
        mds = InMemoryPaperMarketDataSource([make_bar(available_time=utc(2024, 1, 2), close=100.0, volume=1_000_000.0)])
        adapter = PaperBrokerAdapter(config, mds)
        order = make_validated_order(quantity=10.0)
        adapter.submit_order(order, requested_at=utc(2024, 1, 2))
        _, _, fill = adapter.pop_new_fills()[0]

        account = adapter.get_account(as_of=utc(2024, 1, 2))
        positions = adapter.get_positions(as_of=utc(2024, 1, 2))
        cost_basis_value = sum(p.quantity * p.average_cost for p in positions)
        assert abs((account.cash + cost_basis_value + fill.commission) - config.initial_cash) < 1e-6
