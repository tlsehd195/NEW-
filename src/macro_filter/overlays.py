"""Price-only index overlays for SPY (ADR-0235 section 2a): `sma_10m` and
`vol_target_10`, plus the unfiltered baseline. Parameters are the textbook
values, fixed before any run. Uses the unmodified `BacktestEngine` through
the `Strategy` protocol, like `MacroExposureStrategy`.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.enums import OrderSide
from backtest.portfolio import PortfolioView
from backtest.strategy import OrderIntent
from data_infra.models import PriceBar

OVERLAY_RULES = ("no_filter", "sma_10m", "vol_target_10")

SMA_MONTHS = 10
VOL_TARGET = 0.10
VOL_LOOKBACK_DAYS = 21
VOL_REWEIGHT_BAND = 0.10


def _price(bar: PriceBar) -> float:
    return bar.adjusted_close if bar.adjusted_close is not None else bar.close


def month_end_closes(bars: Sequence[PriceBar], before: datetime) -> list[float]:
    """Last close of every calendar month that ended before `before`'s month."""
    last: dict[tuple[int, int], float] = {}
    for bar in bars:
        key = (bar.timestamp.year, bar.timestamp.month)
        if key < (before.year, before.month) and _price(bar) > 0:
            last[key] = _price(bar)
    return [last[k] for k in sorted(last)]


def sma_exposure(bars: Sequence[PriceBar], as_of: datetime) -> Optional[float]:
    closes = month_end_closes(bars, as_of)
    if len(closes) < SMA_MONTHS:
        return None
    window = closes[-SMA_MONTHS:]
    return 1.0 if window[-1] > statistics.fmean(window) else 0.0


def vol_target_exposure(bars: Sequence[PriceBar]) -> Optional[float]:
    prices = [_price(b) for b in bars if _price(b) > 0]
    if len(prices) < VOL_LOOKBACK_DAYS + 1:
        return None
    window = prices[-(VOL_LOOKBACK_DAYS + 1):]
    returns = [b / a - 1.0 for a, b in zip(window, window[1:])]
    vol = statistics.stdev(returns) * math.sqrt(252)
    return 1.0 if vol <= 0 else min(1.0, VOL_TARGET / vol)


class IndexOverlayStrategy:
    version = "index_overlay_v1"

    COST_SAFETY_MARGIN = 0.02
    DRIFT_BAND = 0.025

    def __init__(self, symbol: str, rule: str) -> None:
        if rule not in OVERLAY_RULES:
            raise ValueError(f"unknown overlay rule {rule!r}")
        self._symbol = symbol
        self._rule = rule
        self._applied: Optional[float] = None
        self._month: Optional[tuple[int, int]] = None
        self._monthly_target: float = 1.0
        self.exposure_log: list[tuple[datetime, float]] = []

    def _target(self, as_of: datetime, data: AsOfDataView) -> float:
        if self._rule == "no_filter":
            return 1.0
        if self._rule == "sma_10m":
            month = (as_of.year, as_of.month)
            if month != self._month:
                bars = data.get_bars(self._symbol, as_of - timedelta(days=400), as_of)
                exposure = sma_exposure(bars, as_of)
                self._monthly_target = 1.0 if exposure is None else exposure
                self._month = month
            return self._monthly_target
        bars = data.get_bars(self._symbol, as_of - timedelta(days=60), as_of)
        exposure = vol_target_exposure(bars)
        return 1.0 if exposure is None else exposure

    def generate_orders(
        self, as_of_time: datetime, data: AsOfDataView, portfolio: PortfolioView
    ) -> list[OrderIntent]:
        target = self._target(as_of_time, data)
        self.exposure_log.append((as_of_time, target))
        bars = data.get_bars(self._symbol, as_of_time - timedelta(days=14), as_of_time)
        if not bars or bars[-1].close <= 0 or portfolio.portfolio_value <= 0:
            return []
        price = bars[-1].close
        held = portfolio.quantity_of(self._symbol)
        held_share = held * price / portfolio.portfolio_value
        desired_share = target * (1.0 - self.COST_SAFETY_MARGIN)
        band = VOL_REWEIGHT_BAND if self._rule == "vol_target_10" else self.DRIFT_BAND
        if self._applied is not None and abs(held_share - desired_share) <= band:
            return []
        target_quantity = math.floor(desired_share * portfolio.portfolio_value / price)
        self._applied = target
        delta = target_quantity - held
        if delta > 0:
            return [OrderIntent(self._symbol, OrderSide.BUY, float(delta))]
        if delta < 0:
            return [OrderIntent(self._symbol, OrderSide.SELL, float(-delta))]
        return []
