"""Paper Trading Performance Report -- Phase 18. Closes the Phase 17
Production Safety Review's most significant gap: Paper Trading had no
performance evaluation beyond raw PnL (`monitoring.collectors.
collect_account`, Phase 17). "Paper return > benchmark" is never
sufficient on its own (`docs/operations/PRODUCTION-READINESS-MATRIX.md`
"Benchmark" row) -- this module exists to make every other metric a
first-class, honestly-computed citizen instead.

Reuses, never duplicates:
- `backtest.portfolio.PortfolioAccounting` (Phase 2) for the equity
  curve and turnover -- via `PaperBrokerAdapter.accounting` (Phase 18
  addition, a read-only property exposing the same instance the
  adapter already uses internally; no new accounting system).
- `trade_journal.models.TradeRecord` (Phase 3) for trade-level economics
  (realized PnL, transaction cost, slippage, win rate) -- the
  authoritative, persisted, provenance-tagged record, not
  `PortfolioAccounting.closed_trades`'s own separate bookkeeping, to
  avoid two competing "trade list" sources of truth.
- `backtest.benchmark.BenchmarkEngine`/`BenchmarkResult` (Phase 2) for
  the S&P 500 Buy & Hold comparison, over the identical
  period/capital/cost assumptions as this report's own portfolio, by
  construction (same reasoning as the historical Backtest engine's own
  benchmark comparison).

Does NOT reuse `backtest.metrics`'s public `sharpe_ratio`/
`sortino_ratio`/`cagr`/`calmar_ratio`/`compute_performance_report`
directly -- those functions collapse every insufficient-data or
division-by-zero case to a fabricated `0.0`, which this phase's
explicit integrity requirement forbids ("필요한 값이 없으면 0을
임의로 넣지 않는다"). Modifying `backtest.metrics` itself was rejected
(see `docs/decisions/ADR-0024-paper-performance-and-validation.md`
decision 1) because Phase 2/4's own tests may depend on that exact
fallback behavior, and changing it would risk breaking historical
Backtest reporting outside this phase's scope. Every metric here is
`Optional[float]`, paired with an explicit reason string in
`PaperPerformanceReport.reasons` whenever it is `None` -- never a
guessed number standing in for missing evidence.

Explicit definitions (instruction section 4):
- Return frequency: whatever frequency the caller's `equity_history`
  points actually are (this module does not resample) -- the caller
  states this as `PaperPerformanceConfig.periods_per_year` (default
  252, calendar trading days/year, the same default
  `backtest.metrics` already uses for a daily series).
- Risk-free rate: `PaperPerformanceConfig.risk_free_rate`, default
  `0.0` -- no risk-free assumption is embedded beyond this explicit,
  overridable parameter (matches `backtest.metrics.sharpe_ratio`'s own
  default).
- Downside deviation: population (ddof=0) standard deviation of
  `min(0.0, excess_return)` across all periods -- matches
  `backtest.metrics.sortino_ratio`'s existing convention exactly (an
  intentional ddof asymmetry against Sharpe's ddof=1 sample standard
  deviation that already exists in Phase 2, not newly introduced here).
- Drawdown: peak-to-trough decline of the equity curve, computed by
  `backtest.metrics.compute_max_drawdown` (Phase 2, reused unchanged --
  a pure function with no zero-fallback ambiguity of its own; the
  ambiguity this module avoids is calling it on too little data, not
  the function itself).
- Zero volatility -> Sharpe is `None`, reason `"zero_volatility"`.
- Zero downside deviation -> Sortino is `None`, reason
  `"zero_downside_deviation"`.
- Zero max drawdown -> Calmar is `None`, reason `"zero_drawdown"`
  (division by zero is undefined, not "infinite skill").
- Fewer than `PaperPerformanceConfig.min_periods_for_ratios` equity
  points -> every equity-curve-based metric is `None`, reason
  `"insufficient_data"`. Default `5`, reusing the exact precedent
  `risk.config.RiskConfig.min_history_for_volatility` already
  established in this codebase (not a newly invented number).
- Zero closed trades -> `win_rate`/`avg_trade_return` are `None`,
  reason `"insufficient_data"` (a fabricated `0.0` would misleadingly
  read as "0% win rate" rather than "no trades happened yet").

Deterministic: no `random`, no `datetime.now()`/`utcnow()` -- every
timestamp this module ever sees is caller-supplied
(`PaperPerformanceReport.evaluated_at`, `period_start`, `period_end`).
The same `(equity_history, trades, config, benchmark)` always produces
a byte-identical report (`tests/broker/paper/test_paper_performance.py::
TestReproducibility`).

See docs/specifications/PHASE-18-paper-performance-and-validation.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from data_infra.versioning import compute_data_version

from backtest.benchmark import BenchmarkResult
from backtest.metrics import compute_max_drawdown

from trade_journal.enums import TradeProvenance
from trade_journal.models import TradeRecord

_DAYS_PER_YEAR = 365.25


def _finite(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class PaperPerformanceConfig:
    version: str = "paper_performance_config_v1"

    # -- annualization / risk-free assumption, both explicit and
    # overridable -- never silently embedded in a formula --
    risk_free_rate: float = 0.0
    periods_per_year: int = 252
    return_frequency: str = "DAILY"  # documents what periods_per_year assumes; this module does not resample

    # -- minimum equity-curve observations before any ratio (volatility/
    # Sharpe/Sortino/Calmar) is computed at all; reuses the exact
    # precedent risk.config.RiskConfig.min_history_for_volatility
    # already established in this codebase, not a new number --
    min_periods_for_ratios: int = 5

    def __post_init__(self) -> None:
        if self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        if self.return_frequency not in ("DAILY", "WEEKLY", "MONTHLY"):
            raise ValueError("return_frequency must be one of DAILY/WEEKLY/MONTHLY")
        if self.min_periods_for_ratios < 2:
            raise ValueError("min_periods_for_ratios must be >= 2 -- a sample stdev needs at least 2 points")

    def configuration_version(self) -> str:
        from dataclasses import asdict

        return compute_data_version(asdict(self))


DEFAULT_PAPER_PERFORMANCE_CONFIG = PaperPerformanceConfig()


@dataclass(frozen=True)
class BenchmarkComparison:
    """`status="BENCHMARK_UNAVAILABLE"` whenever no `BenchmarkResult`
    was supplied (e.g. `backtest.benchmark.BenchmarkEngine.compute`
    returned `None` because no benchmark price data exists in this
    repository -- true for every environment today, since no real S&P
    500 data has been ingested, ADR-0005). A report computed without a
    benchmark must never be read as "beat the S&P 500" -- this
    dataclass makes that state impossible to skip past silently."""

    status: str  # "AVAILABLE" | "BENCHMARK_UNAVAILABLE"
    benchmark_id: Optional[str] = None
    benchmark_return_type: Optional[str] = None
    benchmark_cumulative_return: Optional[float] = None
    benchmark_cagr: Optional[float] = None
    benchmark_max_drawdown: Optional[float] = None
    excess_return: Optional[float] = None
    annualized_excess_return: Optional[float] = None

    def __post_init__(self) -> None:
        if self.status not in ("AVAILABLE", "BENCHMARK_UNAVAILABLE"):
            raise ValueError("BenchmarkComparison.status must be AVAILABLE or BENCHMARK_UNAVAILABLE")
        if self.status == "BENCHMARK_UNAVAILABLE" and self.benchmark_cumulative_return is not None:
            raise ValueError("BENCHMARK_UNAVAILABLE must not carry a benchmark_cumulative_return")


_UNAVAILABLE_BENCHMARK = BenchmarkComparison(status="BENCHMARK_UNAVAILABLE")


@dataclass(frozen=True)
class PaperPerformanceReport:
    report_id: str
    paper_session_id: str
    evaluated_at: datetime
    period_start: Optional[datetime]
    period_end: Optional[datetime]

    total_return: Optional[float]
    cagr: Optional[float]
    volatility: Optional[float]
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    calmar_ratio: Optional[float]
    max_drawdown: Optional[float]
    turnover: Optional[float]

    total_transaction_cost: Optional[float]
    total_slippage: Optional[float]
    num_trades: int
    win_rate: Optional[float]
    avg_trade_return: Optional[float]
    realized_pnl: Optional[float]

    benchmark: BenchmarkComparison

    configuration_version: str
    provenance: TradeProvenance = TradeProvenance.PAPER_TRADING
    strategy_version: str = "unknown"
    model_version: Optional[str] = None
    experiment_id: Optional[str] = None

    # `reasons[metric_name]` explains every `None` above -- e.g.
    # `{"sharpe_ratio": "zero_volatility"}`. A metric with a real
    # (possibly zero) value never appears here.
    reasons: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.report_id:
            raise ValueError("PaperPerformanceReport.report_id must not be empty")
        if not self.paper_session_id:
            raise ValueError("PaperPerformanceReport.paper_session_id must not be empty")
        _require_aware("PaperPerformanceReport.evaluated_at", self.evaluated_at)
        if self.period_start is not None:
            _require_aware("PaperPerformanceReport.period_start", self.period_start)
        if self.period_end is not None:
            _require_aware("PaperPerformanceReport.period_end", self.period_end)
        if self.num_trades < 0:
            raise ValueError("PaperPerformanceReport.num_trades must not be negative")


def _sample_stdev(values: Sequence[float]) -> float:
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return variance**0.5


def _population_stdev(values: Sequence[float]) -> float:
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance**0.5


def compute_returns(values: Sequence[float]) -> list[float]:
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] != 0]


def _cagr(initial_value: float, final_value: float, start: datetime, end: datetime) -> Optional[str]:
    """Returns None on success (caller computes the value), or a reason
    string if CAGR is undefined -- never a fabricated 0.0."""
    years = (end - start).days / _DAYS_PER_YEAR
    if years <= 0:
        return "insufficient_data"
    if initial_value <= 0:
        return "undefined_nonpositive_initial_value"
    return None


def compute_paper_performance_report(
    *,
    report_id: str,
    paper_session_id: str,
    equity_history: Sequence[tuple[datetime, float]],
    trades: Sequence[TradeRecord],
    evaluated_at: datetime,
    config: PaperPerformanceConfig = DEFAULT_PAPER_PERFORMANCE_CONFIG,
    benchmark: Optional[BenchmarkResult] = None,
    turnover: Optional[float] = None,
    strategy_version: str = "unknown",
    model_version: Optional[str] = None,
    experiment_id: Optional[str] = None,
) -> PaperPerformanceReport:
    """`equity_history` -- an already-point-in-time-filtered sequence of
    `(as_of_time, portfolio_value)`, typically
    `[(p.as_of_time, p.portfolio_value) for p in adapter.accounting.
    value_series]` after the caller has called `adapter.accounting.
    mark_to_market(prices, as_of)` at each valuation point. `trades` --
    `TradeRecord`s from `trade_journal.repository.TradeJournalRepository.
    list_trades(provenance=TradeProvenance.PAPER_TRADING, ...)` for this
    session, never re-derived from `PortfolioAccounting.closed_trades`
    (a second, competing trade list) to keep the Trade Journal the one
    authoritative source of trade-level economics. `turnover` --
    typically `adapter.accounting.turnover()` (Phase 2, reused
    unchanged) -- passed explicitly rather than recomputed here since
    this module holds no `PortfolioAccounting` reference of its own;
    `None` (the caller never supplied one) is a distinct, honestly
    different reason from any computed value, including a genuine
    `0.0`."""
    _require_aware("evaluated_at", evaluated_at)

    reasons: dict[str, str] = {}
    ordered = sorted(equity_history, key=lambda pair: pair[0])
    values = [v for _, v in ordered]

    period_start = ordered[0][0] if ordered else None
    period_end = ordered[-1][0] if ordered else None

    if turnover is None:
        reasons["turnover"] = "not_supplied"

    if len(values) < 2:
        total_return = cagr_value = volatility = sharpe = sortino = max_dd = calmar = None
        for name in ("total_return", "cagr", "volatility", "sharpe_ratio", "sortino_ratio", "max_drawdown", "calmar_ratio"):
            reasons[name] = "insufficient_data"
    else:
        total_return = values[-1] / values[0] - 1.0 if values[0] != 0 else None
        if total_return is None:
            reasons["total_return"] = "undefined_nonpositive_initial_value"

        cagr_reason = _cagr(values[0], values[-1], period_start, period_end)
        if cagr_reason is not None:
            cagr_value = None
            reasons["cagr"] = cagr_reason
        else:
            years = (period_end - period_start).days / _DAYS_PER_YEAR
            cagr_value = (values[-1] / values[0]) ** (1.0 / years) - 1.0

        returns = compute_returns(values)
        if len(values) < config.min_periods_for_ratios or len(returns) < 2:
            volatility = sharpe = sortino = None
            reasons["volatility"] = reasons["sharpe_ratio"] = reasons["sortino_ratio"] = "insufficient_data"
        else:
            volatility = _sample_stdev(returns) * (config.periods_per_year**0.5)

            period_rf = config.risk_free_rate / config.periods_per_year
            excess = [r - period_rf for r in returns]
            mean_excess = sum(excess) / len(excess)
            sharpe_std = _sample_stdev(excess)
            if sharpe_std == 0:
                sharpe = None
                reasons["sharpe_ratio"] = "zero_volatility"
            else:
                sharpe = (mean_excess / sharpe_std) * (config.periods_per_year**0.5)

            downside = [min(0.0, r) for r in excess]
            downside_std = _population_stdev(downside)
            if downside_std == 0:
                sortino = None
                reasons["sortino_ratio"] = "zero_downside_deviation"
            else:
                sortino = (mean_excess / downside_std) * (config.periods_per_year**0.5)

        max_dd = compute_max_drawdown(values)
        if not _finite(max_dd):
            max_dd = None
            reasons["max_drawdown"] = "undefined"

        if cagr_value is None or max_dd is None:
            calmar = None
            reasons.setdefault("calmar_ratio", "insufficient_data")
        elif max_dd == 0:
            calmar = None
            reasons["calmar_ratio"] = "zero_drawdown"
        else:
            calmar = cagr_value / abs(max_dd)

    closed_trades = [t for t in trades if t.realized_pnl is not None]
    if not trades:
        num_trades = 0
        win_rate = avg_trade_return = realized_pnl = None
        total_transaction_cost = total_slippage = None
        reasons["win_rate"] = reasons["avg_trade_return"] = reasons["realized_pnl"] = "insufficient_data"
        reasons["total_transaction_cost"] = reasons["total_slippage"] = "insufficient_data"
    else:
        num_trades = len(trades)
        total_transaction_cost = sum(t.transaction_cost for t in trades)
        total_slippage = sum(t.slippage for t in trades)
        if not closed_trades:
            win_rate = avg_trade_return = realized_pnl = None
            reasons["win_rate"] = reasons["avg_trade_return"] = reasons["realized_pnl"] = "insufficient_data"
        else:
            win_rate = sum(1 for t in closed_trades if t.realized_pnl > 0) / len(closed_trades)
            realized_return_trades = [t for t in closed_trades if t.realized_return is not None]
            avg_trade_return = (
                sum(t.realized_return for t in realized_return_trades) / len(realized_return_trades)
                if realized_return_trades else None
            )
            if avg_trade_return is None:
                reasons["avg_trade_return"] = "insufficient_data"
            realized_pnl = sum(t.realized_pnl for t in closed_trades)

    if benchmark is None:
        comparison = _UNAVAILABLE_BENCHMARK
    else:
        excess_return = total_return - benchmark.cumulative_return if total_return is not None else None
        annualized_excess = cagr_value - benchmark.cagr if cagr_value is not None else None
        comparison = BenchmarkComparison(
            status="AVAILABLE", benchmark_id=benchmark.benchmark_id,
            benchmark_return_type=benchmark.return_type.value if hasattr(benchmark.return_type, "value") else str(benchmark.return_type),
            benchmark_cumulative_return=benchmark.cumulative_return, benchmark_cagr=benchmark.cagr,
            benchmark_max_drawdown=benchmark.max_drawdown, excess_return=excess_return,
            annualized_excess_return=annualized_excess,
        )

    return PaperPerformanceReport(
        report_id=report_id, paper_session_id=paper_session_id, evaluated_at=evaluated_at,
        period_start=period_start, period_end=period_end,
        total_return=total_return, cagr=cagr_value, volatility=volatility, sharpe_ratio=sharpe,
        sortino_ratio=sortino, calmar_ratio=calmar, max_drawdown=max_dd, turnover=turnover,
        total_transaction_cost=total_transaction_cost, total_slippage=total_slippage,
        num_trades=num_trades, win_rate=win_rate, avg_trade_return=avg_trade_return, realized_pnl=realized_pnl,
        benchmark=comparison, configuration_version=config.configuration_version(),
        strategy_version=strategy_version, model_version=model_version, experiment_id=experiment_id,
        reasons=reasons,
    )
