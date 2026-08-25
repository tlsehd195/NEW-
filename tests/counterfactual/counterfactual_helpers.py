"""Shared test helpers for the Phase 10 Counterfactual/Attribution test suite."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from data_infra.calendar import US_EQUITY
from data_infra.enums import InstrumentType, SecurityStatus
from data_infra.models import PriceBar, Provenance, SecurityMaster
from data_infra.repository import InMemoryDataRepository

from backtest.enums import ExperimentResult
from backtest.experiment import ExperimentRecord
from backtest.metrics import PerformanceReport


def utc(year: int, month: int, day: int, hour: int = 20, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_bars_repo(closes: dict[date, float], security_id: str = "AAA") -> InMemoryDataRepository:
    bars = []
    for i, (d, close) in enumerate(sorted(closes.items())):
        bars.append(
            PriceBar(
                security_id=security_id, timestamp=utc(d.year, d.month, d.day, 0), open=close,
                high=close * 1.01, low=close * 0.99, close=close, volume=100_000.0,
                available_time=utc(d.year, d.month, d.day, 20), ingestion_time=utc(d.year, d.month, d.day, 20),
                provenance=Provenance(
                    source="test", source_dataset="test_ds", source_record_id=f"{security_id}-{i}",
                    retrieved_at=utc(d.year, d.month, d.day, 20), data_version=f"v{i}",
                ),
            )
        )
    sec = SecurityMaster(
        security_id=security_id, ticker=security_id, exchange="NASDAQ", currency="USD",
        company_id="C1", instrument_type=InstrumentType.EQUITY,
        valid_from=utc(2020, 1, 1), status=SecurityStatus.ACTIVE,
    )
    return InMemoryDataRepository(bars=bars, securities=[sec], calendars={"US_EQUITY": US_EQUITY})


def make_performance_report(
    *,
    cumulative_return: float = 0.10,
    total_transaction_cost: float = 100.0,
    benchmark_cumulative_return: Optional[float] = 0.06,
    turnover: float = 0.5,
) -> PerformanceReport:
    excess = None if benchmark_cumulative_return is None else cumulative_return - benchmark_cumulative_return
    return PerformanceReport(
        cumulative_return=cumulative_return, cagr=cumulative_return, annualized_volatility=0.2,
        sharpe_ratio=1.0, sortino_ratio=1.2, max_drawdown=-0.05, calmar_ratio=2.0, turnover=turnover,
        total_transaction_cost=total_transaction_cost, win_rate=0.6, avg_trade_return=0.01,
        benchmark_cumulative_return=benchmark_cumulative_return,
        benchmark_cagr=benchmark_cumulative_return, benchmark_max_drawdown=-0.03,
        excess_return=excess, annualized_excess_return=excess,
    )


def make_experiment_record(
    *,
    experiment_id: str = "BT-000001",
    initial_capital: float = 50_000.0,
    metrics: Optional[PerformanceReport] = None,
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id, strategy_version="v1", data_version=("v1",), feature_version=None,
        configuration_version="cfg-v1", start_date=utc(2024, 1, 2), end_date=utc(2024, 6, 1),
        initial_capital=initial_capital, transaction_cost_config={}, slippage_config={}, benchmark={},
        metrics=metrics or make_performance_report(), code_version="test", seed=42,
        result=ExperimentResult.PASSED, timestamp=utc(2024, 6, 1),
    )
