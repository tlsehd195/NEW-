"""BrokerInterface and its Phase 2 implementation, BacktestBroker.

See docs/specifications/PHASE-2-backtesting.md section 3, section 6 and
ADR-0006. A future PaperBroker/TossBroker (Phase 13+) implements the same
BrokerInterface; BacktestEngine's use of the broker does not change when
the concrete implementation is swapped (Phase 1's DataRepository /
InMemoryDataRepository split, ADR-0002, is the precedent this mirrors).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol

from data_infra.models import PriceBar

from backtest.fills import Fill, FillSimulator
from backtest.orders import Order
from backtest.portfolio import PortfolioView


class BrokerInterface(Protocol):
    def submit_order(
        self,
        order: Order,
        execution_bar: Optional[PriceBar],
        portfolio: PortfolioView,
        execution_time: datetime,
    ) -> tuple[Optional[Fill], Order]: ...


class BacktestBroker:
    """The only BrokerInterface implementation in Phase 2. Delegates
    entirely to FillSimulator — this class exists so the interface
    boundary is real (BacktestEngine depends on BrokerInterface, not on
    FillSimulator directly), not to add behavior of its own."""

    def __init__(self, fill_simulator: FillSimulator) -> None:
        self._fill_simulator = fill_simulator

    def submit_order(
        self,
        order: Order,
        execution_bar: Optional[PriceBar],
        portfolio: PortfolioView,
        execution_time: datetime,
    ) -> tuple[Optional[Fill], Order]:
        return self._fill_simulator.execute(order, execution_bar, portfolio, execution_time)
