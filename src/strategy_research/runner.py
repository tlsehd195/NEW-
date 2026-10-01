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
from backtest.risk_free import RiskFreeRates
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
    point_in_time_universe: Optional[str] = None,
    settle_after_missing_checkpoints: int = 5,
    risk_free: Optional[RiskFreeRates] = None,
    cash_interest: Optional[RiskFreeRates] = None,
) -> GrossNetResult:
    """Runs the SAME strategy specification twice against the SAME data
    window: once under `ZERO_TRANSACTION_COST_MODEL`/`ZERO_SLIPPAGE_MODEL`
    (gross) and once under the project's real
    `DEFAULT_TRANSACTION_COST_MODEL`/`DEFAULT_SLIPPAGE_MODEL` (net).
    `strategy_factory` must return a FRESH strategy instance each call
    (a `Strategy` implementation in this codebase holds internal
    rebalance-timing state -- reusing one instance across two runs would
    let the second run's timing depend on the first run's, breaking
    reproducibility).

    `point_in_time_universe` (ADR-0224): the name of a dynamic universe
    in `repository` (e.g. `SP500_INDEX_HISTORICAL`). The strategy then
    sees only that date's members, and a held name with no bar for
    `settle_after_missing_checkpoints` checkpoints is settled to cash.
    `security_ids` should list every name that is ever a member.

    `risk_free` (ADR-0227): when given, Sharpe/Sortino use the average
    3-month T-bill yield over this window; when None they use 0%.

    `cash_interest` (ADR-0229): when given, idle cash earns the daily
    3-month T-bill yield in both runs; when None cash earns 0%."""
    universe_kwargs = {}
    if point_in_time_universe is not None:
        universe_kwargs = {
            "universe": (market, point_in_time_universe),
            "restrict_strategy_to_universe": True,
            "settle_after_missing_checkpoints": settle_after_missing_checkpoints,
        }
    risk_free_rate = risk_free.average_annual_rate(start_date, end_date) if risk_free is not None else 0.0
    gross_config = BacktestConfig(
        market=market, start_date=start_date, end_date=end_date, initial_capital=initial_capital,
        security_ids=tuple(security_ids), benchmark_id=benchmark_id,
        cost_model=ZERO_TRANSACTION_COST_MODEL, slippage_model=ZERO_SLIPPAGE_MODEL,
        risk_free_rate=risk_free_rate, cash_interest=cash_interest, code_version=code_version,
        **universe_kwargs,
    )
    net_config = BacktestConfig(
        market=market, start_date=start_date, end_date=end_date, initial_capital=initial_capital,
        security_ids=tuple(security_ids), benchmark_id=benchmark_id,
        cost_model=DEFAULT_TRANSACTION_COST_MODEL, slippage_model=DEFAULT_SLIPPAGE_MODEL,
        risk_free_rate=risk_free_rate, cash_interest=cash_interest, code_version=code_version,
        **universe_kwargs,
    )

    gross_result = BacktestEngine(repository, gross_config, strategy_factory()).run()
    net_result = BacktestEngine(repository, net_config, strategy_factory()).run()

    strategy_name = type(strategy_factory()).__name__
    return GrossNetResult(strategy_name=strategy_name, gross=gross_result, net=net_result)
