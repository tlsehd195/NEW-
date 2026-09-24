"""Walk-forward evaluation (Phase 25). See
docs/decisions/ADR-0031-long-horizon-walk-forward-validation.md.

Reuses, unmodified:
- `strategy_research.splits.generate_walk_forward_windows` (Phase 23) --
  the rolling-window generator itself.
- `strategy_research.runner.run_gross_and_net` (Phase 23) -- gross/net
  BacktestEngine execution.
- `regime.detector.RegimeDetector`/`make_single_point_view` (Phase 5) --
  BULL/BEAR/NEUTRAL market-regime classification, reused for the
  "which market environment was this fold's test window in" question
  (instruction section 13) instead of building a new regime model.

**Design insight that avoids touching `backtest.engine` at all**: each
fold's `run_gross_and_net` call uses `start_date=window.test_start`,
`end_date=window.test_end` -- NOT `window.train_start`. This is
deliberate, not an oversight. `BacktestConfig.start_date`/`end_date`
only bound which CHECKPOINTS the engine builds; they do not bound what
history a `Strategy.generate_orders` implementation can itself query
via `AsOfDataView.get_bars(security_id, as_of_time - lookback,
as_of_time)` -- that call reaches directly into the `DataRepository`,
independent of the backtest's own start date. A strategy with (say) a
12-month lookback therefore automatically sees genuine train-period
history the moment the test window's first checkpoint fires, with zero
special plumbing -- exactly the existing point-in-time architecture
doing what it was already built to do. `train_window_months` here is
consequently a **sanity/documentation parameter** (how much prior
history this evaluation assumes exists and checks for), not a second
backtest phase this module runs.

Each fold starts from fresh `initial_capital` (never compounds fold to
fold) -- walk-forward's purpose is checking consistency of an edge
across independent periods, not simulating one continuous multi-decade
run (instruction section 12).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Sequence

from backtest.strategy import Strategy
from data_infra.repository import DataRepository

from regime.config import RegimeConfig
from regime.detector import RegimeDetector, make_single_point_view
from regime.enums import RegimeAxis, SubjectKind

from strategy_research.runner import GrossNetResult, run_gross_and_net
from strategy_research.splits import WalkForwardWindow, generate_walk_forward_windows


@dataclass(frozen=True)
class WalkForwardFoldResult:
    fold_index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    result: GrossNetResult
    regime_trend_state: str  # "BULL" / "BEAR" / "NEUTRAL" / "UNKNOWN" -- regime.enums.TrendState values


@dataclass(frozen=True)
class WalkForwardAggregate:
    strategy_name: str
    train_window_months: int
    test_window_months: int
    step_months: int
    # `fold_count` and every statistic below it (positive_net_return_
    # folds, median/stdev/worst/best, regime_breakdown) count ONLY
    # folds where `fold.result.net.is_valid_performance` is True (see
    # `_is_valid_fold` below) -- an ERROR/CRITICAL integrity issue
    # (e.g. a negative-cash state, a delisting mis-valuation) means
    # that fold's net.performance numbers are not a legitimate
    # backtest outcome at all, per `BacktestResult.is_valid_performance`'s
    # own contract (backtest.integrity), and must not silently count
    # toward this strategy's evidence. External audit finding
    # (2026-09-24): `is_valid_performance` had no consumer anywhere in
    # `strategy_research` before this fix -- every fold's numbers,
    # integrity-valid or not, were being aggregated, fed into PBO/DSR,
    # and used for CANDIDATE/evidence-level classification.
    # `total_fold_count` (raw, unfiltered) and `excluded_integrity_
    # invalid_fold_count` are kept separately below for transparency --
    # `folds` itself still holds EVERY fold actually run, valid or not.
    fold_count: int
    total_fold_count: int
    excluded_integrity_invalid_fold_count: int
    positive_net_return_folds: int
    median_net_cumulative_return: Optional[float]
    median_net_sharpe: Optional[float]
    stdev_net_cumulative_return: Optional[float]
    worst_max_drawdown: Optional[float]
    worst_fold_index: Optional[int]
    best_net_cumulative_return: Optional[float]
    best_fold_index: Optional[int]
    regime_breakdown: dict  # {"BULL": count, "BEAR": count, "NEUTRAL": count, "UNKNOWN": count}
    folds: tuple[WalkForwardFoldResult, ...]


def run_walk_forward_evaluation(
    repository: DataRepository,
    strategy_factory: Callable[[], Strategy],
    security_ids: Sequence[str],
    *,
    overall_start: datetime,
    overall_end: datetime,
    train_window_months: int,
    test_window_months: int,
    step_months: int,
    initial_capital: float,
    benchmark_id: Optional[str] = None,
    regime_subject_id: Optional[str] = None,
    market: str = "US_EQUITY",
) -> WalkForwardAggregate:
    """Runs one strategy across every rolling window
    `generate_walk_forward_windows` produces for `[overall_start,
    overall_end]`. Returns an empty-fold aggregate (all `None`/`0`
    numeric fields, `fold_count=0`) when no window fits -- the honest
    answer for insufficient history (instruction section 25's own
    "데이터가 충분하지 않으면 억지로 구현하지 않는다", inherited
    unchanged from `generate_walk_forward_windows`), never an error and
    never a fabricated result."""
    windows = generate_walk_forward_windows(
        overall_start, overall_end,
        train_window_months=train_window_months, test_window_months=test_window_months, step_months=step_months,
    )

    strategy_name = type(strategy_factory()).__name__
    folds: list[WalkForwardFoldResult] = []
    for index, window in enumerate(windows):
        result = run_gross_and_net(
            repository, strategy_factory, security_ids,
            start_date=window.test_start.date(), end_date=window.test_end.date(),
            initial_capital=initial_capital, benchmark_id=benchmark_id, market=market,
        )
        regime_state = "UNKNOWN"
        if regime_subject_id is not None:
            data_view = make_single_point_view(repository, window.test_end)
            composite = RegimeDetector(RegimeConfig()).compute_composite(data_view, regime_subject_id, SubjectKind.SECURITY)
            regime_state = composite.axes[RegimeAxis.TREND].state
        folds.append(
            WalkForwardFoldResult(
                fold_index=index, train_start=window.train_start, train_end=window.train_end,
                test_start=window.test_start, test_end=window.test_end,
                result=result, regime_trend_state=regime_state,
            )
        )

    return _aggregate(strategy_name, train_window_months, test_window_months, step_months, folds)


def _is_valid_fold(fold: WalkForwardFoldResult) -> bool:
    """A fold whose real, net BacktestResult has an ERROR/CRITICAL
    integrity issue (backtest.integrity -- negative cash, a delisting
    mis-valuation, etc.) is not a legitimate performance outcome at
    all, per `BacktestResult.is_valid_performance`'s own contract --
    its numbers must not count toward this strategy's aggregate
    evidence (see `WalkForwardAggregate`'s own docstring/field
    comments)."""
    return fold.result.net.is_valid_performance


def _aggregate(
    strategy_name: str, train_window_months: int, test_window_months: int, step_months: int,
    folds: list[WalkForwardFoldResult],
) -> WalkForwardAggregate:
    if not folds:
        return WalkForwardAggregate(
            strategy_name=strategy_name, train_window_months=train_window_months,
            test_window_months=test_window_months, step_months=step_months,
            fold_count=0, total_fold_count=0, excluded_integrity_invalid_fold_count=0,
            positive_net_return_folds=0,
            median_net_cumulative_return=None, median_net_sharpe=None, stdev_net_cumulative_return=None,
            worst_max_drawdown=None, worst_fold_index=None, best_net_cumulative_return=None, best_fold_index=None,
            regime_breakdown={}, folds=(),
        )

    valid_folds = [f for f in folds if _is_valid_fold(f)]

    if not valid_folds:
        # Every fold this strategy produced was integrity-invalid --
        # the honest answer is "no usable evidence at all", not a
        # fabricated aggregate over folds that are not legitimate
        # performance outcomes.
        return WalkForwardAggregate(
            strategy_name=strategy_name, train_window_months=train_window_months,
            test_window_months=test_window_months, step_months=step_months,
            fold_count=0, total_fold_count=len(folds), excluded_integrity_invalid_fold_count=len(folds),
            positive_net_return_folds=0,
            median_net_cumulative_return=None, median_net_sharpe=None, stdev_net_cumulative_return=None,
            worst_max_drawdown=None, worst_fold_index=None, best_net_cumulative_return=None, best_fold_index=None,
            regime_breakdown={}, folds=tuple(folds),
        )

    net_returns = [f.result.net.performance.cumulative_return for f in valid_folds]
    net_sharpes = [f.result.net.performance.sharpe_ratio for f in valid_folds]
    max_drawdowns = [f.result.net.performance.max_drawdown for f in valid_folds]

    # Indices reference each fold's own stable `fold_index` (its
    # position among every window this evaluation generated), not a
    # position within `valid_folds` -- `aggregate.folds` below still
    # holds every fold, valid or not, so a raw list position would be
    # ambiguous about which list it indexes into.
    worst_dd_pos = min(range(len(valid_folds)), key=lambda i: max_drawdowns[i])
    best_return_pos = max(range(len(valid_folds)), key=lambda i: net_returns[i])

    regime_breakdown: dict = {}
    for f in valid_folds:
        regime_breakdown[f.regime_trend_state] = regime_breakdown.get(f.regime_trend_state, 0) + 1

    return WalkForwardAggregate(
        strategy_name=strategy_name, train_window_months=train_window_months,
        test_window_months=test_window_months, step_months=step_months,
        fold_count=len(valid_folds),
        total_fold_count=len(folds),
        excluded_integrity_invalid_fold_count=len(folds) - len(valid_folds),
        positive_net_return_folds=sum(1 for r in net_returns if r > 0),
        median_net_cumulative_return=statistics.median(net_returns),
        median_net_sharpe=statistics.median(net_sharpes),
        stdev_net_cumulative_return=statistics.pstdev(net_returns) if len(net_returns) > 1 else 0.0,
        worst_max_drawdown=max_drawdowns[worst_dd_pos],
        worst_fold_index=valid_folds[worst_dd_pos].fold_index,
        best_net_cumulative_return=net_returns[best_return_pos],
        best_fold_index=valid_folds[best_return_pos].fold_index,
        regime_breakdown=regime_breakdown,
        folds=tuple(folds),
    )
