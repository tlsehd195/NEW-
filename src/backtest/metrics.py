"""Performance metrics.

See docs/specifications/PHASE-2-backtesting.md section 11. No single
metric here is meant to be read as a pass/fail signal on its own — see
that section's closing note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from backtest.benchmark import BenchmarkResult
    from backtest.portfolio import PortfolioAccounting

_DAYS_PER_YEAR = 365.25


def compute_returns(values: Sequence[float]) -> list[float]:
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values)) if values[i - 1] != 0]


def compute_max_drawdown(values: Sequence[float]) -> float:
    """Returns a value <= 0 (e.g. -0.2 for a 20% drawdown)."""
    peak = float("-inf")
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return max_dd


def annualized_volatility(returns: Sequence[float], periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return (variance**0.5) * (periods_per_year**0.5)


def sharpe_ratio(returns: Sequence[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = [r - period_rf for r in returns]
    mean_excess = sum(excess) / len(excess)
    std = (sum((r - mean_excess) ** 2 for r in excess) / (len(excess) - 1)) ** 0.5
    if std == 0:
        return 0.0
    return (mean_excess / std) * (periods_per_year**0.5)


def sortino_ratio(returns: Sequence[float], risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    if len(returns) < 2:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    excess = [r - period_rf for r in returns]
    mean_excess = sum(excess) / len(excess)
    downside = [min(0.0, r) for r in excess]
    downside_variance = sum(d**2 for d in downside) / len(downside)
    downside_std = downside_variance**0.5
    if downside_std == 0:
        return 0.0
    return (mean_excess / downside_std) * (periods_per_year**0.5)


def cagr(initial_value: float, final_value: float, start: datetime, end: datetime) -> float:
    years = (end - start).days / _DAYS_PER_YEAR
    if years <= 0 or initial_value <= 0:
        return 0.0
    return (final_value / initial_value) ** (1.0 / years) - 1.0


def calmar_ratio(cagr_value: float, max_drawdown: float) -> float:
    if max_drawdown == 0:
        return 0.0
    return cagr_value / abs(max_drawdown)


def ulcer_index(values: Sequence[float]) -> float:
    """Root-mean-square of the drawdown-from-running-peak series, in the
    same (<=0) sign convention as `compute_max_drawdown`'s per-point
    drawdown. Unlike `compute_max_drawdown` (worst single point only),
    this reflects both DEPTH and DURATION of every drawdown in one
    number: a shallow-but-long drawdown and a deep-but-brief one can
    produce a similar Ulcer Index even though `compute_max_drawdown`
    would rank them very differently -- a genuinely different question
    from what depth-only or the episode-duration fields above answer.

    Follows the same convention as `compute_max_drawdown` for the
    degenerate case: an empty or peak-less series returns 0.0 (not
    None) since "no drawdown observed" is a real, honest answer here,
    not an undefined one."""
    peak = float("-inf")
    squared_drawdowns = []
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            squared_drawdowns.append(((v - peak) / peak) ** 2)
    if not squared_drawdowns:
        return 0.0
    return (sum(squared_drawdowns) / len(squared_drawdowns)) ** 0.5


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile on an already-sorted sequence,
    matching `numpy.percentile`'s default interpolation. `q` in [0, 1]."""
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    idx = q * (n - 1)
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    frac = idx - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> Optional[float]:
    """Historical (non-parametric) VaR: the `1 - confidence` percentile
    of the observed return distribution, with no assumption that
    returns are normally distributed. `None` (not 0.0) when `returns`
    is empty -- a VaR of 0 would falsely read as "no risk observed"
    rather than "not computable"."""
    if not returns:
        return None
    return _percentile(sorted(returns), 1.0 - confidence)


def conditional_value_at_risk(returns: Sequence[float], confidence: float = 0.95) -> Optional[float]:
    """Expected Shortfall: mean return among observations at or below
    the VaR threshold -- "given a bad day happens, how bad on
    average". `None` when `returns` is empty, for the same reason as
    `value_at_risk`."""
    if not returns:
        return None
    var = value_at_risk(returns, confidence)
    tail = [r for r in returns if r <= var]
    if not tail:
        return var
    return sum(tail) / len(tail)


