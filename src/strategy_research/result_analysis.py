"""Track A (Phase 32): decomposes an already-produced
`long_horizon_validation.json` report into the per-strategy
breakdowns needed to explain WHY a result looks the way it does --
fold-return distribution, regime-conditional performance (over the
walk-forward TRAIN+VALIDATION region only, which is the only region
this report's schema carries a `regime_trend_state` label for),
gross-to-net cost drag, and (when present -- older reports predate
these fields) drawdown-duration and per-security concentration.

Pure functions over the report's own JSON structure (no re-running of
any backtest, no repository/network access) -- this module can run
against a report file alone, from any machine that has one, which is
why it exists separately from `scripts/run_long_horizon_validation.py`
itself (that script needs a live DuckDB catalog; this one only needs
its output).

Deliberately does NOT compute: Signal IC (`strategy_research.
signal_ic` needs a live `DataRepository` to re-score securities,
not just this report) or true upside/downside capture ratios (needs
the full portfolio value time series, which this report's schema does
not persist -- only summary statistics per fold/held-out run). Both
are called out as such in the produced summary rather than silently
omitted or approximated.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _stdev(values: list[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = _mean(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5


@dataclass(frozen=True)
class FoldDistributionSummary:
    fold_count: int
    win_rate: Optional[float]
    mean_return: Optional[float]
    median_return: Optional[float]
    stdev_return: Optional[float]
    worst_return: Optional[float]
    best_return: Optional[float]
    mean_sharpe: Optional[float]


def fold_distribution_summary(folds: list[dict]) -> FoldDistributionSummary:
    """`folds` is the report's `results[strategy]["walk_forward"]["folds"]`
    list -- each entry's `net.cumulative_return`/`net.sharpe_ratio` come
    from that fold's own `PerformanceReport`."""
    returns = [f["net"]["cumulative_return"] for f in folds]
    sharpes = [f["net"]["sharpe_ratio"] for f in folds]
    wins = sum(1 for r in returns if r > 0)
    return FoldDistributionSummary(
        fold_count=len(folds),
        win_rate=(wins / len(folds)) if folds else None,
        mean_return=_mean(returns),
        # `statistics.median` (not `sorted(...)[len//2]`, which is the
        # upper element on an even-length list, not the true median --
        # ADR-0117), matching `walk_forward_evaluation.py`'s own
        # convention for the same statistic.
        median_return=(statistics.median(returns) if returns else None),
        stdev_return=_stdev(returns),
        worst_return=(min(returns) if returns else None),
        best_return=(max(returns) if returns else None),
        mean_sharpe=_mean(sharpes),
    )


@dataclass(frozen=True)
class RegimeBucket:
    regime: str
    fold_count: int
    win_rate: Optional[float]
    mean_return: Optional[float]


def regime_conditional_summary(folds: list[dict]) -> tuple[RegimeBucket, ...]:
    """Buckets `folds` by each fold's own `regime_trend_state` (as
    already classified by `RegimeDetector` when the walk-forward ran)
    and reports win rate/mean return per bucket. Covers the
    TRAIN+VALIDATION walk-forward region only -- this report's schema
    does not carry a regime label for the held-out TEST result (a
    single continuous backtest, not fold-based), so this function
    cannot and does not say anything about regime-conditional TEST
    performance."""
    by_regime: dict[str, list[dict]] = {}
    for fold in folds:
        by_regime.setdefault(fold["regime_trend_state"], []).append(fold)
    buckets = []
    for regime, group in sorted(by_regime.items()):
        returns = [f["net"]["cumulative_return"] for f in group]
        wins = sum(1 for r in returns if r > 0)
        buckets.append(
            RegimeBucket(
                regime=regime, fold_count=len(group),
                win_rate=(wins / len(group)) if group else None,
                mean_return=_mean(returns),
            )
        )
    return tuple(buckets)


@dataclass(frozen=True)
class CostDragSummary:
    gross_cumulative_return: float
    net_cumulative_return: float
    cost_drag: float  # gross - net, in return-fraction terms
    turnover: float
    total_transaction_cost: float


def cost_drag_summary(perf: dict) -> CostDragSummary:
    """`perf` is a `{"gross": {...}, "net": {...}}` block (either a
    fold's or `held_out_test`'s)."""
    gross = perf["gross"]["cumulative_return"]
    net = perf["net"]["cumulative_return"]
    return CostDragSummary(
        gross_cumulative_return=gross,
        net_cumulative_return=net,
        cost_drag=gross - net,
        turnover=perf["net"]["turnover"],
        total_transaction_cost=perf["net"]["total_transaction_cost"],
    )


@dataclass(frozen=True)
class BenchmarkComparisonSummary:
    strategy_net_cumulative_return: float
    benchmark_cumulative_return: Optional[float]
    excess_return: Optional[float]
    strategy_cagr: float
    benchmark_cagr: Optional[float]
    annualized_excess_return: Optional[float]
    strategy_max_drawdown: float
    benchmark_max_drawdown: Optional[float]


