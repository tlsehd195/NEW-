"""Category: Real-Calendar Accuracy Test -- `ExchangeCalendarsTradingCalendar`
is the only `TradingCalendar` in this project backed by real (not
hand-picked/rule-derived) holiday data. Requires the `market-calendars`
optional extra (`exchange_calendars`) -- `pytest.importorskip` mirrors
`tests/scripts/test_generate_paper_performance_tearsheet_cli.py`'s own
`[reporting]`/`[research]` pattern. Every date asserted below was
confirmed directly against the real `exchange_calendars` library before
being written here (ADR-0207), never guessed."""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("exchange_calendars", reason="optional [market-calendars] extra not installed")

from data_infra.calendar import TradingCalendar  # noqa: E402
from data_infra.exchange_calendars_adapter import (  # noqa: E402
    build_xkrx_calendar,
    build_xnys_calendar,
)


class TestKoreanLunarHolidays:
    """The exact gap `data_infra.calendar.KR_EQUITY`'s hand-picked
    2-holiday sample cannot cover -- lunar holidays shift every
    Gregorian year and cannot be derived from a fixed rule."""

    @pytest.mark.parametrize(
        "day",
        [
            date(2024, 2, 10),  # Seollal (Lunar New Year) 2024
            date(2025, 1, 29),  # Seollal 2025
            date(2026, 2, 17),  # Seollal 2026
        ],
    )
    def test_seollal_is_not_a_trading_day(self, day: date) -> None:
        cal = build_xkrx_calendar()
        assert cal.is_trading_day(day) is False
        assert cal.session_hours(day) is None


class TestUsFederalAndAdHocHolidays:
    @pytest.mark.parametrize(
        "day",
        [
            date(2024, 1, 15),  # MLK Day 2024
            date(2024, 6, 19),  # Juneteenth 2024
            date(2024, 11, 28),  # Thanksgiving 2024
            date(2025, 4, 18),  # Good Friday 2025
            date(2026, 9, 7),  # Labor Day 2026
        ],
    )
    def test_known_us_holiday_is_not_a_trading_day(self, day: date) -> None:
        cal = build_xnys_calendar()
        assert cal.is_trading_day(day) is False
        assert cal.session_hours(day) is None


class TestWeekendsAndOrdinaryDays:
    def test_saturday_is_not_a_trading_day(self) -> None:
        cal = build_xnys_calendar()
        assert cal.is_trading_day(date(2025, 1, 25)) is False

    def test_an_ordinary_monday_is_a_trading_day_on_both_markets(self) -> None:
        assert build_xnys_calendar().is_trading_day(date(2025, 3, 10)) is True
        assert build_xkrx_calendar().is_trading_day(date(2025, 3, 10)) is True


class TestSessionHours:
    def test_xnys_session_hours_are_local_regular_hours(self) -> None:
        cal = build_xnys_calendar()
        hours = cal.session_hours(date(2025, 3, 10))
        assert hours is not None
        open_t, close_t = hours
        assert open_t.hour == 9 and open_t.minute == 30
        assert close_t.hour == 16 and close_t.minute == 0

    def test_xkrx_session_hours_are_local_regular_hours(self) -> None:
        cal = build_xkrx_calendar()
        hours = cal.session_hours(date(2025, 3, 10))
        assert hours is not None
        open_t, close_t = hours
        assert open_t.hour == 9 and open_t.minute == 0
        assert close_t.hour == 15 and close_t.minute == 30


class TestProtocolCompliance:
    def test_xnys_calendar_satisfies_the_trading_calendar_protocol(self) -> None:
        cal: TradingCalendar = build_xnys_calendar()
        assert cal.market == "US_EQUITY"
        assert cal.timezone == "America/New_York"
        assert isinstance(cal.is_trading_day(date(2025, 3, 10)), bool)

    def test_xkrx_calendar_satisfies_the_trading_calendar_protocol(self) -> None:
        cal: TradingCalendar = build_xkrx_calendar()
        assert cal.market == "KR_EQUITY"
        assert cal.timezone == "Asia/Seoul"
        assert isinstance(cal.is_trading_day(date(2025, 3, 10)), bool)

    def test_drop_in_market_key_matches_existing_us_equity_callers(self) -> None:
        """Every real caller injects US_EQUITY_NYSE as `calendars=
        {"US_EQUITY": ...}` -- this must be a same-key drop-in, not a
        second, differently-keyed calendar callers would need to
        discover separately."""
        from data_infra.calendar import US_EQUITY_NYSE

        assert build_xnys_calendar().market == US_EQUITY_NYSE.market


class TestOutOfBoundsFailsLoudly:
    """Real, disclosed limitation (this module's own docstring): a date
    outside exchange_calendars' own supported window must raise, never
    silently answer wrong."""

    def test_a_date_far_in_the_future_raises_rather_than_answers_wrong(self) -> None:
        cal = build_xnys_calendar()
        with pytest.raises(Exception):
            cal.is_trading_day(date(2099, 1, 4))
