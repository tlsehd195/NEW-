"""Kakushadze (2015), "101 Formulaic Alphas" (arXiv:1601.00991) -- 10 of
the paper's alphas, reimplemented per-security in this project's own
`ScoreFn`-compatible style.

Selected from Vibe-Trading's own `agent/src/factors/zoo/alpha101/`
(`EXTERNAL_REPO_APPLICABILITY_REPORT.md` priority 9) as the subset that
needs only OHLCV -- no `vwap` (which this project's providers rarely
populate) and no cross-sectional `rank()`/industry-neutralization
(which needs the whole universe's data at once, a different function
shape than this module's `ScoreFn` contract, and this project has no
cross-sectional-operator infrastructure to reuse for it).

Formulas verified directly against Vibe-Trading's own source (each
`alpha_NNN.py` cites the same paper equation number), per this
project's own "never reconstruct a cited algorithm from memory alone"
discipline (`factor_scores.bid_ask_spread_score`'s own precedent) -- not
reconstructed from memory, and not a copy of Vibe-Trading's
pandas-vectorized code (this project's `src/` stays duckdb+pyarrow-only,
no pandas/numpy): reimplemented per-security in plain Python against
this project's own `AsOfDataView`/`PriceBar`.

**Adjusted vs. raw prices**: where a formula compares a raw price LEVEL
across different days (`delta(close, N)`, `sum(high, N)`),
`adjusted_close`/`adjusted_high` is preferred with a fallback to the raw
field -- the same "prefer adjusted, degrade gracefully" pattern every
existing momentum-style factor in `factor_scores.py` already uses. Where
a formula computes a same-day ratio of the shape `(a*close - b*low -
c*high) / (close - low)` and only diffs THAT ratio across days
(alpha #53/#54/#101 below), no adjustment is needed at all: multiplying
every OHLC field of one bar by the same per-day split-adjustment factor
leaves such a ratio unchanged (it cancels in the division), so raw
prices give the mathematically identical result adjusted prices would.
`open`/`volume` have no adjusted counterpart in `PriceBar` at all
(alpha #6) -- a known, pre-existing limitation this module inherits
rather than introduces.

Every function returns `None` -- never `NaN`/`inf` -- on insufficient
history or an undefined intermediate division, per this project's own
NaN/gap contract (`ml.features.compute_feature_vector`, Batch K)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from backtest.asof import AsOfDataView
from data_infra.models import PriceBar

from strategy_research._dates import trim_to_lookback


@dataclass(frozen=True)
class Alpha101Spec:
    """Metadata for one reimplemented alpha -- this project's own
    `ml.features.FeatureSpec` convention applied to Vibe-Trading's own
    `__alpha_meta__` schema (`columns_required`/`min_warmup_bars`
    fields kept under the same names for direct cross-reference against
    that source)."""

    alpha_id: str
    kakushadze_equation: int
    formula: str
    columns_required: tuple[str, ...]
    min_warmup_bars: int
    theme: tuple[str, ...]


ALPHA101_SPECS: tuple[Alpha101Spec, ...] = (
    Alpha101Spec(
        alpha_id="alpha101_006", kakushadze_equation=6,
        formula="-1 * correlation(open, volume, 10)",
        columns_required=("open", "volume"), min_warmup_bars=10, theme=("volume", "reversal"),
    ),
    Alpha101Spec(
        alpha_id="alpha101_009", kakushadze_equation=9,
        formula="(0<ts_min(delta(close,1),5))?delta(close,1):"
        "((ts_max(delta(close,1),5)<0)?delta(close,1):(-1*delta(close,1)))",
        columns_required=("close",), min_warmup_bars=6, theme=("momentum",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_012", kakushadze_equation=12,
        formula="sign(delta(volume,1)) * (-1 * delta(close,1))",
        columns_required=("close", "volume"), min_warmup_bars=2, theme=("volume", "reversal"),
    ),
    Alpha101Spec(
        alpha_id="alpha101_023", kakushadze_equation=23,
        formula="((sum(high,20)/20) < high) ? (-1*delta(high,2)) : 0",
        columns_required=("high",), min_warmup_bars=20, theme=("momentum",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_046", kakushadze_equation=46,
        formula="(0.25 < x) ? (-1) : ((x < 0) ? 1 : (-1*(close-delay(close,1)))), "
        "x = (delay(close,20)-delay(close,10))/10 - (delay(close,10)-close)/10",
        columns_required=("close",), min_warmup_bars=21, theme=("momentum",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_049", kakushadze_equation=49,
        formula="(x < -0.1) ? 1 : (-1*(close-delay(close,1))), "
        "x = (delay(close,20)-delay(close,10))/10 - (delay(close,10)-close)/10",
        columns_required=("close",), min_warmup_bars=21, theme=("momentum",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_051", kakushadze_equation=51,
        formula="(x < -0.05) ? 1 : (-1*(close-delay(close,1))), "
        "x = (delay(close,20)-delay(close,10))/10 - (delay(close,10)-close)/10",
        columns_required=("close",), min_warmup_bars=21, theme=("momentum",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_053", kakushadze_equation=53,
        formula="-1 * delta(((close-low) - (high-close))/(close-low), 9)",
        columns_required=("high", "low", "close"), min_warmup_bars=10, theme=("reversal",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_054", kakushadze_equation=54,
        formula="-1 * ((low-close)*(open^5)) / ((low-high)*(close^5))",
        columns_required=("open", "high", "low", "close"), min_warmup_bars=1, theme=("reversal",),
    ),
    Alpha101Spec(
        alpha_id="alpha101_101", kakushadze_equation=101,
        formula="(close - open) / ((high - low) + 0.001)",
        columns_required=("open", "high", "low", "close"), min_warmup_bars=1, theme=("reversal",),
    ),
)


def _last_n_bars(
    security_id: str, as_of_time: datetime, data: AsOfDataView, n: int,
) -> Sequence[PriceBar]:
    """The most recent `n` bars ending at (or before) `as_of_time`, or
    fewer if history is shorter -- same calendar-day padding factor
    (1.6x) every other lookback-windowed factor in this package uses."""
    padded_start = as_of_time - timedelta(days=int(n * 1.6) + 5)
    return trim_to_lookback(data.get_bars(security_id, padded_start, as_of_time), n - 1)


def _adj_close(bar: PriceBar) -> float:
    return bar.adjusted_close if bar.adjusted_close is not None else bar.close


def _adj_high(bar: PriceBar) -> float:
    return bar.adjusted_high if bar.adjusted_high is not None else bar.high


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


def _finite_or_none(value: float) -> Optional[float]:
    return value if math.isfinite(value) else None


def alpha101_006(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #6: `-1 * correlation(open, volume, 10)`. A quantized
    open/volume divergence signal -- open and volume moving in the same
    direction over the trailing 10 days scores negatively."""
    n = 10
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    opens = [b.open for b in bars]
    volumes = [b.volume for b in bars]
    corr = _pearson(opens, volumes)
    if corr is None:
        return None
    return _finite_or_none(-1.0 * corr)


