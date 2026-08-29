"""Category: point-in-time S&P 500 membership reconstruction from the
`hanshof/sp500_constituents` third-party Wikipedia-scrape CSV schema
(`date,tickers`). Uses small synthetic fixture CSVs, not the real
6.7MB source file -- this project's existing test-fixture discipline
(same pattern as `test_file_import_provider.py`), and specifically
constructs a deliberate gap to exercise the honest uncertainty
reporting the module promises."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from data_infra.providers.sp500_pit_membership import (
    MembershipSnapshot,
    membership_as_of,
    parse_snapshots,
    reconstruct_intervals,
)


def _write_csv(tmp_path, rows: list[tuple[str, str]]):
    """Mirrors the real source file's quoting: a `tickers` field
    containing embedded commas must be quoted, exactly like the real
    `sp_500_historical_components.csv` (e.g. `1996-01-02,"AAL,AAMRQ,..."`)."""
    path = tmp_path / "sp_500_historical_components.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "tickers"])
        writer.writerows(rows)
    return path


class TestParseSnapshots:
    def test_parses_and_sorts_ascending(self, tmp_path) -> None:
        path = _write_csv(
            tmp_path,
            [("2020-06-01", "AAPL,MSFT"), ("2020-01-01", "AAPL")],
        )
        snapshots = parse_snapshots(path)
        assert [s.as_of for s in snapshots] == [date(2020, 1, 1), date(2020, 6, 1)]
        assert snapshots[1].tickers == frozenset({"AAPL", "MSFT"})

    def test_rejects_wrong_schema(self, tmp_path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text("symbol,security\nAAPL,Apple")
        with pytest.raises(ValueError):
            parse_snapshots(path)

    def test_empty_ticker_field_produces_empty_set(self, tmp_path) -> None:
        path = _write_csv(tmp_path, [("2020-01-01", "")])
        snapshots = parse_snapshots(path)
        assert snapshots[0].tickers == frozenset()


class TestMembershipAsOf:
    def _snapshots(self):
        return (
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 6, 1), tickers=frozenset({"AAPL", "MSFT"})),
        )

    def test_exact_snapshot_date_has_zero_staleness(self) -> None:
        result = membership_as_of(self._snapshots(), date(2020, 1, 1))
        assert result.staleness_days == 0
        assert result.tickers == frozenset({"AAPL"})

    def test_forward_fills_from_nearest_prior_snapshot(self) -> None:
        result = membership_as_of(self._snapshots(), date(2020, 3, 15))
        assert result.snapshot_used == date(2020, 1, 1)
        assert result.staleness_days == (date(2020, 3, 15) - date(2020, 1, 1)).days
        assert result.tickers == frozenset({"AAPL"})  # MSFT not yet added as of this snapshot

    def test_returns_none_before_first_snapshot(self) -> None:
        result = membership_as_of(self._snapshots(), date(2019, 1, 1))
        assert result is None

    def test_uses_most_recent_snapshot_after_the_last_one(self) -> None:
        result = membership_as_of(self._snapshots(), date(2025, 1, 1))
        assert result.snapshot_used == date(2020, 6, 1)
        assert result.tickers == frozenset({"AAPL", "MSFT"})


class TestReconstructIntervals:
    def test_empty_snapshots_returns_empty(self) -> None:
        assert reconstruct_intervals(()) == ()

    def test_ticker_present_in_first_snapshot_is_left_censored(self) -> None:
        snapshots = (
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 6, 1), tickers=frozenset({"AAPL"})),
        )
        intervals = {i.ticker: i for i in reconstruct_intervals(snapshots)}
        assert intervals["AAPL"].left_censored is True
        assert intervals["AAPL"].added_uncertainty_days == 0

    def test_ticker_present_in_last_snapshot_is_right_censored(self) -> None:
        snapshots = (
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 6, 1), tickers=frozenset({"AAPL"})),
        )
        intervals = {i.ticker: i for i in reconstruct_intervals(snapshots)}
        assert intervals["AAPL"].right_censored is True
        assert intervals["AAPL"].removed_uncertainty_days == 0

    def test_ticker_added_mid_sequence_reports_gap_before_it_appeared(self) -> None:
        snapshots = (
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 3, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 6, 1), tickers=frozenset({"AAPL", "TSLA"})),
        )
        intervals = {i.ticker: i for i in reconstruct_intervals(snapshots)}
        tsla = intervals["TSLA"]
        assert tsla.left_censored is False
        assert tsla.first_seen == date(2020, 6, 1)
        # TSLA wasn't in the 2020-03-01 snapshot, so its true addition
        # date is uncertain within that gap -- not the 2020-06-01 date itself.
        assert tsla.added_uncertainty_days == (date(2020, 6, 1) - date(2020, 3, 1)).days

    def test_ticker_removed_mid_sequence_reports_gap_after_it_disappeared(self) -> None:
        snapshots = (
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"AAPL", "GE"})),
            MembershipSnapshot(as_of=date(2020, 3, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 6, 1), tickers=frozenset({"AAPL"})),
        )
        intervals = {i.ticker: i for i in reconstruct_intervals(snapshots)}
        ge = intervals["GE"]
        assert ge.right_censored is False
        assert ge.last_seen == date(2020, 1, 1)
        assert ge.removed_uncertainty_days == (date(2020, 3, 1) - date(2020, 1, 1)).days

    def test_large_documented_gap_produces_large_uncertainty_not_a_precise_date(self) -> None:
        """Regression guard for this module's core honesty promise: a
        real ~1-year gap (like the actual 2019-2022 dormancy this
        session found in the real dataset) must show up as a large
        uncertainty window, never be silently smoothed into an exact
        date."""
        snapshots = (
            MembershipSnapshot(as_of=date(2019, 1, 1), tickers=frozenset({"OLD"})),
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"NEW"})),  # ~1-year gap
        )
        intervals = {i.ticker: i for i in reconstruct_intervals(snapshots)}
        assert intervals["OLD"].removed_uncertainty_days == 365
        assert intervals["NEW"].added_uncertainty_days == 365

    def test_unchanged_membership_across_snapshots_has_zero_gap(self) -> None:
        snapshots = (
            MembershipSnapshot(as_of=date(2020, 1, 1), tickers=frozenset({"AAPL"})),
            MembershipSnapshot(as_of=date(2020, 1, 2), tickers=frozenset({"AAPL"})),
        )
        intervals = {i.ticker: i for i in reconstruct_intervals(snapshots)}
        assert intervals["AAPL"].left_censored is True  # still censored, present since the start
        assert intervals["AAPL"].right_censored is True
