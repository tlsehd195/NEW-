#!/usr/bin/env python3
"""Reports, for a given point in time, how much of this project's real
S&P 500 removed-ticker population (`data/sp500_ticker_start_end.csv`,
`fja05680/sp500`, ADR-0120) actually has real price data available in
an existing DuckDB catalog -- the concrete, actionable "how exposed is
a backtest over this window to survivorship bias, right now" question
`data_infra.universe.audit_survivorship` cannot answer (that function
audits universe MEMBERSHIP METADATA quality, never whether the
underlying PRICE DATA needed to backtest through a real delisting
exists at all).

Makes NO network call -- it only reads the local `sp500_ticker_
start_end.csv` and queries an existing local DuckDB catalog for
`get_bars` results -- so, unlike `scripts/fetch_fmp_delisted_prices.py`
(which makes real HTTP calls), this script IS exercised by the
automated test suite.

Usage:
    python3 scripts/report_survivorship_price_coverage.py \\
        --sp500-intervals-csv ./data/sp500_ticker_start_end.csv \\
        --db-path ./data/wiki_prices_delisted_db \\
        --since 2010-01-01 \\
        --as-of 2026-09-12 \\
        --out ./data/survivorship_price_coverage_report.json

`--db-path` should point at whichever DuckDB catalog holds the price
bars you want checked -- e.g. the catalog `scripts/import_external_
market_data.py` populated with the real delisted-ticker prices from
ADR-0126/ADR-0128, or a project's actual backtest catalog, to see
exactly which historical constituents removed since `--since` this
project can and cannot show real prices for.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    parse_ticker_intervals,
    price_data_coverage_for_removed_securities,
)
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sp500-intervals-csv", required=True, type=Path, help="Path to fja05680/sp500's sp500_ticker_start_end.csv")
    parser.add_argument("--db-path", required=True, type=Path, help="Existing DuckDB catalog directory to check for real price bars")
    parser.add_argument("--since", required=True, type=str, help="YYYY-MM-DD; only check tickers removed from the S&P 500 on/after this date")
    parser.add_argument("--as-of", required=True, type=str, help="YYYY-MM-DD; as_of_time for the bar query (also the query window's end)")
    parser.add_argument("--price-history-start", type=str, default="1900-01-01", help="Earliest date to check for bars (default: 1900-01-01)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the JSON coverage report")
    args = parser.parse_args(argv)

    if not args.sp500_intervals_csv.is_file():
        print(f"FATAL: {args.sp500_intervals_csv} does not exist", file=sys.stderr)
        return 1
    if not args.db_path.exists():
        print(f"FATAL: {args.db_path} does not exist", file=sys.stderr)
        return 1

    intervals = parse_ticker_intervals(args.sp500_intervals_csv)
    since = _parse_date(args.since)
    as_of_time = _parse_datetime_utc(args.as_of)
    price_history_start = _parse_datetime_utc(args.price_history_start)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    try:
        repository = DuckDBDataRepository(engine)
        report = price_data_coverage_for_removed_securities(
            intervals,
            repository,
            since=since,
            price_history_start=price_history_start,
            as_of_time=as_of_time,
        )
    finally:
        engine.close()

    if report.checked_ticker_count == 0:
        print(f"FATAL: no tickers were removed from the S&P 500 on/after {since}", file=sys.stderr)
        return 1

    output = {
        "since": report.since.isoformat(),
        "as_of_time": report.as_of_time.isoformat(),
        "checked_ticker_count": report.checked_ticker_count,
        "covered_ticker_count": report.covered_ticker_count,
        "not_covered_ticker_count": report.not_covered_ticker_count,
        "coverage_percentage": round(report.coverage_percentage, 1),
        "covered_tickers": list(report.covered_tickers),
        "not_covered_tickers": list(report.not_covered_tickers),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2))

    print(f"Tickers removed from the S&P 500 on/after {since}: {report.checked_ticker_count}")
    print(f"Real price data available for: {report.covered_ticker_count} ({report.coverage_percentage:.1f}%)")
    print(f"Missing (real, current survivorship-bias exposure for this window): {report.not_covered_ticker_count}")
    print(f"Report written to: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
