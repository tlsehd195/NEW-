"""Shared test helpers for the Phase 3 Trade Journal test suite."""

from __future__ import annotations

from datetime import datetime, timezone

from backtest.enums import OrderSide, OrderStatus, OrderType
from backtest.fills import Fill
from backtest.orders import Order


def utc(year: int, month: int, day: int, hour: int = 20, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_order(
    order_id: str = "ORD-000001",
    security_id: str = "AAA",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 10.0,
    decision_time: datetime | None = None,
    status: OrderStatus = OrderStatus.PROPOSED,
    rejection_reason: str | None = None,
) -> Order:
    return Order(
        order_id=order_id,
        security_id=security_id,
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        decision_time=decision_time or utc(2024, 1, 2),
        status=status,
        rejection_reason=rejection_reason,
    )


def make_fill(
    order_id: str = "ORD-000001",
    security_id: str = "AAA",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 10.0,
    price: float = 100.0,
    reference_price: float = 99.9,
    commission: float = 1.0,
    spread_cost: float = 0.1,
    slippage_cost: float = 0.2,
    decision_time: datetime | None = None,
    execution_time: datetime | None = None,
    data_version: str = "v-2024-01-03",
) -> Fill:
    return Fill(
        order_id=order_id,
        security_id=security_id,
        side=side,
        quantity=quantity,
        reference_price=reference_price,
        price=price,
        commission=commission,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        decision_time=decision_time or utc(2024, 1, 2),
        execution_time=execution_time or utc(2024, 1, 3),
        data_version=data_version,
    )
