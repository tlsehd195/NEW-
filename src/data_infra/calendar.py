"""Trading Calendar abstraction.

See docs/specifications/PHASE-1-data-infrastructure.md section 11.

IMPORTANT: the concrete calendars shipped here (US_EQUITY, KR_EQUITY) use
a small, hand-picked holiday sample sufficient for Phase 1's mock data
date range. They are explicitly NOT a production-accurate, multi-year
holiday calendar — sourcing one is deferred (Phase 1 spec section 11).
Do not rely on these for real trading-day calculations beyond tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Protocol


class TradingCalendar(Protocol):
    """A market's trading schedule. Deliberately more than "weekdays 9-15":
    callers must consult holidays/early-close/late-open explicitly rather
    than assuming a fixed weekly pattern."""

    market: str
    timezone: str  # IANA timezone name, e.g. "America/New_York"
    open_time: time
    close_time: time

    def is_trading_day(self, day: date) -> bool: ...

    def session_hours(self, day: date) -> tuple[time, time] | None:
        """Returns (open_time, close_time) for the given day, or None if
        the market is closed that day (holiday/weekend)."""
        ...


@dataclass(frozen=True)
class SimpleTradingCalendar:
    """A minimal concrete TradingCalendar implementation.

    Weekends are always non-trading days. `holidays` fully closes the
    market for that date. `early_close`/`late_open` override the default
    open_time/close_time for specific dates without marking them as
    holidays.
    """

    market: str
    timezone: str
    open_time: time
    close_time: time
    holidays: frozenset[date] = field(default_factory=frozenset)
    early_close: dict[date, time] = field(default_factory=dict)
    late_open: dict[date, time] = field(default_factory=dict)

    def is_trading_day(self, day: date) -> bool:
        if day.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        if day in self.holidays:
            return False
        return True

    def session_hours(self, day: date) -> tuple[time, time] | None:
        if not self.is_trading_day(day):
            return None
        open_t = self.late_open.get(day, self.open_time)
        close_t = self.early_close.get(day, self.close_time)
        return open_t, close_t


# Minimal, Phase-1-scope-only sample calendars. See module docstring.
US_EQUITY = SimpleTradingCalendar(
    market="US_EQUITY",
    timezone="America/New_York",
    open_time=time(9, 30),
    close_time=time(16, 0),
    holidays=frozenset(
        {
            date(2024, 1, 1),  # New Year's Day
            date(2024, 7, 4),  # Independence Day
            date(2024, 12, 25),  # Christmas
        }
    ),
)

KR_EQUITY = SimpleTradingCalendar(
    market="KR_EQUITY",
    timezone="Asia/Seoul",
    open_time=time(9, 0),
    close_time=time(15, 30),
    holidays=frozenset(
        {
            date(2024, 1, 1),  # New Year's Day
            date(2024, 12, 25),  # Christmas
        }
    ),
)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """`weekday`: Monday=0 .. Sunday=6. `n`: 1-indexed occurrence."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + 7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (a standard, widely-published
    closed-form computation -- not a recalled/memorized date list)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(day: date) -> date:
    """NYSE convention: a holiday falling on Saturday is observed the
    preceding Friday; on Sunday, the following Monday."""
    if day.weekday() == 5:  # Saturday
        return day - timedelta(days=1)
    if day.weekday() == 6:  # Sunday
        return day + timedelta(days=1)
    return day


def _nyse_holidays_for_year(year: int) -> frozenset[date]:
    """Standard, fixed NYSE holiday rules (New Year's Day, MLK Day,
    Presidents Day, Good Friday, Memorial Day, Juneteenth [NYSE
    observance began 2022], Independence Day, Labor Day, Thanksgiving,
    Christmas), computed from each rule's own published definition --
    never a hand-recalled list of specific past dates. Deliberately
    does NOT include one-off ad-hoc closures with no fixed rule (e.g.
    9/11/2001, Hurricane Sandy 2012, a national day of mourning) --
    those cannot be derived from a rule and are not claimed to be
    covered here; see this module's own docstring."""
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday_of_month(year, 1, 0, 3),  # MLK Day: 3rd Monday of Jan
        _nth_weekday_of_month(year, 2, 0, 3),  # Presidents Day: 3rd Monday of Feb
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday_of_month(year, 5, 0),  # Memorial Day: last Monday of May
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),  # Labor Day: 1st Monday of Sep
        _nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving: 4th Thursday of Nov
        _observed(date(year, 12, 25)),  # Christmas
    }
    if year >= 2022:  # NYSE began observing Juneteenth in 2022
        holidays.add(_observed(date(year, 6, 19)))
    return frozenset(holidays)


def _build_nyse_holidays(start_year: int, end_year: int) -> frozenset[date]:
    holidays: set[date] = set()
    for year in range(start_year, end_year + 1):
        holidays |= _nyse_holidays_for_year(year)
    return frozenset(holidays)


# A rule-derived NYSE holiday calendar, spanning a much wider real range
# than US_EQUITY's own Phase-1-scope 3-date, single-year sample -- for
# real multi-year walk-forward/backtest runs (e.g.
# scripts/run_long_horizon_validation.py) where US_EQUITY's own gap
# (missing every real US market holiday outside 2024) would otherwise
# generate a checkpoint on real, unlisted market holidays across the
# whole 2000-2035 span. Every date here is DERIVED from each holiday's
# own published, fixed observance rule (see `_nyse_holidays_for_year`),
# not a memorized list -- the one known, explicitly documented gap is
# ad-hoc closures with no fixed rule (9/11/2001, Hurricane Sandy 2012,
# etc.), which this function cannot derive and does not claim to cover.
US_EQUITY_NYSE = SimpleTradingCalendar(
    market="US_EQUITY",
    timezone="America/New_York",
    open_time=time(9, 30),
    close_time=time(16, 0),
    holidays=_build_nyse_holidays(2000, 2035),
)
