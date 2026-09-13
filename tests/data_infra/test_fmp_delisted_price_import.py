"""Tests for `data_infra.providers.fmp_delisted_price_import` (Session
37 continued, ADR-0128). Pure functions, no network -- fixture rows are
shaped exactly like the real Financial Modeling Prep `stable/
historical-price-eod/full` response for ATVI the account owner fetched
this session (real values, not invented; see ADR-0128 for the source)."""

from __future__ import annotations

from datetime import date

from data_infra.providers.fmp_delisted_price_import import (
    days_from_nearest_end_date,
    is_dummy_row,
    is_likely_genuine_delisting,
    real_rows,
    to_file_import_row,
)


def _real_last_trading_row() -> dict:
    """The real last trading row for ATVI (2023-10-12) -- Microsoft's
    Activision Blizzard acquisition closed 2023-10-13, so this is the
    real last day of trading, one day before close."""
    return {
        "symbol": "ATVI", "date": "2023-10-12", "open": 94.48, "high": 94.54,
        "low": 94.305, "close": 94.42, "volume": 7323451, "change": -0.06,
        "changePercent": -0.0635055, "vwap": 94.43,
    }


def _real_dummy_row(day: str) -> dict:
    """A real dummy flat-fill row -- FMP keeps returning the exact
    same OHLC with volume=0 after the real last trade."""
    return {
        "symbol": "ATVI", "date": day, "open": 94.42, "high": 94.42,
        "low": 94.42, "close": 94.42, "volume": 0, "change": 0,
        "changePercent": 0, "vwap": 94.42,
    }


class TestIsDummyRow:
    def test_zero_volume_is_dummy(self) -> None:
        assert is_dummy_row(_real_dummy_row("2023-10-20")) is True

    def test_nonzero_volume_is_not_dummy(self) -> None:
        assert is_dummy_row(_real_last_trading_row()) is False


class TestRealRows:
    def test_dummy_tail_is_dropped(self) -> None:
        response = [
            _real_dummy_row("2023-10-20"),
            _real_dummy_row("2023-10-13"),
            _real_last_trading_row(),
        ]
        rows = real_rows(response)
        assert len(rows) == 1
        assert rows[0]["date"] == "2023-10-12"

    def test_rows_are_sorted_ascending_by_date(self) -> None:
        row1 = dict(_real_last_trading_row(), date="2023-10-10")
        row2 = dict(_real_last_trading_row(), date="2023-10-12")
        rows = real_rows([row2, row1])
        assert [r["date"] for r in rows] == ["2023-10-10", "2023-10-12"]

    def test_empty_response_yields_empty_list(self) -> None:
        assert real_rows([]) == []

    def test_all_dummy_response_yields_empty_list(self) -> None:
        response = [_real_dummy_row("2023-10-13"), _real_dummy_row("2023-10-20")]
        assert real_rows(response) == []


class TestToFileImportRow:
    def test_maps_raw_fields(self) -> None:
        row = to_file_import_row(_real_last_trading_row())
        assert row["date"] == "2023-10-12"
        assert row["open"] == 94.48
        assert row["close"] == 94.42
        assert row["volume"] == 7323451

    def test_adjusted_columns_are_always_blank(self) -> None:
        """FMP's response has no split-adjusted fields at all -- must
        never be fabricated from vwap/change/changePercent."""
        row = to_file_import_row(_real_last_trading_row())
        assert row["adj_close"] == ""
        assert row["adj_high"] == ""
        assert row["adj_low"] == ""


class TestDaysFromNearestEndDate:
    def test_exact_match_is_zero_days(self) -> None:
        last = date(2023, 10, 12)
        assert days_from_nearest_end_date(last, [date(2023, 10, 12)]) == 0

    def test_uses_minimum_across_multiple_end_dates(self) -> None:
        last = date(1997, 1, 20)
        gap = days_from_nearest_end_date(last, [date(1997, 1, 15), date(2024, 9, 23)])
        assert gap == 5


class TestIsLikelyGenuineDelisting:
    def test_within_threshold_is_genuine(self) -> None:
        last = date(2023, 10, 12)
        assert is_likely_genuine_delisting(last, [date(2023, 10, 13)]) is True

    def test_beyond_threshold_is_not_genuine(self) -> None:
        last = date(2023, 10, 12)
        assert is_likely_genuine_delisting(last, [date(2020, 1, 1)]) is False

    def test_atvi_real_case_is_classified_genuine(self) -> None:
        """The exact real case this module was built from: real last
        trade 2023-10-12, one day before Microsoft's real acquisition
        close 2023-10-13."""
        last = date(2023, 10, 12)
        assert is_likely_genuine_delisting(last, [date(2023, 10, 13)]) is True
