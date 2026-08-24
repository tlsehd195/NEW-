"""Basic coverage for the Trading Calendar abstraction.

Not one of the 14 required Phase 1 test categories on its own, but the
calendar module (docs/specifications/PHASE-1-data-infrastructure.md
section 11) is exercised here since the repository's
get_trading_calendar() depends on it.
"""

from __future__ import annotations

from datetime import date, time

from data_infra.calendar import KR_EQUITY, US_EQUITY, SimpleTradingCalendar
from data_infra.repository import InMemoryDataRepository


class TestTradingCalendar:
    def test_weekend_is_not_a_trading_day(self) -> None:
        saturday = date(2024, 1, 6)
        assert US_EQUITY.is_trading_day(saturday) is False

    def test_weekday_is_a_trading_day(self) -> None:
        tuesday = date(2024, 1, 2)
        assert US_EQUITY.is_trading_day(tuesday) is True

    def test_holiday_is_not_a_trading_day(self) -> None:
        assert US_EQUITY.is_trading_day(date(2024, 1, 1)) is False

    def test_session_hours_returns_none_on_non_trading_day(self) -> None:
        assert US_EQUITY.session_hours(date(2024, 1, 1)) is None

    def test_session_hours_returns_default_open_close_on_normal_day(self) -> None:
        hours = US_EQUITY.session_hours(date(2024, 1, 2))
        assert hours == (time(9, 30), time(16, 0))

    def test_early_close_overrides_default_close_time(self) -> None:
        cal = SimpleTradingCalendar(
            market="TEST",
            timezone="UTC",
            open_time=time(9, 0),
            close_time=time(16, 0),
            early_close={date(2024, 7, 3): time(13, 0)},
        )
        assert cal.session_hours(date(2024, 7, 3)) == (time(9, 0), time(13, 0))

    def test_us_and_kr_calendars_have_distinct_timezones(self) -> None:
        assert US_EQUITY.timezone != KR_EQUITY.timezone


class TestRepositoryCalendarAccess:
    def test_get_trading_calendar_returns_registered_calendar(self) -> None:
        repo = InMemoryDataRepository(calendars={"US_EQUITY": US_EQUITY})
        assert repo.get_trading_calendar("US_EQUITY") is US_EQUITY

    def test_get_trading_calendar_raises_for_unknown_market(self) -> None:
        import pytest

        repo = InMemoryDataRepository()
        with pytest.raises(KeyError):
            repo.get_trading_calendar("UNKNOWN_MARKET")