def alpha101_009(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #9: follow a 1-day close delta if it has been
    consistently positive or consistently negative over the trailing 5
    days (a monotonic run), otherwise fade it."""
    n = 6
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    closes = [_adj_close(b) for b in bars]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    d1 = deltas[-1]
    if min(deltas) > 0 or max(deltas) < 0:
        value = d1
    else:
        value = -1.0 * d1
    return _finite_or_none(value)


def alpha101_012(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #12: `sign(delta(volume,1)) * (-1 * delta(close,1))`
    -- a 1-day reversal, sign-flipped by whether volume is rising or
    falling."""
    n = 2
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    closes = [_adj_close(b) for b in bars]
    volumes = [b.volume for b in bars]
    dvol = volumes[-1] - volumes[-2]
    dclose = closes[-1] - closes[-2]
    sign = 1.0 if dvol > 0 else (-1.0 if dvol < 0 else 0.0)
    return _finite_or_none(sign * (-1.0 * dclose))


def alpha101_023(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #23: if today's high is above its trailing-20-day
    average, score the negative of the 2-day high delta; otherwise 0."""
    n = 20
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    highs = [_adj_high(b) for b in bars]
    mean_high = sum(highs) / n
    if mean_high < highs[-1]:
        value = -1.0 * (highs[-1] - highs[-3])
    else:
        value = 0.0
    return _finite_or_none(value)


def _alpha_46_49_51_x(closes: Sequence[float]) -> float:
    # Shared intermediate for #46/#49/#51: closes has exactly 21 entries,
    # closes[-1]=T, closes[-11]=T-10, closes[-21]=T-20.
    close_t, close_t10, close_t20 = closes[-1], closes[-11], closes[-21]
    return ((close_t20 - close_t10) / 10.0) - ((close_t10 - close_t) / 10.0)


def alpha101_046(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #46: a 3-way regime split on a 20-day-vs-10-day close
    trend-of-trend measure `x` -- strongly positive `x` (trend
    decelerating hard) scores maximally bearish, negative `x` (trend
    accelerating) scores maximally bullish, otherwise fall back to a
    1-day reversal."""
    n = 21
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    closes = [_adj_close(b) for b in bars]
    x = _alpha_46_49_51_x(closes)
    if x > 0.25:
        value = -1.0
    elif x < 0.0:
        value = 1.0
    else:
        value = -1.0 * (closes[-1] - closes[-2])
    return _finite_or_none(value)


def alpha101_049(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #49: same trend-of-trend measure as #46, a single
    threshold at -0.1 instead of a 3-way split."""
    n = 21
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    closes = [_adj_close(b) for b in bars]
    x = _alpha_46_49_51_x(closes)
    if x < -0.1:
        value = 1.0
    else:
        value = -1.0 * (closes[-1] - closes[-2])
    return _finite_or_none(value)


def alpha101_051(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #51: same as #49, threshold -0.05 instead of -0.1."""
    n = 21
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    closes = [_adj_close(b) for b in bars]
    x = _alpha_46_49_51_x(closes)
    if x < -0.05:
        value = 1.0
    else:
        value = -1.0 * (closes[-1] - closes[-2])
    return _finite_or_none(value)


def _alpha_53_ratio(bar: PriceBar) -> Optional[float]:
    # Same-day, split-invariant ratio -- raw OHLC is mathematically
    # identical to adjusted OHLC here (see module docstring).
    denom = bar.close - bar.low
    if denom == 0:
        return None
    return ((bar.close - bar.low) - (bar.high - bar.close)) / denom


def alpha101_053(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #53: the 9-day change in a same-day close-location
    ratio (where in the day's range the close sits)."""
    n = 10
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    x_t = _alpha_53_ratio(bars[-1])
    x_t9 = _alpha_53_ratio(bars[-10])
    if x_t is None or x_t9 is None:
        return None
    return _finite_or_none(-1.0 * (x_t - x_t9))


def alpha101_054(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #54: `-1 * ((low-close)*open^5) / ((low-high)*close^5)`
    -- a single-bar reversal shape amplified by the 5th power of open
    and close."""
    n = 1
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    bar = bars[-1]
    denom = (bar.low - bar.high) * (bar.close ** 5)
    if denom == 0:
        return None
    value = -1.0 * ((bar.low - bar.close) * (bar.open ** 5)) / denom
    return _finite_or_none(value)


def alpha101_101(security_id: str, as_of_time: datetime, data: AsOfDataView) -> Optional[float]:
    """Kakushadze #101: `(close - open) / ((high - low) + 0.001)` -- the
    intraday return normalized by the day's range."""
    n = 1
    bars = _last_n_bars(security_id, as_of_time, data, n)
    if len(bars) < n:
        return None
    bar = bars[-1]
    value = (bar.close - bar.open) / ((bar.high - bar.low) + 0.001)
    return _finite_or_none(value)
