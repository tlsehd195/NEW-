"""BrokerInterface and its Phase 2 implementation, BacktestBroker.

See docs/specifications/PHASE-2-backtesting.md section 3, section 6 and
ADR-0006. `BacktestEngine` depends on `BrokerInterface`, not on
`BacktestBroker`/`FillSimulator` directly (Phase 1's DataRepository /
InMemoryDataRepository split, ADR-0002, is the precedent this mirrors).

**Correction (independent audit finding, 2026-09-25): the paragraph
below used to say "A future PaperBroker/TossBroker (Phase 13+)
implements the same BrokerInterface" -- false as written and left
uncorrected since Phase 2. Phase 13+ built `broker.protocol.
BrokerAdapter` instead, a deliberately DIFFERENT, differently-shaped
Protocol (`submit_order(order: ValidatedOrder, *, requested_at)
-> BrokerOrderResponse` plus `cancel_order`/`get_order_status`/
`get_account`/`get_positions`/`get_capabilities` -- see that module's
own docstring) for real Paper/Live trading, never `BrokerInterface`
(`submit_order(order: Order, execution_bar, portfolio, execution_time)
-> tuple[Optional[Fill], Order]`, backtest-specific: `execution_bar`
and the returned `Fill` only make sense against a historical
`PriceBar`, which Paper/Live trading has no analogue for). Neither
`broker.paper.adapter.PaperBrokerAdapter` nor `broker.toss.adapter.
TossBrokerAdapter` implements `BrokerInterface` -- both implement
`BrokerAdapter`. `BrokerInterface`/`BacktestBroker` remain permanently
backtest-only; the "future unification" this docstring originally
anticipated never happened, by design, not by omission.**
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
