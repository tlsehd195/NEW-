"""BenchmarkEngine: computes the S&P 500 Buy & Hold comparison over the
identical period/capital/cost assumptions as a strategy backtest.

See docs/specifications/PHASE-2-backtesting.md section 9.

IMPORTANT: section 9.3 of that spec raises the choice between
PRICE_RETURN and TOTAL_RETURN benchmark data as a DECISION REQUIRED, not
resolved here. This engine handles either data_infra.enums.BenchmarkReturnType
correctly and reports which one was actually used — it does not assume
one or silently prefer one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from data_infra.enums import BenchmarkReturnType
from data_infra.repository import DataRepository

from backtest.costs import TransactionCostModel
from backtest.enums import OrderSide
from backtest.metrics import cagr as compute_cagr
from backtest.metrics import compute_max_drawdown


@dataclass(frozen=True)
class BenchmarkResult:
    benchmark_id: str
    return_type: BenchmarkReturnType
    start: datetime
    end: datetime
    initial_capital: float
    final_value: float
    cumulative_return: float
    cagr: float
    max_drawdown: float
    value_series: tuple[tuple[datetime, float], ...]


class BenchmarkEngine:
    def __init__(self, cost_model: TransactionCostModel) -> None:
        self._cost_model = cost_model

    def compute(
        self,
        repository: DataRepository,
        benchmark_id: str,
        start: datetime,
        end: datetime,
        as_of_time: datetime,
        initial_capital: float,
    ) -> Optional[BenchmarkResult]:
        """`as_of_time` is evaluated post-hoc (typically the backtest's own
        end date) — this is retrospective performance reporting over an
        already-completed window, not a forward-looking decision, so
        using a later as_of_time here is not leakage (Phase 2 spec
        section 8.3's reasoning applies equally to benchmark reporting)."""
        points = sorted(
            repository.get_benchmark(benchmark_id, start, end, as_of_time=as_of_time),
            key=lambda p: p.timestamp,
        )
        if len(points) < 2:
            return None

        return_type = points[0].return_type
        entry_price = self._cost_model.apply_spread(points[0].level, OrderSide.BUY)
        if entry_price <= 0:
            return None
        units = (initial_capital - self._cost_model.fixed_per_trade) / entry_price

        value_series = tuple((p.timestamp, units * p.level) for p in points)

        exit_price = self._cost_model.apply_spread(points[-1].level, OrderSide.SELL)
        final_value = units * exit_price - self._cost_model.fixed_per_trade
        cumulative_return = final_value / initial_capital - 1.0 if initial_capital > 0 else 0.0
        cagr_value = compute_cagr(initial_capital, final_value, points[0].timestamp, points[-1].timestamp)
        max_dd = compute_max_drawdown([v for _, v in value_series])

        return BenchmarkResult(
            benchmark_id=benchmark_id,
            return_type=return_type,
            start=points[0].timestamp,
            end=points[-1].timestamp,
            initial_capital=initial_capital,
            final_value=final_value,
            cumulative_return=cumulative_return,
            cagr=cagr_value,
            max_drawdown=max_dd,
            value_series=value_series,
        )
