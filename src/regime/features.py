"""Deterministic, interpretable regime feature math (Phase 5 spec section
4). No HMM/Transformer/deep-learning model -- moving-average
relationships, realized volatility, volume ratios, rolling correlation,
and trailing drawdown, exactly the baseline set the instruction lists as
the required starting point.

Every function here takes only `PricePoint`s already available as of the
caller's cutoff (enforced by whoever fetched them -- see detector.py,
which sources them exclusively through `backtest.asof.AsOfDataView`, the
same point-in-time-safe view Strategy code already uses). No function in
this module accepts or infers an "as_of_time" itself; it operates purely
on "whatever points you handed me," which is what makes the point-in-time
guarantee re-derivable from the caller alone, mirroring
`data_infra.repository`'s "the guard lives at the one place every
caller must pass through" design (ADR-0004).

Percentile-based classification (volatility) ranks the current estimate
against its own *trailing* rolling history, never the full sample --
using the full sample (including dates after the current as_of_time)
would leak future information into a "how extreme is today" judgment,
exactly the failure mode Phase 1/2's look-ahead guard exists to prevent
one layer up.
"""

from __future__ import annotations

from typing import Optional, Sequence

from backtest.metrics import compute_max_drawdown

from regime.config import RegimeConfig
from regime.enums import CorrelationState, LiquidityState, StressState, TrendState, VolatilityState
from regime.points import PricePoint

_PERIODS_PER_YEAR = 252


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5


def _returns(prices: Sequence[float]) -> list[float]:
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1] != 0]


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 2 or n != len(b):
        return None
    mean_a, mean_b = _mean(a), _mean(b)
    covariance = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((x - mean_b) ** 2 for x in b)
    denominator = (var_a * var_b) ** 0.5
    if denominator == 0:
        return None
    return covariance / denominator


def data_completeness(available: int, required: int) -> float:
    if required <= 0:
        return 1.0
    return min(1.0, available / required)


def annualized_realized_vol(prices_window: Sequence[float]) -> Optional[float]:
    """Public (Phase 6 reuses this directly for its volatility-persistence
    baseline predictor, `predict.predictor.DriftPredictor` -- the same
    "don't duplicate math across phases" precedent Phase 5's Stress axis
    already set by reusing `backtest.metrics.compute_max_drawdown`)."""
    returns = _returns(prices_window)
    if len(returns) < 2:
        return None
    return _stdev(returns) * (_PERIODS_PER_YEAR**0.5)


def _rolling_vol_series(prices: Sequence[float], window: int) -> list[float]:
    """One realized-vol estimate per index `i` in `[window, len(prices)]`,
    each computed strictly from `prices[i-window:i]` -- the estimate
    "as of" position `i` never sees `prices[i:]`."""
    series: list[float] = []
    for i in range(window, len(prices) + 1):
        vol = annualized_realized_vol(prices[i - window : i])
        if vol is not None:
            series.append(vol)
    return series


# --------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------


def compute_trend(points: Sequence[PricePoint], config: RegimeConfig) -> tuple[TrendState, Optional[float], float]:
    """Short/long moving-average relationship (Phase 5 spec section 4).
    `value` is the relative gap `(short_ma - long_ma) / long_ma`."""
    required = config.trend_long_window
    reliability = data_completeness(len(points), required)
    if len(points) < required or reliability < config.min_data_completeness:
        return TrendState.UNKNOWN, None, reliability

    prices = [p.price for p in points]
    short_ma = _mean(prices[-config.trend_short_window :])
    long_ma = _mean(prices[-config.trend_long_window :])
    if long_ma == 0:
        return TrendState.UNKNOWN, None, reliability

    signal = (short_ma - long_ma) / long_ma
    if signal > config.trend_neutral_band:
        state = TrendState.BULL
    elif signal < -config.trend_neutral_band:
        state = TrendState.BEAR
    else:
        state = TrendState.NEUTRAL
    return state, signal, reliability


# --------------------------------------------------------------------
# Volatility
# --------------------------------------------------------------------


def compute_volatility(
    points: Sequence[PricePoint], config: RegimeConfig
) -> tuple[VolatilityState, Optional[float], float]:
    """Annualized realized volatility, percentile-ranked against its own
    trailing rolling history (never the full/future sample -- see module
    docstring)."""
    prices = [p.price for p in points]
    required_for_percentile = config.volatility_window + config.volatility_percentile_window - 1
    reliability = data_completeness(len(points), required_for_percentile)

    series = _rolling_vol_series(prices, config.volatility_window)
    if not series:
        return VolatilityState.UNKNOWN, None, reliability
    current_vol = series[-1]
    if reliability < config.min_data_completeness or len(series) < 2:
        return VolatilityState.UNKNOWN, current_vol, reliability

    history = series[-config.volatility_percentile_window :]
    rank = sum(1 for v in history if v <= current_vol) / len(history)
    if rank >= config.volatility_extreme_percentile:
        state = VolatilityState.EXTREME
    elif rank >= config.volatility_high_percentile:
        state = VolatilityState.HIGH
    elif rank <= config.volatility_low_percentile:
        state = VolatilityState.LOW
    else:
        state = VolatilityState.NORMAL
    return state, current_vol, reliability


