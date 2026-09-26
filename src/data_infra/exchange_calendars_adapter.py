"""ExchangeCalendarsTradingCalendar: a `data_infra.calendar.TradingCalendar`
implementation backed by the real `exchange_calendars` library, rather
than this project's own hand-picked/rule-derived holiday data.

See ADR-0151 Decision 7 (`pyproject.toml`'s `market-calendars` extra) --
that ADR adopted `exchange_calendars>=4.13.2` but deliberately left it
unwired ("Not yet wired in -- TradingCalendar is already a Protocol for
this exact swap"). This module is that swap. See ADR-0207 for why it was
wired now and exactly how.

**This is the only file in `data_infra.*` that imports `exchange_calendars`**
-- `data_infra.calendar`'s own `TradingCalendar` Protocol and
`SimpleTradingCalendar`/`US_EQUITY`/`KR_EQUITY`/`US_EQUITY_NYSE` stay
exactly as they were, dependency-free. `exchange_calendars` remains an
optional extra (`pip install -e '.[market-calendars]'`), never promoted
to a core dependency -- importing this module without it installed
raises `ImportError` at import time, exactly like every other
optional-extra module in this codebase (e.g.
`scripts/verify_alpaca_paper_broker.py`).

**Real, disclosed limitation**: both `XNYS` and `XKRX` calendars in
`exchange_calendars==4.13.2` cover a fixed, rolling ~21-year window --
confirmed directly in this environment (2026-09-25) as
`first_session=2006-09-25`, `last_session=2027-09-24`. A date outside
that window raises `exchange_calendars.errors.DateOutOfBounds` (a clear,
loud failure -- never a silently wrong answer), not a `TradingCalendar`
Protocol violation. `data_infra.calendar.US_EQUITY_NYSE` (rule-derived,
2000-2035) has no such near-term ceiling; a caller needing dates beyond
2027-09-24 (this window advances only when `exchange_calendars` itself
is upgraded) must keep using that one, or a future session must bump
the `market-calendars` pin and re-verify the new bounds.
"""

from __future__ import annotations

from datetime import date, time
from typing import Optional

import exchange_calendars as xcals


def _calendar_date(day: date) -> date:
    """Real bug found and fixed while wiring this module in (ADR-0207):
    `TradingCalendar.is_trading_day`'s own Protocol signature says `day:
    date`, but this project's real callers (`backtest.clock.
    build_daily_checkpoints` in particular) actually pass a
    timezone-AWARE `datetime` -- `datetime` is a `date` subclass, so this
    was never a type error, and `SimpleTradingCalendar`'s own
    `is_trading_day`/`session_hours` tolerate it silently (`.weekday()`
    works identically on both; a `datetime` failing to equal a same-day
    `date` in its `holidays: frozenset[date]` membership check never
    raises, it just silently never matches -- a separate, pre-existing
    gap this function does not attempt to fix). `exchange_calendars`
    is far stricter: passing a tz-aware `datetime` straight to
    `is_session()` raises `AttributeError` from deep inside its own
    timestamp parsing (`'datetime.timezone' object has no attribute
    'key'`) -- confirmed directly, not guessed, while running this
    project's own real test suite after wiring this adapter in. Every
    entry point into this class normalizes through this function first,
    stripping time/timezone down to the plain calendar date the caller
    actually meant."""
    return date(day.year, day.month, day.day)


class ExchangeCalendarsTradingCalendar:
    """Delegates every real calendar question to a real
    `exchange_calendars.ExchangeCalendar` instance -- no hand-picked or
    rule-derived holiday data of its own, unlike every other concrete
    `TradingCalendar` in this package. In particular, this is the only
    calendar in this project that correctly excludes Korean lunar
    holidays (Seollal/Chuseok -- not derivable from a fixed Gregorian
    rule the way `US_EQUITY_NYSE`'s US federal holidays are) and US
    ad-hoc market closures (e.g. a National Day of Mourning) that
    `US_EQUITY_NYSE`'s own docstring explicitly discloses it cannot
    cover."""

    def __init__(self, xcal_name: str, *, market: str, timezone: str, start: Optional[str] = None) -> None:
        self.market = market
        self.timezone = timezone
        # `start=None` keeps exchange_calendars' own default, which is a
        # ROLLING 20 years before today -- see `_XNYS_HISTORY_START`.
        self._xcal = xcals.get_calendar(xcal_name) if start is None else xcals.get_calendar(xcal_name, start=start)
        # Protocol requires fixed open_time/close_time fallback fields --
        # sampled from one real, representative regular session (never
        # hardcoded), but session_hours() below always consults the real
        # per-date schedule instead of these for an actual date's hours
        # (a given date can have an early close, a late/ceremonial open,
        # etc. that these two fields alone could never express).
        _sample = self._xcal.schedule.iloc[len(self._xcal.schedule) // 2]
        self.open_time = _sample["open"].tz_convert(timezone).time()
        self.close_time = _sample["close"].tz_convert(timezone).time()

    def is_trading_day(self, day: date) -> bool:
        return bool(self._xcal.is_session(_calendar_date(day)))

    def session_hours(self, day: date) -> Optional[tuple[time, time]]:
        plain_day = _calendar_date(day)
        if not self.is_trading_day(plain_day):
            return None
        row = self._xcal.schedule.loc[str(plain_day)]
        open_local = row["open"].tz_convert(self.timezone)
        close_local = row["close"].tz_convert(self.timezone)
        return open_local.time(), close_local.time()


# Real bug found by the first 2000-onward Stage 5 ingestion run (ADR-0213,
# 2026-09-26): exchange_calendars' default calendar only covers the 20
# years before TODAY (first XNYS session 2006-09-26 on that date), so
# `is_trading_day(2000-01-03)` raised `DateOutOfBounds` and every shard
# of `ingest_real_market_data.py --start 2000-01-01` crashed after
# persisting its bars. The same rolling default would also have broken
# the existing 2010-01-01 validation window once today passed 2030.
# A fixed start well before any research window this project uses.
_XNYS_HISTORY_START = "1990-01-01"


def build_xnys_calendar() -> ExchangeCalendarsTradingCalendar:
    """US equities (NYSE) -- same `market="US_EQUITY"` key every existing
    caller already uses for `data_infra.calendar.US_EQUITY`/
    `US_EQUITY_NYSE`, so this is a drop-in replacement at each
    `calendars={"US_EQUITY": ...}` injection site. Covers sessions from
    `_XNYS_HISTORY_START`, not exchange_calendars' rolling 20-year
    default."""
    return ExchangeCalendarsTradingCalendar(
        "XNYS", market="US_EQUITY", timezone="America/New_York", start=_XNYS_HISTORY_START
    )


def build_xkrx_calendar() -> ExchangeCalendarsTradingCalendar:
    """Korea equities (KRX) -- `market="KR_EQUITY"`, matching
    `data_infra.calendar.KR_EQUITY`'s own key. Not yet injected by any
    real caller (no Korean broker/scheduler exists in this repository
    yet) -- built ahead of that need, per ADR-0207, as the calendar
    accuracy prerequisite a future KIS adapter will require."""
    return ExchangeCalendarsTradingCalendar("XKRX", market="KR_EQUITY", timezone="Asia/Seoul")
