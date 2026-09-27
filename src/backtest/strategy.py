"""Strategy interface and Phase 2 baseline strategies.

See docs/specifications/PHASE-2-backtesting.md sections 5, 10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from backtest.asof import AsOfDataView
from backtest.costs import DEFAULT_TRANSACTION_COST_MODEL, TransactionCostModel
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


def new_position_cash(
    portfolio: PortfolioView,
    data: AsOfDataView,
    as_of_time: datetime,
    target: set[str] | frozenset[str],
    to_buy_count: int,
    cost_safety_margin: float,
) -> float:
    """Cash to put into each NEW position of an equal-weight rebalance
    toward `target` (ADR-0219).

    Counts this rebalance's own SELL proceeds (held names leaving
    `target`, at their latest close), since the engine fills those sells
    before the buys. Caps each new position at an equal share of the
    whole portfolio. Sizing from `portfolio.cash` alone left the sell
    proceeds idle for one rebalance, then poured all of them into the
    next rebalance's few new names. On research-catalogs-v1,
    sloan_accruals put 34% of a $10k book into TSLA in 2019-07, and one
    position produced a +306% held-out return."""
    proceeds = 0.0
    for security_id, position in portfolio.positions.items():
        if security_id in target or position.quantity <= 0:
            continue
        bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
        if bars and bars[-1].close > 0:
            proceeds += position.quantity * bars[-1].close
    budget = (portfolio.cash + proceeds) * (1.0 - cost_safety_margin) / to_buy_count
    cap = portfolio.portfolio_value * (1.0 - cost_safety_margin) / len(target)
    return max(0.0, min(budget, cap))


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

    def __init__(
        self,
        security_ids: Sequence[str],
        cash_buffer: float = 0.0,
        *,
        fractional: bool = False,
        cost_safety_margin: Optional[float] = None,
    ) -> None:
        """`fractional=True` buys fractional shares and splits the cash
        only across symbols that have a price at the buy checkpoint
        (ADR-0223). With whole shares, $10k over 203 symbols is ~$48 a
        name, so every name priced above that got 0 shares, and names
        not yet listed kept their slice as cash for the whole run: the
        research baseline was mostly cash. `cost_safety_margin`
        overrides COST_SAFETY_MARGIN for callers that know the cost
        model (the strategy itself never does)."""
        if not 0.0 <= cash_buffer < 1.0:
            raise ValueError("cash_buffer must be in [0, 1)")
        if cost_safety_margin is not None and not 0.0 <= cost_safety_margin < 1.0:
            raise ValueError("cost_safety_margin must be in [0, 1)")
        self._security_ids = list(security_ids)
        self._cash_buffer = cash_buffer
        self._fractional = fractional
        self._cost_safety_margin = self.COST_SAFETY_MARGIN if cost_safety_margin is None else cost_safety_margin
        self._invested = False

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        if self._invested or not self._security_ids:
            return []

        investable_cash = portfolio.cash * (1.0 - self._cash_buffer) * (1.0 - self._cost_safety_margin)

        prices: dict[str, float] = {}
        for security_id in self._security_ids:
            bars = data.get_bars(security_id, as_of_time - timedelta(days=14), as_of_time)
            if bars and bars[-1].close > 0:
                prices[security_id] = bars[-1].close
        if not prices:
            return []
        per_symbol_cash = investable_cash / (len(prices) if self._fractional else len(self._security_ids))

        intents: list[OrderIntent] = []
        for security_id, price in prices.items():
            quantity = per_symbol_cash / price if self._fractional else float(math.floor(per_symbol_cash / price))
            if quantity > 0:
                intents.append(OrderIntent(security_id, OrderSide.BUY, quantity))
        # Only commit to "already invested" once a real attempt actually
        # produced at least one order -- a checkpoint where no symbol
        # has data yet must not permanently disable every later,
        # genuinely investable checkpoint.
        if intents:
            self._invested = True
        return intents


def buy_and_hold_baseline(
    security_ids: Sequence[str],
    initial_capital: float,
    cost_model: TransactionCostModel = DEFAULT_TRANSACTION_COST_MODEL,
) -> BuyAndHoldStrategy:
    """The research baseline: fractional, equal-weight buy-and-hold whose
    cash margin also covers one fixed commission per name (ADR-0223).
    Without that, $1 x 203 names ate the 2% margin and the last orders
    were rejected for cash."""
    margin = BuyAndHoldStrategy.COST_SAFETY_MARGIN + len(security_ids) * cost_model.fixed_per_trade / initial_capital
    return BuyAndHoldStrategy(security_ids, fractional=True, cost_safety_margin=min(margin, 0.5))


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
                # External review, ADR-0048's own original gap: attach
                # the real momentum score this security's ranking was
                # already computed from -- no new computation, omitted
                # (never fabricated) for a security not in `scores`.
                features = {"momentum_score": scores[security_id]} if security_id in scores else None
                intents.append(OrderIntent(security_id, OrderSide.SELL, position.quantity, features=features))

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
                    features = {"momentum_score": scores[security_id]} if security_id in scores else None
                    intents.append(OrderIntent(security_id, OrderSide.BUY, float(quantity), features=features))
        return intents
