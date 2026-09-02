"""Signal predictiveness (Information Coefficient) diagnostic.

Added following a comparison against `quantopian/alphalens`: this
project's existing evaluation path only ever backtests a FULLY FORMED
strategy (rank -> top-N -> orders -> P&L) -- it never asks the
narrower, prior question alphalens is built around: does the raw
ranking signal itself have ANY forward-predictive power, independent
of the top-N/rebalance/cost wrapper around it? A weak full-backtest
result is ambiguous between "the signal has no edge" and "the signal
has edge but the wrapper (position sizing, top-N cutoff, costs) is
destroying it" -- IC analysis is the tool that tells those two apart.

Definition (alphalens's own, Spearman rank correlation): at each
rebalance date, rank every security by its score, rank every security
by its N-day-forward return, and correlate the two rankings. Mean IC
across many dates, and its stability (mean/stdev, an "IR" analogous to
but distinct from a Sharpe ratio), together answer "is this signal
predictive at all" -- independent of any specific top-N/rebalance-
frequency/cost choice.

**Point-in-time discipline, read before changing this module**:
`AsOfDataView` (`backtest/asof.py`) is deliberately incapable of
looking past its bound `BacktestClock`'s current checkpoint -- "There
is no method, override, or parameter through which a well-behaved
Strategy implementation could request data beyond the clock's current
checkpoint" (that module's own docstring). This is correct and must
stay that way for any live Strategy. This module is NOT a Strategy --
it is after-the-fact research analysis asking "did this signal predict
what actually happened," so it deliberately queries the underlying
`DataRepository` directly for forward returns (bypassing the clock),
while still routing every SCORE computation through a properly clocked
`AsOfDataView` so the score itself remains exactly as point-in-time-safe
as it would be inside a real backtest. Never blur this line: the score
must never see the future, the forward-return check must.

No numpy/scipy: Spearman rank correlation is Pearson correlation of the
RANKS (a standard identity), computed here in pure Python, matching
this project's existing stdlib-only convention (`strategy_research.pbo_dsr`).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, Sequence

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from data_infra.repository import DataRepository

ScoreFn = Callable[[str, datetime, AsOfDataView], Optional[float]]
FilterFn = Callable[[str, datetime, AsOfDataView], bool]


def forward_return(
    repository: DataRepository, security_id: str, as_of_time: datetime, horizon_days: int
) -> Optional[float]:
    """The realized return from `as_of_time` to `as_of_time + horizon_days`,
    queried directly against `repository` (deliberately NOT through an
    `AsOfDataView` -- see module docstring). `as_of_time` for the
    availability filter is `end_time` itself: for a period that has
    already fully elapsed, this returns exactly what actually happened,
    which is precisely what an after-the-fact predictiveness check
    needs to see."""
    end_time = as_of_time + timedelta(days=horizon_days)
    bars = repository.get_bars(security_id, as_of_time, end_time, as_of_time=end_time)
    if len(bars) < 2:
        return None
    start_price = bars[0].adjusted_close or bars[0].close
    end_price = bars[-1].adjusted_close or bars[-1].close
    if start_price <= 0:
        return None
    return end_price / start_price - 1.0


def rank_average(values: Sequence[float]) -> list[float]:
    """Average ranks (1-indexed); tied values get the mean of the ranks
    they span -- the standard convention Spearman correlation requires."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x * var_y) ** 0.5


def spearman_ic(scores: dict, forward_returns: dict) -> Optional[float]:
    """Spearman rank correlation between `scores` and `forward_returns`,
    matched by key (security_id). Requires >= 2 securities present in
    both dicts; returns `None` otherwise -- never a fabricated `0.0`
    standing in for "not enough data"."""
    common = sorted(set(scores) & set(forward_returns))
    if len(common) < 2:
        return None
    score_ranks = rank_average([scores[s] for s in common])
    return_ranks = rank_average([forward_returns[s] for s in common])
    return _pearson(score_ranks, return_ranks)


@dataclass(frozen=True)
class IcObservation:
    as_of_time: datetime
    ic: float
    num_securities: int


@dataclass(frozen=True)
class IcSummary:
    observations: tuple
    mean_ic: Optional[float]
    ic_information_ratio: Optional[float]
    positive_ic_ratio: Optional[float]


