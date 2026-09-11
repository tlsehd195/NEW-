"""Basic coverage for the Trading Calendar abstraction.

Not one of the 14 required Phase 1 test categories on its own, but the
calendar module (docs/specifications/PHASE-1-data-infrastructure.md
section 11) is exercised here since the repository's
get_trading_calendar() depends on it.
"""

from __future__ import annotations

from datetime import date, time

from data_infra.calendar import KR_EQUITY, US_EQUITY, US_EQUITY_NYSE, SimpleTradingCalendar
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


class TestUsEquityNyseRuleBasedCalendar:
    """ADR-0117: US_EQUITY's own module docstring explicitly warns it is
    Phase-1-scope-only (3 holiday dates, one year) -- a real multi-year
    walk-forward/paper-trading run using it would generate a checkpoint
    on every real US market holiday outside 2024
    (`backtest.engine.BacktestEngine.run` -> `build_daily_checkpoints`
    consults this calendar directly). US_EQUITY_NYSE is a rule-derived
    calendar covering a much wider real range; these pin known, real
    NYSE holiday dates as a spot-check on the rules themselves (not
    generated from the same code being tested)."""

    def test_2024_holidays_match_the_real_published_nyse_calendar(self) -> None:
        # New Year's, MLK, Presidents, Good Friday, Memorial, Juneteenth,
        # Independence, Labor, Thanksgiving, Christmas.
        expected = {
            date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 3, 29),
            date(2024, 5, 27), date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2),
            date(2024, 11, 28), date(2024, 12, 25),
        }
        for day in expected:
            assert US_EQUITY_NYSE.is_trading_day(day) is False, f"{day} should be a holiday"

    def test_a_saturday_holiday_is_observed_the_preceding_friday(self) -> None:
        # July 4, 2020 fell on a Saturday -- observed Friday July 3, 2020.
        assert US_EQUITY_NYSE.is_trading_day(date(2020, 7, 3)) is False
        assert US_EQUITY_NYSE.is_trading_day(date(2020, 7, 4)) is False  # Saturday anyway

    def test_a_sunday_holiday_is_observed_the_following_monday(self) -> None:
        # Christmas 2022 fell on a Sunday -- observed Monday Dec 26, 2022.
        assert US_EQUITY_NYSE.is_trading_day(date(2022, 12, 26)) is False

    def test_juneteenth_is_not_a_holiday_before_2022(self) -> None:
        # NYSE began observing Juneteenth in 2022 -- June 19, 2019 (a
        # Wednesday) was an ordinary trading day.
        assert US_EQUITY_NYSE.is_trading_day(date(2019, 6, 19)) is True

    def test_juneteenth_is_a_holiday_from_2022_onward(self) -> None:
        assert US_EQUITY_NYSE.is_trading_day(date(2022, 6, 20)) is False  # observed (6/19 was Sunday)

    def test_an_ordinary_weekday_across_a_multi_year_span_is_still_a_trading_day(self) -> None:
        assert US_EQUITY_NYSE.is_trading_day(date(2015, 6, 10)) is True
        assert US_EQUITY_NYSE.is_trading_day(date(2010, 3, 15)) is True

    def test_covers_a_wide_multi_decade_range_not_just_one_year(self) -> None:
        assert len(US_EQUITY_NYSE.holidays) > 100  # 2000-2035, ~9-10/year


class TestRepositoryCalendarAccess:
    def test_get_trading_calendar_returns_registered_calendar(self) -> None:
        repo = InMemoryDataRepository(calendars={"US_EQUITY": US_EQUITY})
        assert repo.get_trading_calendar("US_EQUITY") is US_EQUITY

    def test_get_trading_calendar_raises_for_unknown_market(self) -> None:
        import pytest

        repo = InMemoryDataRepository()
        with pytest.raises(KeyError):
            repo.get_trading_calendar("UNKNOWN_MARKET")
