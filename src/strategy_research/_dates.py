"""Calendar-month arithmetic shared by the long-term strategy candidates.

No new dependency added (no `dateutil`) -- manual month rollover, pure
and deterministic, never touching wall-clock time.
"""

from __future__ import annotations

from datetime import datetime

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


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1)
    else:
        next_month_first = datetime(year, month + 1, 1)
    this_month_first = datetime(year, month, 1)
    return (next_month_first - this_month_first).days
