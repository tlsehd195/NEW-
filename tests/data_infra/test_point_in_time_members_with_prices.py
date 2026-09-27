"""ADR-0224: point_in_time_members_with_prices picks the window's
members that have bars and reports per-date member coverage."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backtest"))

from backtest_helpers import build_repository, make_bars, make_security, trading_days  # noqa: E402

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    parse_ticker_intervals,
    point_in_time_members_with_prices,
)


def test_members_with_prices_and_yearly_coverage(tmp_path: Path) -> None:
    csv_path = tmp_path / "sp500.csv"
    csv_path.write_text(
        "ticker,start_date,end_date\n"
        "KEEP,1996-01-02,\n"
        "GONE,1996-01-02,2021-06-01\n"  # left the index, has bars
        "NODATA,1996-01-02,2021-06-01\n"  # left the index, never ingested
        "LATE,2023-01-03,\n"  # joined after the window
    )
    days = trading_days(date(2020, 12, 1), date(2021, 3, 1))
    repo = build_repository(
        bars=make_bars("KEEP", days, [10.0] * len(days)) + make_bars("GONE", days, [20.0] * len(days))
        + make_bars("LATE", days, [30.0] * len(days)),
        securities=[make_security(s, s) for s in ("KEEP", "GONE", "LATE")],
    )
    start = datetime(2020, 12, 1, tzinfo=timezone.utc)
    end = datetime(2021, 12, 31, tzinfo=timezone.utc)

    ids, report = point_in_time_members_with_prices(parse_ticker_intervals(csv_path), repo, start=start, end=end)

    assert ids == ["GONE", "KEEP"]
    assert report["members_without_price_data"] == ["NODATA"]
    assert report["coverage_by_year"] == [{"date": "2021-01-01", "members": 3, "with_price_data": 2}]
    assert report["summary"]["min_member_coverage"] == 2 / 3
