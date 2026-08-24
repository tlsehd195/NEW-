"""Category: Trade creation.
Category: Immutable snapshot (TradeRecord).
Category: Order/fill linkage.
Category: Partial fill.
Category: Rejected order.
Category: Cancelled order.
Category: Realized PnL.
Category: Holding period.

See docs/specifications/PHASE-3-trade-journal.md sections 5.3, 12.
"""

from __future__ import annotations

import dataclasses

import pytest
from journal_helpers import make_fill, make_order, utc

from backtest.enums import OrderSide, OrderStatus
from trade_journal.enums import DecisionAction
from trade_journal.repository import InMemoryTradeJournalRepository


class TestTradeCreation:
    def test_record_trade_populates_fields_from_fill(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(
            decision_time=utc(2024, 1, 2), security_id="AAA", decision=DecisionAction.BUY, order=make_order(),
        )
        fill = make_fill()
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=10.0)

        assert trade.trade_id.startswith("TRD-")
        assert trade.decision_id == decision.snapshot_id
        assert trade.order_id == fill.order_id
        assert trade.security_id == "AAA"
        assert trade.side == OrderSide.BUY
        assert trade.quantity == 10.0
        assert trade.execution_price == fill.price
        assert trade.reference_price == fill.reference_price
        assert trade.slippage == fill.slippage_cost
        assert trade.transaction_cost == fill.total_cost
        assert trade.position_after == 10.0
        assert trade.fill is fill

    def test_trade_ids_are_monotonic(self) -> None:
        journal = InMemoryTradeJournalRepository()
        d1 = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                      decision=DecisionAction.BUY, order=make_order(order_id="ORD-A"))
        d2 = journal.record_decision(decision_time=utc(2024, 1, 3), security_id="BBB",
                                      decision=DecisionAction.BUY, order=make_order(order_id="ORD-B"))
        t1 = journal.record_trade(decision_id=d1.snapshot_id, fill=make_fill(order_id="ORD-A"), position_after=10)
        t2 = journal.record_trade(decision_id=d2.snapshot_id, fill=make_fill(order_id="ORD-B", security_id="BBB"),
                                   position_after=5)
        assert t1.trade_id == "TRD-000001"
        assert t2.trade_id == "TRD-000002"


class TestImmutableTradeRecord:
    def test_trade_record_is_frozen(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            trade.execution_price = 0.0  # type: ignore[misc]


class TestOrderFillLinkage:
    def test_trade_links_back_to_its_decision(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)

        relinked = journal.get_decision(trade.decision_id)
        assert relinked is decision
        assert relinked.order.order_id == trade.order_id


class TestPartialFill:
    def test_partial_fill_produces_correctly_sized_trade(self) -> None:
        journal = InMemoryTradeJournalRepository()
        order = make_order(quantity=100.0, status=OrderStatus.PARTIALLY_FILLED)
        decision = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                             decision=DecisionAction.BUY, order=order)
        fill = make_fill(quantity=40.0)  # only 40 of the requested 100 filled
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=fill, position_after=40.0)

        assert decision.order.status == OrderStatus.PARTIALLY_FILLED
        assert trade.quantity == 40.0
        assert trade.position_after == 40.0


class TestRejectedOrder:
    def test_rejected_order_produces_decision_but_no_trade(self) -> None:
        journal = InMemoryTradeJournalRepository()
        order = make_order(status=OrderStatus.REJECTED, rejection_reason="insufficient cash")
        decision = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                             decision=DecisionAction.BUY, order=order)

        assert decision.order.status == OrderStatus.REJECTED
        assert decision.order.rejection_reason == "insufficient cash"
        assert journal.list_trades() == []


class TestCancelledOrder:
    def test_cancelled_order_is_representable_without_a_schema_change(self) -> None:
        # Phase 2's synchronous BacktestBroker never produces CANCELLED
        # (confirmed by inspecting src/backtest/{orders,fills}.py) — this
        # proves the Journal already tolerates it for a future async
        # broker (Phase 13+), per Phase 3 spec section 5.3.
        journal = InMemoryTradeJournalRepository()
        order = make_order(status=OrderStatus.CANCELLED, rejection_reason="cancelled by user before fill")
        decision = journal.record_decision(decision_time=order.decision_time, security_id="AAA",
                                             decision=DecisionAction.BUY, order=order)
        assert decision.order.status == OrderStatus.CANCELLED
        assert journal.list_trades() == []


class TestRealizedPnl:
    def test_realized_pnl_matches_hand_computation(self) -> None:
        journal = InMemoryTradeJournalRepository()
        buy_decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                                 decision=DecisionAction.BUY, order=make_order(order_id="ORD-BUY"))
        sell_decision = journal.record_decision(decision_time=utc(2024, 1, 5), security_id="AAA",
                                                  decision=DecisionAction.SELL,
                                                  order=make_order(order_id="ORD-SELL", side=OrderSide.SELL))

        buy_fill = make_fill(order_id="ORD-BUY", side=OrderSide.BUY, quantity=10, price=100.0,
                              commission=0, spread_cost=0, slippage_cost=0)
        journal.record_trade(decision_id=buy_decision.snapshot_id, fill=buy_fill, position_after=10.0)

        sell_fill = make_fill(order_id="ORD-SELL", side=OrderSide.SELL, quantity=10, price=120.0,
                               commission=1.0, spread_cost=0, slippage_cost=0,
                               decision_time=utc(2024, 1, 4), execution_time=utc(2024, 1, 5))
        # realized = (120-100)*10 - total_cost(1.0) = 199.0
        sell_trade = journal.record_trade(
            decision_id=sell_decision.snapshot_id, fill=sell_fill, position_after=0.0,
            realized_pnl=199.0, realized_return=199.0 / 1000.0,
        )
        assert sell_trade.realized_pnl == pytest.approx(199.0)
        assert sell_trade.realized_return == pytest.approx(0.199)

    def test_buy_trade_has_no_realized_pnl(self) -> None:
        journal = InMemoryTradeJournalRepository()
        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.BUY, order=make_order())
        trade = journal.record_trade(decision_id=decision.snapshot_id, fill=make_fill(), position_after=10.0)
        assert trade.realized_pnl is None
        assert trade.realized_return is None
        assert trade.holding_period is None


class TestHoldingPeriod:
    def test_holding_period_matches_hand_computation(self) -> None:
        from datetime import timedelta

        journal = InMemoryTradeJournalRepository()
        opened_at = utc(2024, 1, 3)
        closed_at = utc(2024, 1, 10)

        decision = journal.record_decision(decision_time=utc(2024, 1, 2), security_id="AAA",
                                             decision=DecisionAction.SELL, order=make_order(side=OrderSide.SELL))
        fill = make_fill(side=OrderSide.SELL, execution_time=closed_at)
        trade = journal.record_trade(
            decision_id=decision.snapshot_id, fill=fill, position_after=0.0,
            holding_period=closed_at - opened_at,
        )
        assert trade.holding_period == timedelta(days=7)
