"""Category: point-in-time S&P 500 INDEX CONSTITUENT history from the
`fja05680/sp500` third-party ticker-start/end CSV schema
(`ticker,start_date,end_date`). Uses small synthetic fixture CSVs, not
the real source file -- this project's existing test-fixture discipline
(same pattern as `test_sp500_pit_membership.py`/`test_file_import_
provider.py`)."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone

import pytest

from data_infra.models import UniverseMembership
from data_infra.providers.sp500_index_constituent_history import (
    SP500_INDEX_HISTORICAL_UNIVERSE_NAME,
    TickerMembershipInterval,
    build_sp500_index_universe_memberships,
    constituents_as_of,
    dataset_coverage_start,
    history_for_ticker,
    left_censored_tickers,
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


class TestBuildSp500IndexUniverseMemberships:
    def test_open_ended_interval_becomes_valid_to_none(self) -> None:
        intervals = (TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),)
        memberships = build_sp500_index_universe_memberships(intervals)
        assert memberships == [
            UniverseMembership(
                security_id="GE",
                universe=SP500_INDEX_HISTORICAL_UNIVERSE_NAME,
                valid_from=datetime(1996, 1, 2, tzinfo=timezone.utc),
                valid_to=None,
            )
        ]

    def test_closed_interval_becomes_valid_to_set(self) -> None:
        intervals = (TickerMembershipInterval(ticker="FB", start_date=date(2013, 12, 23), end_date=date(2022, 6, 9)),)
        memberships = build_sp500_index_universe_memberships(intervals)
        assert memberships[0].valid_from == datetime(2013, 12, 23, tzinfo=timezone.utc)
        assert memberships[0].valid_to == datetime(2022, 6, 9, tzinfo=timezone.utc)

    def test_one_membership_record_per_interval_not_per_ticker(self) -> None:
        """A ticker with two non-contiguous intervals (left and
        re-entered the index) must produce two separate
        UniverseMembership records, not one collapsed record --
        DataRepository.get_universe already ORs across multiple
        records for the same security_id, so both stay independently
        queryable."""
        intervals = (
            TickerMembershipInterval(ticker="AAL", start_date=date(1996, 1, 2), end_date=date(1997, 1, 15)),
            TickerMembershipInterval(ticker="AAL", start_date=date(2015, 3, 23), end_date=date(2024, 9, 23)),
        )
        memberships = build_sp500_index_universe_memberships(intervals)
        assert len(memberships) == 2
        assert all(m.security_id == "AAL" for m in memberships)
        assert all(m.universe == SP500_INDEX_HISTORICAL_UNIVERSE_NAME for m in memberships)

    def test_empty_intervals_produces_empty_list(self) -> None:
        assert build_sp500_index_universe_memberships(()) == []

    def test_is_member_at_correctly_answers_from_the_built_records(self) -> None:
        """End-to-end sanity check against UniverseMembership's own
        is_member_at, the exact method DataRepository.get_universe
        calls -- confirms the built records actually answer the
        point-in-time question this whole module exists for."""
        intervals = (
            TickerMembershipInterval(ticker="FB", start_date=date(2013, 12, 23), end_date=date(2022, 6, 9)),
            TickerMembershipInterval(ticker="META", start_date=date(2022, 6, 9), end_date=None),
        )
        memberships = build_sp500_index_universe_memberships(intervals)
        by_ticker = {m.security_id: m for m in memberships}
        assert by_ticker["FB"].is_member_at(datetime(2020, 1, 1, tzinfo=timezone.utc)) is True
        assert by_ticker["FB"].is_member_at(datetime(2023, 1, 1, tzinfo=timezone.utc)) is False
        assert by_ticker["META"].is_member_at(datetime(2023, 1, 1, tzinfo=timezone.utc)) is True


class TestDatasetCoverageStart:
    def test_returns_the_earliest_start_date_across_all_intervals(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),
            TickerMembershipInterval(ticker="TSLA", start_date=date(2020, 12, 21), end_date=None),
        )
        assert dataset_coverage_start(intervals) == date(1996, 1, 2)

    def test_returns_none_for_empty_intervals(self) -> None:
        assert dataset_coverage_start(()) is None


class TestLeftCensoredTickers:
    def test_ticker_starting_at_coverage_start_is_left_censored(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),
            TickerMembershipInterval(ticker="TSLA", start_date=date(2020, 12, 21), end_date=None),
        )
        assert left_censored_tickers(intervals) == frozenset({"GE"})

    def test_ticker_with_a_confirmed_later_start_is_not_left_censored(self) -> None:
        intervals = (
            TickerMembershipInterval(ticker="GE", start_date=date(1996, 1, 2), end_date=None),
            TickerMembershipInterval(ticker="TSLA", start_date=date(2020, 12, 21), end_date=None),
        )
        assert "TSLA" not in left_censored_tickers(intervals)

    def test_re_entering_ticker_is_not_left_censored_by_a_later_interval_sharing_the_coverage_date(self) -> None:
        """A ticker whose GENUINE earliest interval starts well after
        the dataset's coverage start must never be flagged, even if
        (contrived, but must be handled correctly) some other,
        chronologically later interval for the same ticker happened to
        also start exactly on the coverage-start date."""
        intervals = (
            TickerMembershipInterval(ticker="X", start_date=date(2010, 1, 1), end_date=date(2015, 1, 1)),
            TickerMembershipInterval(ticker="Y", start_date=date(1996, 1, 2), end_date=None),
        )
        assert left_censored_tickers(intervals) == frozenset({"Y"})

    def test_empty_intervals_returns_empty_set(self) -> None:
        assert left_censored_tickers(()) == frozenset()
