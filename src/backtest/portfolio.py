"""Portfolio state and accounting.

See docs/specifications/PHASE-2-backtesting.md section 8.

Average-cost-basis accounting (not FIFO tax lots) — a documented Phase 2
simplification (spec section 8.1). PortfolioAccounting never rejects or
validates a fill (that is OrderSimulator/FillSimulator's job, upstream);
it only performs the bookkeeping arithmetic, so that a deliberately
invalid fill (used to exercise BacktestIntegrityChecker's "impossible
portfolio state" check) can still be applied and observed rather than
raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from backtest.enums import OrderSide

if TYPE_CHECKING:
    from backtest.fills import Fill


@dataclass
class Position:
    security_id: str
    quantity: float = 0.0
    average_cost: float = 0.0


@dataclass(frozen=True)
class PositionView:
    security_id: str
    quantity: float
    average_cost: float


@dataclass(frozen=True)
class PortfolioView:
    """Read-only snapshot handed to a Strategy. A Strategy cannot mutate
    portfolio state through this — only BacktestBroker/PortfolioAccounting
    can, after order/fill simulation (Phase 2 spec section 5)."""

    as_of_time: datetime
    cash: float
    positions: dict[str, PositionView]
    portfolio_value: float

    def quantity_of(self, security_id: str) -> float:
        pos = self.positions.get(security_id)
        return pos.quantity if pos is not None else 0.0


@dataclass(frozen=True)
class ValuationPoint:
    as_of_time: datetime
    cash: float
    market_value: float
    portfolio_value: float


@dataclass(frozen=True)
class CashFlowRecord:
    as_of_time: datetime
    security_id: str
    amount: float
    reason: str  # e.g. "dividend"


@dataclass(frozen=True)
class ClosedTradeRecord:
    security_id: str
    quantity: float
    average_cost: float
    exit_price: float
    realized_pnl: float
    execution_time: datetime


class PortfolioAccounting:
    def __init__(self, initial_cash: float) -> None:
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        self.cash: float = initial_cash
        self.positions: dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.transaction_costs: float = 0.0
        self.cash_flows: list[CashFlowRecord] = []
        self.closed_trades: list[ClosedTradeRecord] = []
        self._trade_notionals: list[float] = []
        self._valuation_history: list[ValuationPoint] = []

    @property
    def value_series(self) -> tuple[ValuationPoint, ...]:
        return tuple(self._valuation_history)

    def apply_fill(self, fill: "Fill") -> None:
        pos = self.positions.setdefault(fill.security_id, Position(fill.security_id))
        self.transaction_costs += fill.total_cost
        self._trade_notionals.append(fill.notional)

        if fill.side == OrderSide.BUY:
            self.cash -= fill.notional + fill.commission
            new_quantity = pos.quantity + fill.quantity
            if new_quantity > 0:
                pos.average_cost = (
                    pos.average_cost * pos.quantity + fill.price * fill.quantity
                ) / new_quantity
            pos.quantity = new_quantity
        else:  # SELL
            self.cash += fill.notional - fill.commission
            realized = (fill.price - pos.average_cost) * fill.quantity - fill.total_cost
            self.realized_pnl += realized
            self.closed_trades.append(
                ClosedTradeRecord(
                    security_id=fill.security_id,
                    quantity=fill.quantity,
                    average_cost=pos.average_cost,
                    exit_price=fill.price,
                    realized_pnl=realized,
                    execution_time=fill.execution_time,
                )
            )
            pos.quantity -= fill.quantity
            if pos.quantity <= 0:
                pos.average_cost = 0.0

        if pos.quantity == 0:
            del self.positions[fill.security_id]

    def apply_split(self, security_id: str, ratio_multiplier: float) -> None:
        """ratio_multiplier > 1 for a forward split (e.g. 2.0 for a 2:1
        split), < 1 for a reverse split. Not a trade — does not touch
        realized_pnl, transaction_costs, or trade_notionals (Phase 2 spec
        section 8.4)."""
        pos = self.positions.get(security_id)
        if pos is None or pos.quantity == 0:
            return
        pos.quantity *= ratio_multiplier
        pos.average_cost /= ratio_multiplier

    def apply_dividend(self, security_id: str, amount_per_share: float, as_of_time: datetime) -> None:
        pos = self.positions.get(security_id)
        if pos is None or pos.quantity == 0:
            return
        credit = pos.quantity * amount_per_share
        self.cash += credit
        self.cash_flows.append(
            CashFlowRecord(as_of_time=as_of_time, security_id=security_id, amount=credit, reason="dividend")
        )

    def mark_to_market(self, prices: dict[str, float], as_of_time: datetime) -> tuple[ValuationPoint, list[str]]:
        """Values every open position using `prices` (typically that
        day's own close — see Phase 2 spec section 8.3 for why this is
        not leakage). A held security missing from `prices` falls back to
        its average cost (a neutral, non-fabricated valuation) and is
        returned in the second element for the caller to raise as a
        missing_data integrity issue."""
        missing: list[str] = []
        market_value = 0.0
        for security_id, pos in self.positions.items():
            if pos.quantity == 0:
                continue
            price = prices.get(security_id)
            if price is None:
                missing.append(security_id)
                price = pos.average_cost
            market_value += pos.quantity * price
        point = ValuationPoint(
            as_of_time=as_of_time,
            cash=self.cash,
            market_value=market_value,
            portfolio_value=self.cash + market_value,
        )
        self._valuation_history.append(point)
        return point, missing

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        total = 0.0
        for security_id, pos in self.positions.items():
            if pos.quantity == 0:
                continue
            price = prices.get(security_id, pos.average_cost)
            total += (price - pos.average_cost) * pos.quantity
        return total

    def turnover(self) -> float:
        if not self._valuation_history:
            return 0.0
        avg_value = sum(p.portfolio_value for p in self._valuation_history) / len(self._valuation_history)
        if avg_value <= 0:
            return 0.0
        return sum(self._trade_notionals) / avg_value

    def snapshot_view(self, as_of_time: datetime) -> PortfolioView:
        last_value = (
            self._valuation_history[-1].portfolio_value if self._valuation_history else self.cash
        )
        return PortfolioView(
            as_of_time=as_of_time,
            cash=self.cash,
            positions={
                sid: PositionView(sid, p.quantity, p.average_cost)
                for sid, p in self.positions.items()
                if p.quantity != 0
            },
            portfolio_value=last_value,
        )