def summarize_ic_observations(observations: list[IcObservation]) -> IcSummary:
    """Shared aggregation tail for `compute_ic_series` and
    `compute_fundamentals_ic_series` -- identical math, factored out
    once both needed it, rather than duplicated."""
    if not observations:
        return IcSummary(observations=(), mean_ic=None, ic_information_ratio=None, positive_ic_ratio=None)

    ic_values = [o.ic for o in observations]
    mean_ic = statistics.fmean(ic_values)
    if len(ic_values) >= 2:
        stdev_ic = statistics.pstdev(ic_values)
        ic_ir = (mean_ic / stdev_ic) if stdev_ic > 0 else None
    else:
        ic_ir = None
    positive_ratio = sum(1 for v in ic_values if v > 0) / len(ic_values)

    return IcSummary(
        observations=tuple(observations),
        mean_ic=mean_ic,
        ic_information_ratio=ic_ir,
        positive_ic_ratio=positive_ratio,
    )


def compute_ic_series(
    security_ids: Sequence[str],
    rebalance_dates: Sequence[datetime],
    score_fn: ScoreFn,
    repository: DataRepository,
    *,
    horizon_days: int,
) -> IcSummary:
    """Computes IC at each date in `rebalance_dates`: `score_fn` is
    called through a per-date `AsOfDataView` clocked to exactly that
    date (point-in-time-safe, same as inside a real backtest);
    forward returns are read directly from `repository` (deliberately
    not point-in-time-limited -- see module docstring). A date with
    fewer than 2 securities carrying both a score and a computable
    forward return is silently skipped, not counted as `ic=0`."""
    observations: list[IcObservation] = []
    for as_of_time in rebalance_dates:
        data_view = AsOfDataView(repository, BacktestClock(checkpoints=(as_of_time,)))
        scores = {}
        for sid in security_ids:
            score = score_fn(sid, as_of_time, data_view)
            if score is not None:
                scores[sid] = score

        forward_returns = {}
        for sid in scores:
            fr = forward_return(repository, sid, as_of_time, horizon_days)
            if fr is not None:
                forward_returns[sid] = fr

        ic = spearman_ic(scores, forward_returns)
        if ic is not None:
            observations.append(
                IcObservation(as_of_time=as_of_time, ic=ic, num_securities=len(forward_returns))
            )

    return summarize_ic_observations(observations)


FundamentalsScoreFn = Callable[[str, datetime, object], Optional[float]]


def compute_fundamentals_ic_series(
    security_ids: Sequence[str],
    rebalance_dates: Sequence[datetime],
    score_fn: FundamentalsScoreFn,
    fundamentals_repository: object,
    price_repository: DataRepository,
    *,
    horizon_days: int,
) -> IcSummary:
    """Fundamentals analog of `compute_ic_series` -- the two data
    sources fundamentals signals need are never the same repository
    (fundamentals are ingested into their own DuckDB catalog, entirely
    separate from price data's), unlike `compute_ic_series`'s single
    `repository` which serves both scoring and forward returns.

    `score_fn` is called directly against `fundamentals_repository`,
    with no `AsOfDataView`/`BacktestClock` wrapper needed --
    `DuckDBFundamentalsRepository`'s own methods (`get_fundamentals`/
    `latest_known_value`) already take `as_of_time` and apply the
    `available_time <= as_of_time` look-ahead guard directly, the same
    point-in-time-safety property `AsOfDataView` exists to enforce for
    price data, just implemented at the repository layer instead of a
    separate wrapper. Forward returns still come from `price_repository`
    via the same `forward_return` helper `compute_ic_series` uses,
    deliberately not point-in-time-limited (module docstring)."""
    observations: list[IcObservation] = []
    for as_of_time in rebalance_dates:
        scores = {}
        for sid in security_ids:
            score = score_fn(sid, as_of_time, fundamentals_repository)
            if score is not None:
                scores[sid] = score

        forward_returns = {}
        for sid in scores:
            fr = forward_return(price_repository, sid, as_of_time, horizon_days)
            if fr is not None:
                forward_returns[sid] = fr

        ic = spearman_ic(scores, forward_returns)
        if ic is not None:
            observations.append(
                IcObservation(as_of_time=as_of_time, ic=ic, num_securities=len(forward_returns))
            )

    return summarize_ic_observations(observations)


HybridScoreFn = Callable[[str, datetime, object, DataRepository], Optional[float]]


