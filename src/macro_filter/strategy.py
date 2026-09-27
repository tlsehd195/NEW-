"""MacroExposureStrategy: holds one equity symbol (SPY) at the exposure an
`ExposureRule` gives, the rest in cash (ADR-0220). It trades only when
the target exposure changes, so the unfiltered baseline buys once and
holds, exactly like `BuyAndHoldStrategy`.

Uses the unmodified `BacktestEngine` through the `Strategy` protocol;
prices come from the engine's own `AsOfDataView`, macro values from the
point-in-time `MacroSignalEngine` evaluated at the same checkpoint time.
Cash earns nothing (the engine's `risk_free_rate=0.0`, ADR-0208), which
understates a filter that sits in cash.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent

from macro_filter.signals import ExposureRule, MacroSignalEngine


class MacroExposureStrategy:
    version = "macro_exposure_v1"

    # Same generic buffer as BuyAndHoldStrategy.COST_SAFETY_MARGIN.
    COST_SAFETY_MARGIN = 0.02
    # Also rebalance when the invested share drifts this far from the
    # target (dividends piling up as cash, price moves at a partial
    # exposure). Same band for every trial, the baseline included.
    DRIFT_BAND = 0.025

    def __init__(self, symbol: str, engine: MacroSignalEngine, rule: ExposureRule) -> None:
        self._symbol = symbol
        self._engine = engine
        self._rule = rule
        self._applied: Optional[float] = None
        # (checkpoint, target exposure) for every checkpoint, for the
        # report's time-de-risked statistics.
        self.exposure_log: list[tuple[datetime, float]] = []

    @property
    def rule(self) -> ExposureRule:
        return self._rule

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        snapshot = self._engine.evaluate(as_of_time, data.get_bars)
        target = self._rule.exposure(snapshot, self._engine.config)
        self.exposure_log.append((as_of_time, target))
        bars = data.get_bars(self._symbol, as_of_time - timedelta(days=14), as_of_time)
        if not bars or bars[-1].close <= 0 or portfolio.portfolio_value <= 0:
            return []
        price = bars[-1].close
        held = portfolio.quantity_of(self._symbol)
        desired_share = target * (1.0 - self.COST_SAFETY_MARGIN)
        if self._applied is not None and target == self._applied:
            held_share = held * price / portfolio.portfolio_value
            if abs(held_share - desired_share) <= self.DRIFT_BAND:
                return []
        target_quantity = math.floor(desired_share * portfolio.portfolio_value / price)
        self._applied = target
        delta = target_quantity - held
        if delta > 0:
            return [OrderIntent(self._symbol, OrderSide.BUY, float(delta), features=dict(snapshot.flags))]
        if delta < 0:
            return [OrderIntent(self._symbol, OrderSide.SELL, float(-delta), features=dict(snapshot.flags))]
        return []
