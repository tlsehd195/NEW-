"""Shared test helpers for the Phase 6 Prediction test suite."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from backtest_helpers import build_repository, checkpoint, make_bars, trading_days

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from data_infra.repository import InMemoryDataRepository


def view_at(repository: InMemoryDataRepository, days: Sequence[date], index: int) -> AsOfDataView:
    clock = BacktestClock(tuple(checkpoint(d) for d in days))
    clock.index = index
    return AsOfDataView(repository, clock)


def drifting_prices(days: Sequence[date], start: float = 100.0, daily_return: float = 0.0008, *, seed: int = 3) -> list[float]:
    import random

    rng = random.Random(seed)
    closes = [start]
    for _ in range(1, len(days)):
        closes.append(closes[-1] * (1 + daily_return + rng.gauss(0.0, 0.01)))
    return closes


__all__ = ["build_repository", "checkpoint", "make_bars", "trading_days", "view_at", "drifting_prices"]
