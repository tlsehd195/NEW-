"""Shared test helpers for the Phase 7 Decision Agent test suite."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from backtest_helpers import build_repository, checkpoint, make_bars, trading_days
from predict_helpers import drifting_prices

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from backtest.portfolio import PortfolioView, PositionView

from data_infra.repository import InMemoryDataRepository


def view_at(repository: InMemoryDataRepository, days: Sequence[date], index: int) -> AsOfDataView:
    clock = BacktestClock(tuple(checkpoint(d) for d in days))
    clock.index = index
    return AsOfDataView(repository, clock)


def empty_portfolio(as_of_time) -> PortfolioView:
    return PortfolioView(as_of_time=as_of_time, cash=100_000.0, positions={}, portfolio_value=100_000.0)


def portfolio_holding(as_of_time, security_id: str, quantity: float = 100.0, average_cost: float = 90.0) -> PortfolioView:
    return PortfolioView(
        as_of_time=as_of_time, cash=50_000.0,
        positions={security_id: PositionView(security_id, quantity, average_cost)},
        portfolio_value=100_000.0,
    )


__all__ = [
    "build_repository", "checkpoint", "make_bars", "trading_days", "drifting_prices",
    "view_at", "empty_portfolio", "portfolio_holding",
]
