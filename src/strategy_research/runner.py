"""Strategy research runner: wires the existing, unmodified
`backtest.engine.BacktestEngine` to run one candidate strategy twice --
gross (zero transaction cost/slippage) and net (the project's real
default cost/slippage models) -- against the configured benchmark
(instruction section 22).

No new portfolio accounting, no new cost model, no new benchmark
engine -- every computation happens inside `BacktestEngine.run()`
exactly as it does for `BuyAndHoldStrategy`/`SimpleMomentumStrategy`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional, Sequence

from backtest.costs import (
    DEFAULT_SLIPPAGE_MODEL,
    DEFAULT_TRANSACTION_COST_MODEL,
    ZERO_SLIPPAGE_MODEL,
    ZERO_TRANSACTION_COST_MODEL,
)
from backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from backtest.strategy import Strategy
from data_infra.repository import DataRepository


@dataclass(frozen=True)
class GrossNetResult:
    strategy_name: str
    gross: BacktestResult
    net: BacktestResult


def run_gross_and_net(
    repository: DataRepository,
    strategy_factory: Callable[[], Strategy],
    security_ids: Sequence[str],
    *,
    start_date: date,
    end_date: date,
    initial_capital: float,
    benchmark_id: Optional[str] = None,
    market: str = "US_EQUITY",
    code_version: str = "phase23_strategy_research",
) -> GrossNetResult:
    """Runs the SAME strategy specification twice against the SAME data
    window: once under `ZERO_TRANSACTION_COST_MODEL`/`ZERO_SLIPPAGE_MODEL`
    (gross) and once under the project's real
    `DEFAULT_TRANSACTION_COST_MODEL`/`DEFAULT_SLIPPAGE_MODEL` (net).
    `strategy_factory` must return a FRESH strategy instance each call
    (a `Strategy` implementation in this codebase holds internal
    rebalance-timing state -- reusing one instance across two runs would
    let the second run's timing depend on the first run's, breaking
    reproducibility)."""
    gross_config = BacktestConfig(
        market=market, start_date=start_date, end_date=end_date, initial_capital=initial_capital,
        security_ids=tuple(security_ids), benchmark_id=benchmark_id,
        cost_model=ZERO_TRANSACTION_COST_MODEL, slippage_model=ZERO_SLIPPAGE_MODEL,
        code_version=code_version,
    )
    net_config = BacktestConfig(
        market=market, start_date=start_date, end_date=end_date, initial_capital=initial_capital,
        security_ids=tuple(security_ids), benchmark_id=benchmark_id,
        cost_model=DEFAULT_TRANSACTION_COST_MODEL, slippage_model=DEFAULT_SLIPPAGE_MODEL,
        code_version=code_version,
    )

    gross_result = BacktestEngine(repository, gross_config, strategy_factory()).run()
    net_result = BacktestEngine(repository, net_config, strategy_factory()).run()

    strategy_name = type(strategy_factory()).__name__
    return GrossNetResult(strategy_name=strategy_name, gross=gross_result, net=net_result)