def compute_consecutive_streaks(closed_trades: Sequence["object"]) -> tuple[int, int]:
    """Longest consecutive-winning-trade and consecutive-losing-trade
    streaks, in the closed_trades' existing chronological order (same
    trade-level win/loss definition `win_rate` already uses --
    `realized_pnl > 0` counts as a win, `<= 0` as a loss). Returns
    `(0, 0)` for no trades -- an honest, non-fabricated answer since a
    zero-trade run genuinely has zero-length streaks in either
    direction, not an undefined ratio."""
    max_wins = current_wins = 0
    max_losses = current_losses = 0
    for trade in closed_trades:
        if trade.realized_pnl > 0:
            current_wins += 1
            current_losses = 0
        else:
            current_losses += 1
            current_wins = 0
        max_wins = max(max_wins, current_wins)
        max_losses = max(max_losses, current_losses)
    return max_wins, max_losses


@dataclass(frozen=True)
class DrawdownEpisode:
    """One peak-to-trough-to-recovery episode. `depth` follows
    `compute_max_drawdown`'s convention (<= 0). `recovery_time`/
    `recovery_days` are `None` when the series ends still underwater --
    this is a real, distinct case from a shallow-but-recovered
    drawdown, and is never reported as `0` (which would falsely read
    as "recovered instantly").

    Added following a comparison against `quantopian/pyfolio`'s
    drawdown table: this project previously only reported drawdown
    DEPTH as a single number (`compute_max_drawdown`), with no notion
    of how long capital stayed underwater -- for a long-horizon
    system, duration is often as decision-relevant as depth alone."""

    peak_time: datetime
    trough_time: datetime
    recovery_time: Optional[datetime]
    depth: float
    duration_to_trough_days: int
    recovery_days: Optional[int]


def compute_drawdown_episodes(
    values: Sequence[float], timestamps: Sequence[datetime]
) -> tuple[DrawdownEpisode, ...]:
    """Walks `values`/`timestamps` (parallel sequences, one entry per
    valuation point) and returns every distinct drawdown episode in
    chronological order. A trailing episode that never returns to its
    starting peak by the end of the series is still included, with
    `recovery_time=None` -- never silently dropped."""
    if len(values) != len(timestamps):
        raise ValueError("values and timestamps must have the same length")
    if len(values) < 2:
        return ()

    episodes: list[DrawdownEpisode] = []
    peak_value, peak_time = values[0], timestamps[0]
    trough_value, trough_time = values[0], timestamps[0]
    in_drawdown = False

    for v, t in zip(values[1:], timestamps[1:]):
        if v >= peak_value:
            if in_drawdown:
                depth = (trough_value - peak_value) / peak_value if peak_value > 0 else 0.0
                episodes.append(
                    DrawdownEpisode(
                        peak_time=peak_time,
                        trough_time=trough_time,
                        recovery_time=t,
                        depth=depth,
                        duration_to_trough_days=(trough_time - peak_time).days,
                        recovery_days=(t - trough_time).days,
                    )
                )
                in_drawdown = False
            peak_value, peak_time = v, t
            trough_value, trough_time = v, t
        else:
            in_drawdown = True
            if v < trough_value:
                trough_value, trough_time = v, t

    if in_drawdown:
        depth = (trough_value - peak_value) / peak_value if peak_value > 0 else 0.0
        episodes.append(
            DrawdownEpisode(
                peak_time=peak_time,
                trough_time=trough_time,
                recovery_time=None,
                depth=depth,
                duration_to_trough_days=(trough_time - peak_time).days,
                recovery_days=None,
            )
        )
    return tuple(episodes)


def worst_drawdown_episode(episodes: Sequence[DrawdownEpisode]) -> Optional[DrawdownEpisode]:
    """The episode with the deepest `depth`, or `None` if `episodes` is
    empty. Ties broken by whichever `min()` encounters first (earliest
    in chronological order, since `episodes` is built in order)."""
    if not episodes:
        return None
    return min(episodes, key=lambda e: e.depth)


