"""Baseline vs. Benchmark comparison reporting.

See docs/specifications/PHASE-4-baseline-models-and-storage.md section
10. The purpose of this report is explicitly *not* to declare a winner by
return alone (PROJECT_MASTER_PLAN.md section 1.1: "백테스트 성능이 높다는
이유만으로 모델을 채택하지 않는다", carried forward from Phase 2 spec
section 11's "no single metric is a pass/fail signal"). This module only
assembles and formats numbers that `backtest.metrics.PerformanceReport`
and `backtest.benchmark.BenchmarkResult` already computed; it introduces
no new metric and no accept/reject gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from backtest.benchmark import BenchmarkResult
from backtest.metrics import PerformanceReport

from baseline.runner import BaselineRunResult


@dataclass(frozen=True)
class BaselineComparisonReport:
    label: str
    experiment_id: str
    strategy_version: str
    is_valid_performance: bool
    performance: PerformanceReport
    benchmark: Optional[BenchmarkResult]
    integrity_issue_count: int


def build_comparison_report(run: BaselineRunResult) -> BaselineComparisonReport:
    result = run.backtest_result
    return BaselineComparisonReport(
        label=run.label,
        experiment_id=result.experiment.experiment_id,
        strategy_version=result.experiment.strategy_version,
        is_valid_performance=result.is_valid_performance,
        performance=result.performance,
        benchmark=result.benchmark,
        integrity_issue_count=len(result.integrity.issues),
    )


_METRIC_ROWS: tuple[tuple[str, str], ...] = (
    ("cumulative_return", "Cumulative Return"),
    ("cagr", "CAGR"),
    ("annualized_volatility", "Annualized Volatility"),
    ("sharpe_ratio", "Sharpe Ratio"),
    ("sortino_ratio", "Sortino Ratio"),
    ("max_drawdown", "Max Drawdown"),
    ("calmar_ratio", "Calmar Ratio"),
    ("turnover", "Turnover"),
    ("total_transaction_cost", "Total Transaction Cost"),
    ("win_rate", "Win Rate"),
    ("avg_trade_return", "Avg Trade Return"),
    ("excess_return", "Excess Return vs Benchmark"),
    ("annualized_excess_return", "Annualized Excess Return"),
)


def format_report_text(report: BaselineComparisonReport) -> str:
    lines = [
        f"Baseline: {report.label}  (experiment={report.experiment_id}, "
        f"strategy_version={report.strategy_version})",
        f"  is_valid_performance = {report.is_valid_performance} "
        f"(integrity issues: {report.integrity_issue_count})",
    ]
    for field, display in _METRIC_ROWS:
        value = getattr(report.performance, field)
        lines.append(f"  {display:<32} {value:.6f}" if value is not None else f"  {display:<32} None")
    if report.benchmark is not None:
        lines.append(
            f"  benchmark_id={report.benchmark.benchmark_id} "
            f"return_type={report.benchmark.return_type.value} "
            f"benchmark_cumulative_return={report.performance.benchmark_cumulative_return}"
        )
    else:
        lines.append("  (no benchmark configured for this run)")
    return "\n".join(lines)


def compare_reports(reports: Sequence[BaselineComparisonReport]) -> str:
    """A side-by-side table across multiple baselines (e.g. Buy & Hold vs
    Simple Momentum), each already compared against the same benchmark
    individually. Deliberately does not rank or select a "best" row --
    per this phase's purpose (Phase 4 spec section 12), the report exists
    to let a human compare, not to auto-select a winner."""
    if not reports:
        return "(no baseline reports)"

    header = ["metric"] + [r.label for r in reports]
    rows: list[list[str]] = [header]
    for field, display in _METRIC_ROWS:
        row = [display]
        for r in reports:
            value = getattr(r.performance, field)
            row.append(f"{value:.6f}" if value is not None else "None")
        rows.append(row)
    rows.append(["is_valid_performance"] + [str(r.is_valid_performance) for r in reports])

    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    lines = []
    for row in rows:
        lines.append("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))
    return "\n".join(lines)
