"""Calendar-month arithmetic shared by the long-term strategy candidates.

No new dependency added (no `dateutil`) -- manual month rollover, pure
and deterministic, never touching wall-clock time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence, TypeVar

T = TypeVar("T")

# Trading days per calendar month, used only to size lookback bar-query
# windows generously enough to contain N months of actual trading
# history -- a coarse, standard approximation (21 trading days/month),
# not a claim of calendar precision. Shared by every strategy_research
# candidate that uses a month-denominated lookback.
TRADING_DAYS_PER_MONTH = 21


def add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def trim_to_lookback(bars: Sequence[T], lookback_days: int) -> Sequence[T]:
    """Every candidate strategy that uses a month-denominated lookback
    fetches bars over a calendar-day-padded date range (per this
    module's `TRADING_DAYS_PER_MONTH` docstring, the padding exists
    only to guarantee the query returns enough calendar days to cover
    `lookback_days` trading days -- it is not itself the intended
    lookback window). Found by comparing this codebase against
    gs-quant's `timeseries.moving_average`/`volatility`, which both
    operate on a precisely-sized trailing window: this project's
    strategies previously used the entire over-fetched, padded bar list
    directly as the lookback window (e.g. a `lookback_months=12`
    momentum score, or a `trend_lookback_months` moving average, ending
    up computed over roughly 1.4-1.6x too many trading days, since the
    padding factor was never trimmed back off before use) -- silently
    measuring a longer, diluted period than each strategy's own
    documented parameter claims. Callers pass their already-padded
    `get_bars(...)` result through this before using it as the actual
    signal window; returns the most recent `lookback_days + 1` bars
    (enough for `lookback_days` day-over-day observations), or every
    bar unchanged if the fetch came back with fewer than that (the same
    graceful degradation the un-trimmed code already had for
    insufficient history near the start of a series)."""
    if len(bars) <= lookback_days + 1:
        return bars
    return bars[-(lookback_days + 1):]


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1)
    else:
        next_month_first = datetime(year, month + 1, 1)
    this_month_first = datetime(year, month, 1)
    return (next_month_first - this_month_first).days