@dataclass(frozen=True)
class PerformanceReport:
    cumulative_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    turnover: float
    total_transaction_cost: float
    win_rate: float
    avg_trade_return: float
    benchmark_cumulative_return: Optional[float]
    benchmark_cagr: Optional[float]
    benchmark_max_drawdown: Optional[float]
    excess_return: Optional[float]
    annualized_excess_return: Optional[float]
    # Added following a pyfolio comparison (see docs/decisions/ or chat
    # log): drawdown DURATION, not just depth. Defaulted so every
    # pre-existing PerformanceReport(...) construction site (paper
    # trading persistence, serialization, tests) keeps working
    # unmodified -- purely additive.
    max_drawdown_duration_days: Optional[int] = None
    max_drawdown_recovery_days: Optional[int] = None
    max_drawdown_still_underwater: bool = False
    # Added following a quantstats/empyrical comparison: depth+duration
    # combined into one number (Ulcer Index), and tail-risk metrics
    # (historical VaR/CVaR) plus trade-streak metrics that
    # cumulative-return/Sharpe/Calmar alone don't surface. Same
    # additive-with-defaults pattern as the drawdown-duration fields
    # above -- every pre-existing construction site keeps working
    # unmodified.
    ulcer_index: float = 0.0
    value_at_risk_95: Optional[float] = None
    conditional_value_at_risk_95: Optional[float] = None
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0


def compute_performance_report(
    portfolio: "PortfolioAccounting",
    benchmark: Optional["BenchmarkResult"],
    *,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> PerformanceReport:
    series = portfolio.value_series
    values = [p.portfolio_value for p in series]

    if len(values) < 2:
        cumulative = 0.0
        cagr_value = 0.0
        volatility = 0.0
        sharpe = 0.0
        sortino = 0.0
        max_dd = 0.0
        calmar = 0.0
        dd_duration_days = None
        dd_recovery_days = None
        dd_still_underwater = False
        ulcer = 0.0
        var_95 = None
        cvar_95 = None
    else:
        returns = compute_returns(values)
        cumulative = values[-1] / values[0] - 1.0 if values[0] != 0 else 0.0
        cagr_value = cagr(values[0], values[-1], series[0].as_of_time, series[-1].as_of_time)
        volatility = annualized_volatility(returns, periods_per_year)
        sharpe = sharpe_ratio(returns, risk_free_rate, periods_per_year)
        sortino = sortino_ratio(returns, risk_free_rate, periods_per_year)
        max_dd = compute_max_drawdown(values)
        calmar = calmar_ratio(cagr_value, max_dd)
        ulcer = ulcer_index(values)
        var_95 = value_at_risk(returns, confidence=0.95)
        cvar_95 = conditional_value_at_risk(returns, confidence=0.95)

        timestamps = [p.as_of_time for p in series]
        worst = worst_drawdown_episode(compute_drawdown_episodes(values, timestamps))
        dd_duration_days = worst.duration_to_trough_days if worst is not None else None
        dd_recovery_days = worst.recovery_days if worst is not None else None
        dd_still_underwater = worst is not None and worst.recovery_time is None

    closed_trades = portfolio.closed_trades
    win_rate = (
        sum(1 for t in closed_trades if t.realized_pnl > 0) / len(closed_trades) if closed_trades else 0.0
    )
    avg_trade_return = (
        sum(
            (t.realized_pnl / (t.average_cost * t.quantity)) if t.average_cost * t.quantity > 0 else 0.0
            for t in closed_trades
        )
        / len(closed_trades)
        if closed_trades
        else 0.0
    )
    max_wins, max_losses = compute_consecutive_streaks(closed_trades)

    if benchmark is not None:
        benchmark_cumulative = benchmark.cumulative_return
        benchmark_cagr = benchmark.cagr
        benchmark_max_dd = benchmark.max_drawdown
        excess_return = cumulative - benchmark_cumulative
        annualized_excess_return = cagr_value - benchmark_cagr
    else:
        benchmark_cumulative = benchmark_cagr = benchmark_max_dd = None
        excess_return = annualized_excess_return = None

    return PerformanceReport(
        cumulative_return=cumulative,
        cagr=cagr_value,
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd,
        calmar_ratio=calmar,
        max_drawdown_duration_days=dd_duration_days,
        max_drawdown_recovery_days=dd_recovery_days,
        max_drawdown_still_underwater=dd_still_underwater,
        ulcer_index=ulcer,
        value_at_risk_95=var_95,
        conditional_value_at_risk_95=cvar_95,
        max_consecutive_wins=max_wins,
        max_consecutive_losses=max_losses,
        turnover=portfolio.turnover(),
        total_transaction_cost=portfolio.transaction_costs,
        win_rate=win_rate,
        avg_trade_return=avg_trade_return,
        benchmark_cumulative_return=benchmark_cumulative,
        benchmark_cagr=benchmark_cagr,
        benchmark_max_drawdown=benchmark_max_dd,
        excess_return=excess_return,
        annualized_excess_return=annualized_excess_return,
    )
