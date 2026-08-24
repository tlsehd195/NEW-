"""Fill representation and FillSimulator.

See docs/specifications/PHASE-2-backtesting.md section 6.2-6.4 and
ADR-0006 for the execution timing convention (decide at T's close, fill
at T+1's close) this module implements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from data_infra.models import PriceBar

from backtest.costs import SlippageModel, TransactionCostModel
from backtest.enums import OrderSide, OrderStatus, OrderType
from backtest.orders import Order
from backtest.portfolio import PortfolioView


@dataclass(frozen=True)
class Fill:
    order_id: str
    security_id: str
    side: OrderSide
    quantity: float
    reference_price: float  # execution bar's close, before spread/slippage
    price: float  # effective per-share price actually paid/received
    commission: float
    spread_cost: float
    slippage_cost: float
    decision_time: datetime
    execution_time: datetime
    data_version: str  # provenance.data_version of the bar used for pricing

    @property
    def total_cost(self) -> float:
        return self.commission + self.spread_cost + self.slippage_cost

    @property
    def notional(self) -> float:
        return self.price * self.quantity


class FillSimulator:
    def __init__(
        self,
        cost_model: TransactionCostModel,
        slippage_model: SlippageModel,
        *,
        max_participation: float = 0.10,
    ) -> None:
        if not 0.0 < max_participation <= 1.0:
            raise ValueError("max_participation must be in (0, 1]")
        self._cost_model = cost_model
        self._slippage_model = slippage_model
        self._max_participation = max_participation

    def execute(
        self,
        order: Order,
        execution_bar: Optional[PriceBar],
        portfolio: PortfolioView,
        execution_time: datetime,
    ) -> tuple[Optional[Fill], Order]:
        """Returns (fill_or_none, updated_order). `execution_bar` must be
        the checkpoint T+1 bar (ADR-0006) — the caller (BacktestEngine)
        is responsible for fetching it via AsOfDataView, so this function
        itself has no way to reach for a different bar."""
        if order.order_type == OrderType.LIMIT:
            raise NotImplementedError("FillSimulator does not implement LIMIT orders in Phase 2 — see ADR-0006")

        if order.status != OrderStatus.PROPOSED:
            return None, order  # already rejected at order-creation time

        if execution_bar is None:
            updated = replace(
                order, status=OrderStatus.NOT_EXECUTED,
                rejection_reason="no execution data available at T+1 checkpoint",
            )
            return None, updated

        reference_price = execution_bar.close
        max_fillable = math.floor(execution_bar.volume * self._max_participation)
        fill_quantity = min(order.quantity, max_fillable) if max_fillable > 0 else 0

        if fill_quantity <= 0:
            updated = replace(
                order, status=OrderStatus.NOT_EXECUTED,
                rejection_reason="insufficient liquidity to fill any quantity",
            )
            return None, updated

        price_after_spread = self._cost_model.apply_spread(reference_price, order.side)
        price_after_slippage = self._slippage_model.adjust(
            price_after_spread, fill_quantity, order.side, execution_bar.volume
        )
        commission = self._cost_model.commission(fill_quantity)

        if order.side == OrderSide.BUY:
            # Second-stage, authoritative cash check at the real fill
            # economics (ADR-0006) — an order that looked affordable at
            # order-creation time is rejected here, not silently allowed
            # to overdraw cash, if the real price makes it unaffordable.
            actual_notional = price_after_slippage * fill_quantity
            if actual_notional + commission > portfolio.cash:
                updated = replace(
                    order, status=OrderStatus.REJECTED,
                    rejection_reason="insufficient cash at actual fill price",
                )
                return None, updated

        spread_cost = abs(price_after_spread - reference_price) * fill_quantity
        slippage_cost = abs(price_after_slippage - price_after_spread) * fill_quantity

        fill = Fill(
            order_id=order.order_id,
            security_id=order.security_id,
            side=order.side,
            quantity=float(fill_quantity),
            reference_price=reference_price,
            price=price_after_slippage,
            commission=commission,
            spread_cost=spread_cost,
            slippage_cost=slippage_cost,
            decision_time=order.decision_time,
            execution_time=execution_time,
            data_version=execution_bar.provenance.data_version,
        )
        status = OrderStatus.FILLED if fill_quantity == order.quantity else OrderStatus.PARTIALLY_FILLED
        updated = replace(order, status=status)
        return fill, updated
