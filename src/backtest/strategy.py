"""Strategy interface and Phase 2 baseline strategies.

See docs/specifications/PHASE-2-backtesting.md sections 5, 10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide, OrderType
from backtest.portfolio import PortfolioView


@dataclass(frozen=True)
class OrderIntent:
    security_id: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    # Session 36 addition: the decision-time rationale (e.g. factor
    # scores, model inputs) a Strategy MAY attach to its own intent --
    # optional and never populated by any Strategy in this file, so
    # this is pure additive plumbing, not a behavior change. Exists so
    # `trade_journal.backtest_adapter` has something real to put in
    # `DecisionSnapshot.features` (previously always None for every
    # order this project has ever journaled -- see ADR-0048) instead of
    # needing a second, parallel way to pass rationale through
    # `BacktestEngine`, which has no other route from a Strategy's own
    # `generate_orders` call to the journal.
    features: Optional[dict] = None


class Strategy(Protocol):
    """Any implementation — including a future ML-based strategy
    (Phase 6+) — plugs in here without BacktestEngine changing (Phase 2
    spec section 5, section 10.3)."""

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]: ...


class BuyAndHoldStrategy:
    """Equal-weight buy of `security_ids` on the first decision
    checkpoint THAT ACTUALLY HAS DATA for at least one symbol; holds
    thereafter (Phase 2 spec section 10.1). Not necessarily the
    backtest's very first checkpoint -- a real trading calendar can
    include a date `AsOfDataView` has no bar for yet (e.g. a market
    holiday the calendar's own hand-picked holiday set doesn't know
    about, `data_infra.calendar`'s own documented limitation), and this
    strategy must keep waiting rather than permanently giving up on an
    empty first attempt (found via a real Phase 24 ingestion run,
    `tests/backtest/test_buy_and_hold_late_data_availability.py`)."""

    version = "buy_and_hold_v1"

    # A Strategy has no visibility into the broker's TransactionCostModel
    # by design (Phase 2 spec section 5 — proposing is separate from
    # execution economics). Spending down to the last unit of cash would
    # therefore leave nothing for OrderSimulator's commission estimate,
    # causing a spurious REJECTED. COST_SAFETY_MARGIN reserves a small,
    # generic buffer instead of leaking cost-model details into the
    # strategy.
    COST_SAFETY_MARGIN = 0.02

    def __init__(self, security_ids: Sequence[str], cash_buffer: float = 0.0) -> None:
        if not 0.0 <= cash_buffer < 1.0:
            raise ValueError("cash_buffer must be in [0, 1)")
        self._security_ids = list(security_ids)
        self._cash_buffer = cash_buffer
        self._invested = False

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._invested or not self._security_ids:
            return []

        investable_cash = portfolio.cash * (1.0 - self._cash_buffer) * (1.0 - self.COST_SAFETY_MARGIN)
        per_symbol_cash = investable_cash / len(self._security_ids)

        intents: list[OrderIntent] = []
        for security_id in self._security_ids:
            bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
            if not bars:
                continue
            price = bars[-1].close
            if price <= 0:
                continue
            quantity = math.floor(per_symbol_cash / price)
            if quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.BUY, float(quantity)))
        # Only commit to "already invested" once a real attempt actually
        # produced at least one order -- a checkpoint where no symbol
        # has data yet must not permanently disable every later,
        # genuinely investable checkpoint.
        if intents:
            self._invested = True
        return intents


class SimpleMomentumStrategy:
    """Long-only, cross-sectional trailing-return momentum, rebalanced
    every `rebalance_every` decision steps (Phase 2 spec section 10.2).
    A deliberately simplified reading of Moskowitz, Ooi & Pedersen —
    no short leg, no absolute-momentum construction; only the "rank by
    trailing return, hold the top N" idea is used."""

    version = "simple_momentum_v1"

    # See BuyAndHoldStrategy.COST_SAFETY_MARGIN.
    COST_SAFETY_MARGIN = 0.02

    def __init__(
        self,
        security_ids: Sequence[str],
        *,
        lookback_days: int = 20,
        top_n: int = 2,
        rebalance_every: int = 10,
    ) -> None:
        if top_n < 1:
            raise ValueError("top_n must be >= 1")
        if rebalance_every < 1:
            raise ValueError("rebalance_every must be >= 1")
        self._security_ids = list(security_ids)
        self._lookback_days = lookback_days
        self._top_n = top_n
        self._rebalance_every = rebalance_every
        self._step = 0

    def _momentum_score(self, security_id: str, as_of_time: datetime, data: AsOfDataView) -> float | None:
        bars = data.get_bars(
            security_id, as_of_time - timedelta(days=self._lookback_days * 2), as_of_time
        )
        if len(bars) < 2:
            return None
        start_price = bars[0].adjusted_close or bars[0].close
        end_price = bars[-1].adjusted_close or bars[-1].close
        if start_price <= 0:
            return None
        return end_price / start_price - 1.0

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        self._step += 1
        if (self._step - 1) % self._rebalance_every != 0:
            return []

        scores: dict[str, float] = {}
        for security_id in self._security_ids:
            score = self._momentum_score(security_id, as_of_time, data)
            if score is not None:
                scores[security_id] = score

        ranked = sorted(scores, key=lambda sid: scores[sid], reverse=True)
        target = set(ranked[: self._top_n])

        intents: list[OrderIntent] = []
        for security_id, position in portfolio.positions.items():
            if security_id not in target and position.quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.SELL, position.quantity))

        to_buy = [sid for sid in target if portfolio.quantity_of(sid) == 0]
        if to_buy:
            per_symbol_cash = portfolio.cash * (1.0 - self.COST_SAFETY_MARGIN) / len(to_buy)
            for security_id in to_buy:
                bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
                if not bars:
                    continue
                price = bars[-1].close
                if price <= 0:
                    continue
                quantity = math.floor(per_symbol_cash / price)
                if quantity > 0:
                    intents.append(OrderIntent(security_id, OrderSide.BUY, float(quantity)))
        return intents
