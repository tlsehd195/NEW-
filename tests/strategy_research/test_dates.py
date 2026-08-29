"""Category: lookback-window trimming (strategy_research._dates) --
added following a comparison against gs-quant's `timeseries.
moving_average`/`volatility`, which operate on a precisely-sized
trailing window. This project's month-denominated-lookback strategies
previously used their entire calendar-day-padded `get_bars(...)`
fetch directly as the lookback window, silently diluting the signal
with the ~1.4-1.6x extra trading days the padding exists only to
guarantee coverage for (see `trim_to_lookback`'s own docstring)."""

from __future__ import annotations

from strategy_research._dates import trim_to_lookback


class TestTrimToLookback:
    def test_trims_to_lookback_days_plus_one(self) -> None:
        bars = list(range(20))  # a stand-in for an over-fetched, padded bar list
        trimmed = trim_to_lookback(bars, lookback_days=5)
        assert trimmed == [14, 15, 16, 17, 18, 19]
        assert len(trimmed) == 6  # lookback_days + 1

    def test_keeps_the_most_recent_bars_not_the_earliest(self) -> None:
        bars = ["oldest", "middle", "newest"]
        trimmed = trim_to_lookback(bars, lookback_days=1)
        assert trimmed == ["middle", "newest"]

    def test_returns_everything_unchanged_when_fewer_bars_than_the_window(self) -> None:
        bars = [1, 2, 3]
        trimmed = trim_to_lookback(bars, lookback_days=100)
        assert trimmed == bars

    def test_boundary_exactly_lookback_days_plus_one_is_unchanged(self) -> None:
        bars = [1, 2, 3, 4, 5]
        trimmed = trim_to_lookback(bars, lookback_days=4)
        assert trimmed == bars

    def test_empty_input_stays_empty(self) -> None:
        assert trim_to_lookback([], lookback_days=10) == []
