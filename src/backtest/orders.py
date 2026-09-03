"""Order representation and OrderSimulator (cash/position validation).

See docs/specifications/PHASE-2-backtesting.md section 6.1 and ADR-0006.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backtest.costs import TransactionCostModel
from backtest.enums import OrderSide, OrderStatus, OrderType
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent


@dataclass(frozen=True)
class Order:
    order_id: str
    security_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    decision_time: datetime
    status: OrderStatus
    rejection_reason: Optional[str] = None
    # Session 36 addition: copied straight through from the originating
    # OrderIntent.features (see backtest.strategy.OrderIntent) so a
    # rejected order still carries its rationale into the journal, not
    # just an accepted one -- ADR-0048.
    features: Optional[dict] = None


class OrderSimulator:
    """Validates an OrderIntent against the portfolio state as of the
    decision checkpoint, using a conservative (own-close) price estimate
    — the authoritative check happens again in FillSimulator once the
    real fill price is known (ADR-0006 point on two-stage cash
    validation)."""

    def __init__(self, cost_model: TransactionCostModel) -> None:
        self._cost_model = cost_model
        self._next_id = 1

    def allocate_id(self) -> str:
        order_id = f"ORD-{self._next_id:06d}"
        self._next_id += 1
        return order_id

    def create(
        self,
        intent: OrderIntent,
        portfolio: PortfolioView,
        decision_time: datetime,
        reference_price: float,
    ) -> Order:
        order_id = self.allocate_id()

        if intent.order_type == OrderType.LIMIT:
            # Structurally reserved, not implemented in Phase 2 (Phase 2
            # spec section 6.1 / ADR-0006).
            raise NotImplementedError(
                "OrderType.LIMIT is not implemented in Phase 2 — see ADR-0006"
            )

        if intent.quantity <= 0:
            return Order(
                order_id, intent.security_id, intent.side, intent.quantity, intent.order_type,
                decision_time, OrderStatus.REJECTED, "non-positive quantity", intent.features,
            )

        if intent.side == OrderSide.SELL:
            held = portfolio.quantity_of(intent.security_id)
            if intent.quantity > held:
                return Order(
                    order_id, intent.security_id, intent.side, intent.quantity, intent.order_type,
                    decision_time, OrderStatus.REJECTED,
                    f"insufficient position: requested {intent.quantity}, held {held}", intent.features,
                )
        else:  # BUY
            estimated_notional = reference_price * intent.quantity
            estimated_commission = self._cost_model.commission(intent.quantity)
            if estimated_notional + estimated_commission > portfolio.cash:
                return Order(
                    order_id, intent.security_id, intent.side, intent.quantity, intent.order_type,
                    decision_time, OrderStatus.REJECTED,
                    f"insufficient cash: need ~{estimated_notional + estimated_commission:.2f}, "
                    f"have {portfolio.cash:.2f}", intent.features,
                )

        return Order(
            order_id, intent.security_id, intent.side, intent.quantity, intent.order_type,
            decision_time, OrderStatus.PROPOSED, None, intent.features,
        )