# --------------------------------------------------------------------
# Liquidity
# --------------------------------------------------------------------


def compute_liquidity(
    points: Sequence[PricePoint], config: RegimeConfig
) -> tuple[LiquidityState, Optional[float], float]:
    """Recent-vs-baseline average volume ratio. A subject with no volume
    data at all (e.g. a BenchmarkPoint-derived series, which carries no
    volume field) is honestly UNKNOWN, not guessed (Phase 5 spec section
    4's "가능하면" for spread-based liquidity -- Phase 1's PriceBar has no
    bid/ask spread field at all, so that indicator is not implemented;
    documented as a known limitation, not silently skipped)."""
    volumes = [p.volume for p in points if p.volume is not None]
    if len(volumes) != len(points) or not points:
        return LiquidityState.UNKNOWN, None, 0.0

    required = config.liquidity_baseline_window
    reliability = data_completeness(len(volumes), required)
    if len(volumes) < required or reliability < config.min_data_completeness:
        return LiquidityState.UNKNOWN, None, reliability

    recent = _mean(volumes[-config.liquidity_recent_window :])
    baseline = _mean(volumes[-config.liquidity_baseline_window :])
    if baseline == 0:
        return LiquidityState.UNKNOWN, None, reliability

    ratio = recent / baseline
    if ratio < config.liquidity_low_ratio:
        state = LiquidityState.LOW
    elif ratio > config.liquidity_high_ratio:
        state = LiquidityState.HIGH
    else:
        state = LiquidityState.NORMAL
    return state, ratio, reliability


# --------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------


def compute_correlation(
    subject_points: Sequence[PricePoint], reference_points: Sequence[PricePoint], config: RegimeConfig
) -> tuple[CorrelationState, Optional[float], float]:
    """Rolling Pearson correlation of daily returns between the subject
    and a reference series (typically a benchmark). UNKNOWN, not
    fabricated, when no reference series was supplied at all."""
    if not reference_points:
        return CorrelationState.UNKNOWN, None, 0.0

    subject_by_ts = {p.timestamp: p.price for p in subject_points}
    reference_by_ts = {p.timestamp: p.price for p in reference_points}
    common_ts = sorted(set(subject_by_ts) & set(reference_by_ts))

    required = config.correlation_window + 1
    reliability = data_completeness(len(common_ts), required)
    if len(common_ts) < required or reliability < config.min_data_completeness:
        return CorrelationState.UNKNOWN, None, reliability

    window_ts = common_ts[-required:]
    subject_returns = _returns([subject_by_ts[t] for t in window_ts])
    reference_returns = _returns([reference_by_ts[t] for t in window_ts])
    correlation = _pearson(subject_returns, reference_returns)
    if correlation is None:
        return CorrelationState.UNKNOWN, None, reliability

    if correlation >= config.correlation_high_threshold:
        state = CorrelationState.HIGH
    elif correlation <= config.correlation_low_threshold:
        state = CorrelationState.LOW
    else:
        state = CorrelationState.NORMAL
    return state, correlation, reliability


# --------------------------------------------------------------------
# Stress
# --------------------------------------------------------------------


def compute_stress(
    points: Sequence[PricePoint], volatility_state: VolatilityState, config: RegimeConfig
) -> tuple[StressState, Optional[float], float]:
    """Composite of the Volatility axis's own classification plus
    trailing drawdown (reuses `backtest.metrics.compute_max_drawdown`
    directly rather than re-implementing drawdown math -- Phase 2 already
    built and tested this exact computation). Correlation is a documented
    extension point, not built into Stress now (Phase 5 spec section 4 --
    no need established yet for a three-input composite over a two-input
    one)."""
    prices = [p.price for p in points]
    required = config.stress_drawdown_window
    reliability = data_completeness(len(prices), required)
    if len(prices) < 2 or reliability < config.min_data_completeness:
        return StressState.UNKNOWN, None, reliability

    window = prices[-required:] if len(prices) >= required else prices
    drawdown = compute_max_drawdown(window)
    high_vol = volatility_state in (VolatilityState.HIGH, VolatilityState.EXTREME)

    if high_vol and drawdown <= config.stress_high_drawdown:
        state = StressState.HIGH
    elif high_vol or drawdown <= config.stress_elevated_drawdown:
        state = StressState.ELEVATED
    else:
        state = StressState.NORMAL
    return state, drawdown, reliability
