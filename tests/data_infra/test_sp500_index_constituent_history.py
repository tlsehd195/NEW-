"""Category: point-in-time S&P 500 INDEX CONSTITUENT history from the
`fja05680/sp500` third-party ticker-start/end CSV schema
(`ticker,start_date,end_date`). Uses small synthetic fixture CSVs, not
the real source file -- this project's existing test-fixture discipline
(same pattern as `test_sp500_pit_membership.py`/`test_file_import_
provider.py`)."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from data_infra.providers.sp500_index_constituent_history import (
    TickerMembershipInterval,
    constituents_as_of,
    history_for_ticker,
    parse_ticker_intervals,
    removed_since,
)


def _write_csv(tmp_path, rows: list[tuple[str, str, str]]):
    """Mirrors the real source file's exact header and empty-string
    (not NULL/omitted) convention for a still-active ticker's
    `end_date` (e.g. `A,2000-06-05,`)."""
    path = tmp_path / "sp500_ticker_start_end.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ticker", "start_date", "end_date"])
        writer.writerows(rows)
    return path


class TestParseTickerIntervals:
    def test_parses_still_active_ticker_with_empty_end_date(self, tmp_path) -> None:
        path = _write_csv(tmp_path, [("AAPL", "2000-06-05", "")])
        intervals = parse_ticker_intervals(path)
        assert intervals[0].ticker == "AAPL"
        assert intervals[0].start_date == date(2000, 6, 5)
        assert intervals[0].end_date is None

    def test_parses_removed_ticker_with_populated_end_date(self, tmp_path) -> None:
        path = _write_csv(tmp_path, [("AABA", "1999-12-08", "2017-06-19")])
        intervals = parse_ticker_intervals(path)
        assert intervals[0].end_date == date(2017, 6, 19)

    def test_sorts_by_ticker_then_start_date(self, tmp_path) -> None:
        path = _write_csv(
            tmp_path,
            [
                ("AAL", "2015-03-23", "2024-09-23"),
                ("AAL", "1996-01-02", "1997-01-15"),
                ("AAPL", "2000-06-05", ""),
            ],
        )
        intervals = parse_ticker_intervals(path)
        assert [(iv.ticker, iv.start_date) for iv in intervals] == [
            ("AAL", date(1996, 1, 2)),
            ("AAL", date(2015, 3, 23)),
            ("AAPL", date(2000, 6, 5)),
        ]

    def test_rejects_wrong_schema(self, tmp_path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text("date,tickers\n2020-01-01,AAPL")
        with pytest.raises(ValueError):
            parse_ticker_intervals(path)

    def test_multiple_intervals_for_same_ticker_never_collapsed(self, tmp_path) -> None:
        """A ticker can leave and re-enter the index (e.g. real AAL:
        1996-1997, then 2015-2024) -- both intervals must survive."""
        path = _write_csv(
            tmp_path,
            [("AAL", "1996-01-02", "1997-01-15"), ("AAL", "2015-03-23", "2024-09-23")],
        )
        intervals = parse_ticker_intervals(path)
        assert len(intervals) == 2


class TestTickerMembershipIntervalValidation:
    def test_rejects_empty_ticker(self) -> None:
        with pytest.raises(ValueError):
            TickerMembershipInterval(ticker="", start_date=date(2020, 1, 1), end_date=None)

    def test_rejects_end_date_before_start_date(self) -> None:
        with pytest.raises(ValueError):
            TickerMembershipInterval(ticker="X", start_date=date(2020, 6, 1), end_date=date(2020, 1, 1))

    def test_contains_true_for_date_inside_open_ended_interval(self) -> None:
        iv = TickerMembershipInterval(ticker="AAPL", start_date=date(2000, 1, 1), end_date=None)
        assert iv.contains(date(2026, 9, 11)) is True

    def test_contains_false_before_start_date(self) -> None:
        iv = TickerMembershipInterval(ticker="AAPL", start_date=date(2000, 1, 1), end_date=None)
        assert iv.contains(date(1999, 12, 31)) is False

    def test_contains_false_after_end_date(self) -> None:
        iv = TickerMembershipInterval(ticker="FB", start_date=date(2013, 12, 23), end_date=date(2022, 6, 9))
        assert iv.contains(date(2022, 6, 10)) is False

    def test_contains_true_on_boundary_dates_inclusive(self) -> None:
        iv = TickerMembershipInterval(ticker="FB", start_date=date(2013, 12, 23), end_date=date(2022, 6, 9))
        assert iv.contains(date(2013, 12, 23)) is True
        assert iv.contains(date(2022, 6, 9)) is True


class TestConstituentsAsOf:
    def _intervals(self):
        return (
            TickerMembershipInterval(ticker="FB", start_date=date(2013, 12, 23), end_date=date(2022, 6, 9)),
            TickerMembershipInterval(ticker="META", start_date=date(2022, 6, 9), end_date=None),
            TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),
        )

    def test_includes_ticker_active_on_that_date(self) -> None:
        result = constituents_as_of(self._intervals(), date(2020, 1, 1))
        assert result == frozenset({"FB", "GE"})

    def test_excludes_ticker_removed_before_that_date(self) -> None:
        """This is the core new capability over sp500_pit_membership:
        a ticker no longer in today's index but genuinely a member on
        a historical as_of date is still correctly included/excluded
        by its own real interval, not silently dropped or kept
        forever."""
        result = constituents_as_of(self._intervals(), date(2026, 1, 1))
        assert "FB" not in result
        assert "META" in result

    def test_empty_set_for_date_before_any_interval(self) -> None:
        result = constituents_as_of(self._intervals(), date(1990, 1, 1))
        assert result == frozenset()

    def test_ticker_re_entering_the_index_is_captured_in_both_windows(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="AAL", start_date=date(1996, 1, 2), end_date=date(1997, 1, 15)),
            TickerMembershipInterval(ticker="AAL", start_date=date(2015, 3, 23), end_date=date(2024, 9, 23)),
        )
        assert "AAL" in constituents_as_of(intervals, date(1996, 6, 1))
        assert "AAL" not in constituents_as_of(intervals, date(2005, 1, 1))
        assert "AAL" in constituents_as_of(intervals, date(2020, 1, 1))
        assert "AAL" not in constituents_as_of(intervals, date(2025, 1, 1))


class TestHistoryForTicker:
    def test_returns_all_intervals_sorted_ascending(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="AAL", start_date=date(2015, 3, 23), end_date=date(2024, 9, 23)),
            TickerMembershipInterval(ticker="AAL", start_date=date(1996, 1, 2), end_date=date(1997, 1, 15)),
        )
        result = history_for_ticker(intervals, "AAL")
        assert [iv.start_date for iv in result] == [date(1996, 1, 2), date(2015, 3, 23)]

    def test_returns_empty_for_unknown_ticker(self) -> None:
        intervals = (TickerMembershipInterval(ticker="AAPL", start_date=date(2000, 1, 1), end_date=None),)
        assert history_for_ticker(intervals, "UNKNOWN") == ()


class TestRemovedSince:
    def test_only_includes_tickers_with_end_date_on_or_after_cutoff(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="FB", start_date=date(2013, 12, 23), end_date=date(2022, 6, 9)),
            TickerMembershipInterval(ticker="AABA", start_date=date(1999, 12, 8), end_date=date(2017, 6, 19)),
            TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),
        )
        result = removed_since(intervals, date(2020, 1, 1))
        assert [iv.ticker for iv in result] == ["FB"]

    def test_never_includes_still_active_ticker(self) -> None:
        intervals = (TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),)
        assert removed_since(intervals, date(1990, 1, 1)) == ()

    def test_sorted_ascending_by_end_date(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="B", start_date=date(2000, 1, 1), end_date=date(2021, 1, 1)),
            TickerMembershipInterval(ticker="A", start_date=date(2000, 1, 1), end_date=date(2020, 1, 1)),
        )
        result = removed_since(intervals, date(2020, 1, 1))
        assert [iv.ticker for iv in result] == ["A", "B"]
