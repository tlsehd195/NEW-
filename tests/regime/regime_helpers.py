"""Shared test helpers for the Phase 5 Market Regime test suite."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from backtest_helpers import build_repository, checkpoint, make_bars, make_benchmark, trading_days
from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from data_infra.repository import InMemoryDataRepository


def make_price_series(days: Sequence[date], closes: Sequence[float], security_id: str = "AAA"):
    return make_bars(security_id, days, closes)


def view_at(repository: InMemoryDataRepository, days: Sequence[date], index: int) -> AsOfDataView:
    """An AsOfDataView whose clock is parked at `days[index]`, over the
    *full* set of checkpoints `days` -- mirrors exactly how BacktestEngine
    drives a real run, so a test can move the clock both forward and
    check that later checkpoints do not leak into an earlier one."""
    clock = BacktestClock(tuple(checkpoint(d) for d in days))
    clock.index = index
    return AsOfDataView(repository, clock)


def trend_up(days: Sequence[date], start: float = 100.0, daily_return: float = 0.003) -> list[float]:
    closes = [start]
    for _ in range(1, len(days)):
        closes.append(closes[-1] * (1 + daily_return))
    return closes


def trend_down(days: Sequence[date], start: float = 100.0, daily_return: float = -0.003) -> list[float]:
    return trend_up(days, start=start, daily_return=daily_return)


def high_volatility(days: Sequence[date], start: float = 100.0, *, seed: int = 7) -> list[float]:
    import random

    rng = random.Random(seed)
    closes = [start]
    for _ in range(1, len(days)):
        closes.append(max(0.01, closes[-1] * (1 + rng.gauss(0.0, 0.06))))
    return closes


def low_volatility(days: Sequence[date], start: float = 100.0, *, seed: int = 11) -> list[float]:
    import random

    rng = random.Random(seed)
    closes = [start]
    for _ in range(1, len(days)):
        closes.append(closes[-1] * (1 + rng.gauss(0.0002, 0.002)))
    return closes


__all__ = [
    "build_repository", "checkpoint", "make_bars", "make_benchmark", "trading_days",
    "make_price_series", "view_at", "trend_up", "trend_down", "high_volatility", "low_volatility",
]