def compute_hybrid_ic_series(
    security_ids: Sequence[str],
    rebalance_dates: Sequence[datetime],
    score_fn: HybridScoreFn,
    fundamentals_repository: object,
    price_repository: DataRepository,
    *,
    horizon_days: int,
) -> IcSummary:
    """Analog of `compute_fundamentals_ic_series` for a factor that needs
    BOTH data sources to compute its score itself, not just for forward
    returns -- e.g. a market-cap-dependent factor like shareholder
    yield, which needs `price_repository` for the current price and
    `fundamentals_repository` for shares outstanding and cash-flow
    figures. `compute_fundamentals_ic_series`'s `FundamentalsScoreFn`
    only ever passes `fundamentals_repository` to `score_fn` --
    widening that signature would silently give every existing single-
    repository score an unused extra argument for no reason, so this is
    a new, separate function instead, matching this module's own
    precedent (`compute_ic_series` vs `compute_fundamentals_ic_series`)
    of adding a parallel function rather than changing an existing
    one's contract.

    `score_fn` is called directly against both repositories, with no
    `AsOfDataView` wrapper on either side -- `DataRepository.get_bars`
    already takes `as_of_time` and applies its own look-ahead guard at
    the repository layer (Phase 1 spec section 15), the exact property
    `AsOfDataView` exists to enforce, just already present on the
    interface itself, identical to `compute_fundamentals_ic_series`'s
    reasoning for why `fundamentals_repository` needs no wrapper either.
    Forward returns still come from `price_repository` via the same
    `forward_return` helper, deliberately not point-in-time-limited
    (module docstring)."""
    observations: list[IcObservation] = []
    for as_of_time in rebalance_dates:
        scores = {}
        for sid in security_ids:
            score = score_fn(sid, as_of_time, fundamentals_repository, price_repository)
            if score is not None:
                scores[sid] = score

        forward_returns = {}
        for sid in scores:
            fr = forward_return(price_repository, sid, as_of_time, horizon_days)
            if fr is not None:
                forward_returns[sid] = fr

        ic = spearman_ic(scores, forward_returns)
        if ic is not None:
            observations.append(
                IcObservation(as_of_time=as_of_time, ic=ic, num_securities=len(forward_returns))
            )

    return summarize_ic_observations(observations)


@dataclass(frozen=True)
class BucketObservation:
    as_of_time: datetime
    passing_mean_return: Optional[float]
    passing_count: int
    failing_mean_return: Optional[float]
    failing_count: int


@dataclass(frozen=True)
class BucketReturnSummary:
    observations: tuple
    mean_passing_return: Optional[float]
    mean_failing_return: Optional[float]
    mean_spread: Optional[float]  # mean(passing - failing), averaged per-date then across dates
    positive_spread_ratio: Optional[float]
    dates_with_both_groups: int


def bucket_return_analysis(
    security_ids: Sequence[str],
    rebalance_dates: Sequence[datetime],
    filter_fn: FilterFn,
    repository: DataRepository,
    *,
    horizon_days: int,
) -> BucketReturnSummary:
    """For a BOOLEAN filter (e.g. `TrendVolatilityStrategy._passes_filter`)
    that IC's continuous-score definition does not apply to: splits
    securities at each rebalance date into "passing"/"failing" groups
    and compares their mean forward returns -- same point-in-time
    discipline as `compute_ic_series` (filter evaluated through a
    clocked `AsOfDataView`, forward return read directly from
    `repository`). A date where either group is empty is excluded from
    the summary's aggregate stats (but still recorded in
    `observations`, with `None` for the missing side) -- never
    fabricated as a 0% return or silently dropped without a trace."""
    observations: list[BucketObservation] = []
    for as_of_time in rebalance_dates:
        data_view = AsOfDataView(repository, BacktestClock(checkpoints=(as_of_time,)))
        passing_returns: list[float] = []
        failing_returns: list[float] = []
        for sid in security_ids:
            fr = forward_return(repository, sid, as_of_time, horizon_days)
            if fr is None:
                continue
            if filter_fn(sid, as_of_time, data_view):
                passing_returns.append(fr)
            else:
                failing_returns.append(fr)
        observations.append(
            BucketObservation(
                as_of_time=as_of_time,
                passing_mean_return=(statistics.fmean(passing_returns) if passing_returns else None),
                passing_count=len(passing_returns),
                failing_mean_return=(statistics.fmean(failing_returns) if failing_returns else None),
                failing_count=len(failing_returns),
            )
        )

    usable = [o for o in observations if o.passing_mean_return is not None and o.failing_mean_return is not None]
    if not usable:
        return BucketReturnSummary(
            observations=tuple(observations), mean_passing_return=None, mean_failing_return=None,
            mean_spread=None, positive_spread_ratio=None, dates_with_both_groups=0,
        )

    mean_passing = statistics.fmean([o.passing_mean_return for o in usable])
    mean_failing = statistics.fmean([o.failing_mean_return for o in usable])
    spreads = [o.passing_mean_return - o.failing_mean_return for o in usable]
    mean_spread = statistics.fmean(spreads)
    positive_spread_ratio = sum(1 for s in spreads if s > 0) / len(spreads)

    return BucketReturnSummary(
        observations=tuple(observations),
        mean_passing_return=mean_passing,
        mean_failing_return=mean_failing,
        mean_spread=mean_spread,
        positive_spread_ratio=positive_spread_ratio,
        dates_with_both_groups=len(usable),
    )