def benchmark_comparison_summary(net_perf: dict) -> BenchmarkComparisonSummary:
    """`net_perf` is a `PerformanceReport`-shaped dict (e.g.
    `held_out_test["net"]`). Benchmark fields are `None` (not
    fabricated) when `BENCHMARK_UNAVAILABLE` produced them that way in
    the original run -- passed through unchanged, never defaulted to
    0. Upside/downside capture is NOT computed here: that needs the
    full period-by-period return series for both strategy and
    benchmark, which this report's schema does not persist (only
    start/end summary statistics per fold/held-out run)."""
    return BenchmarkComparisonSummary(
        strategy_net_cumulative_return=net_perf["cumulative_return"],
        benchmark_cumulative_return=net_perf.get("benchmark_cumulative_return"),
        excess_return=net_perf.get("excess_return"),
        strategy_cagr=net_perf["cagr"],
        benchmark_cagr=net_perf.get("benchmark_cagr"),
        annualized_excess_return=net_perf.get("annualized_excess_return"),
        strategy_max_drawdown=net_perf["max_drawdown"],
        benchmark_max_drawdown=net_perf.get("benchmark_max_drawdown"),
    )


@dataclass(frozen=True)
class StrategyAnalysis:
    strategy_name: str
    fold_distribution: FoldDistributionSummary
    regime_conditional: tuple[RegimeBucket, ...]
    walk_forward_cost_drag: Optional[CostDragSummary]
    held_out_cost_drag: Optional[CostDragSummary]
    held_out_benchmark_comparison: Optional[BenchmarkComparisonSummary]
    held_out_drawdown_duration_days: Optional[int]  # None: absent field OR genuinely no drawdown
    held_out_drawdown_field_present: bool  # False -> report predates this field, not "no drawdown"
    held_out_concentration_present: bool  # False -> report predates concentration analysis
    pbo_probability: Optional[float]
    deflated_sharpe_ratio: Optional[float]
    positive_fold_ratio: Optional[float]
    evidence_level: Optional[str]
    evidence_reason: Optional[str]


def analyze_strategy(name: str, result: dict) -> StrategyAnalysis:
    wf = result.get("walk_forward", {})
    folds = wf.get("folds", [])
    held_out = result.get("held_out_test")
    evidence = result.get("evidence_assessment", {})

    held_out_dd_present = bool(held_out) and "max_drawdown_duration_days" in held_out.get("net", {})
    held_out_concentration_present = bool(held_out) and "concentration" in held_out

    return StrategyAnalysis(
        strategy_name=name,
        fold_distribution=fold_distribution_summary(folds),
        regime_conditional=regime_conditional_summary(folds),
        walk_forward_cost_drag=(
            cost_drag_summary({"gross": _aggregate_gross(folds), "net": _aggregate_net(folds)})
            if folds else None
        ),
        held_out_cost_drag=(cost_drag_summary(held_out) if held_out else None),
        held_out_benchmark_comparison=(
            benchmark_comparison_summary(held_out["net"]) if held_out else None
        ),
        held_out_drawdown_duration_days=(
            held_out["net"].get("max_drawdown_duration_days") if held_out_dd_present else None
        ),
        held_out_drawdown_field_present=held_out_dd_present,
        held_out_concentration_present=held_out_concentration_present,
        pbo_probability=evidence.get("pbo_probability"),
        deflated_sharpe_ratio=evidence.get("deflated_sharpe_ratio"),
        positive_fold_ratio=evidence.get("positive_fold_ratio"),
        evidence_level=evidence.get("level"),
        evidence_reason=evidence.get("reason"),
    )


def _aggregate_gross(folds: list[dict]) -> dict:
    # Average gross cumulative_return across folds -- a rough
    # walk-forward-level cost-drag summary, not a claim of a properly
    # compounded multi-fold return (folds are independent, non-
    # contiguous test windows, so they cannot be chained).
    returns = [f["gross"]["cumulative_return"] for f in folds]
    turnovers = [f["gross"].get("turnover", 0.0) for f in folds]
    return {"cumulative_return": _mean(returns) or 0.0, "turnover": _mean(turnovers) or 0.0}


def _aggregate_net(folds: list[dict]) -> dict:
    returns = [f["net"]["cumulative_return"] for f in folds]
    turnovers = [f["net"].get("turnover", 0.0) for f in folds]
    costs = [f["net"].get("total_transaction_cost", 0.0) for f in folds]
    return {
        "cumulative_return": _mean(returns) or 0.0,
        "turnover": _mean(turnovers) or 0.0,
        "total_transaction_cost": sum(costs),
    }


def analyze_report(report: dict) -> tuple[StrategyAnalysis, ...]:
    results = report.get("results", {})
    return tuple(analyze_strategy(name, result) for name, result in sorted(results.items()))
