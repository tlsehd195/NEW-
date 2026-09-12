#!/usr/bin/env python3
"""Fetches real historical price data for candidate delisted tickers
from Financial Modeling Prep (FMP)'s `stable/historical-price-eod/full`
API, filters the confirmed dummy tail (`data_infra.providers.fmp_
delisted_price_import`, ADR-0128), classifies genuine delistings
against this project's own S&P 500 removal dates (`data/sp500_ticker_
start_end.csv`, ADR-0120), and writes:

  1. One `{security_id}.csv` per ticker classified `likely_genuine_
     delisting`, in the schema `data_infra.providers.file_import.
     LocalFileDataProvider` expects (ready for `scripts/import_
     external_market_data.py`).
  2. A JSON coverage report (same shape as `check_wiki_prices_
     delisted_coverage.py`'s own report, ADR-0126, for direct
     comparison between the two free sources).

This is this project's second free source for real delisted-ticker
prices (`ADR-0126` was the first, Quandl WIKI Prices, frozen at
2018-03-27). Unlike that source, FMP's free tier is CONTINUOUSLY
UPDATED -- its own delisted-companies list included entries dated
within days of when this script was written -- so this is the
candidate source for the window WIKI Prices cannot cover at all.

**Makes real network calls** (one GET per candidate ticker, with a
configurable delay between requests to stay well under the free tier's
250-requests/day limit) -- like `fetch_sp500_index_history.py`, this
script is never imported or executed by the automated test suite; only
the pure functions in `data_infra.providers.fmp_delisted_price_import`
are unit tested.

**API key handling**: read from `--api-key` or the `FMP_API_KEY`
environment variable -- never hardcoded in this file, never logged,
never written into the JSON report or any CSV this script produces.

Usage:
    export FMP_API_KEY=your_real_key
    python3 scripts/fetch_fmp_delisted_prices.py \\
        --sp500-intervals-csv ./data/sp500_ticker_start_end.csv \\
        --since 2018-03-28 \\
        --out-dir ./fmp_converted \\
        --report-out ./data/fmp_delisted_coverage_report.json

`--since` should be the day after the last source's coverage ends
(2018-03-28, the day after WIKI Prices' 2018-03-27 freeze) to avoid
spending free-tier request budget re-checking tickers ADR-0126 already
covers.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.fmp_delisted_price_import import (  # noqa: E402
    days_from_nearest_end_date,
    is_likely_genuine_delisting,
    real_rows,
    to_file_import_row,
)
from data_infra.providers.sp500_index_constituent_history import parse_ticker_intervals  # noqa: E402

_BASE_URL = "https://financialmodelingprep.com/stable/historical-price-eod/full"
_OUTPUT_COLUMNS = ("date", "open", "high", "low", "close", "volume", "adj_close", "adj_high", "adj_low")


def _fetch(symbol: str, api_key: str, *, from_date: str, to_date: str, timeout: float) -> list[dict]:
    params = urllib.parse.urlencode({"symbol": symbol, "from": from_date, "to": to_date, "apikey": api_key})
    url = f"{_BASE_URL}?{params}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{exc.reason}") from exc
    data = json.loads(body)
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected response shape: {data!r}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sp500-intervals-csv", required=True, type=Path, help="Path to fja05680/sp500's sp500_ticker_start_end.csv")
    parser.add_argument("--since", required=True, type=str, help="YYYY-MM-DD; only check tickers with an S&P 500 end_date on/after this date")
    parser.add_argument("--from-date", type=str, default="1990-01-01", help="Earliest date to request from FMP per ticker (default: 1990-01-01)")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory to write one <security_id>.csv per covered, likely-genuine ticker")
    parser.add_argument("--report-out", required=True, type=Path, help="Where to write the JSON coverage report")
    parser.add_argument("--api-key", type=str, default=None, help="FMP API key (or set FMP_API_KEY env var -- never hardcode this)")
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="Delay between requests (default: 0.5s)")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    args = parser.parse_args(argv)

    api_key = args.api_key or os.environ.get("FMP_API_KEY")
    if not api_key:
        print("FATAL: no API key given (--api-key or FMP_API_KEY env var)", file=sys.stderr)
        return 1

    if not args.sp500_intervals_csv.is_file():
        print(f"FATAL: {args.sp500_intervals_csv} does not exist", file=sys.stderr)
        return 1

    since = datetime.strptime(args.since, "%Y-%m-%d").date()
    to_date = date.today().isoformat()

    intervals = parse_ticker_intervals(args.sp500_intervals_csv)
    end_dates_by_ticker: dict[str, list[date]] = {}
    for iv in intervals:
        if iv.end_date is not None and iv.end_date >= since:
            end_dates_by_ticker.setdefault(iv.ticker, []).append(iv.end_date)

    if not end_dates_by_ticker:
        print(f"FATAL: no tickers found with an S&P 500 end_date on/after {since}", file=sys.stderr)
        return 1

    candidates = sorted(end_dates_by_ticker)
    print(f"Checking {len(candidates)} candidate ticker(s) against FMP...", flush=True)

    covered_report: dict[str, dict] = {}
    not_covered: list[str] = []
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for i, symbol in enumerate(candidates):
        try:
            response = _fetch(symbol, api_key, from_date=args.from_date, to_date=to_date, timeout=args.timeout)
        except RuntimeError as exc:
            print(f"  [{i + 1}/{len(candidates)}] {symbol}: FETCH ERROR ({exc})", file=sys.stderr)
            not_covered.append(symbol)
            time.sleep(args.sleep_seconds)
            continue

        rows = real_rows(response)
        if not rows:
            print(f"  [{i + 1}/{len(candidates)}] {symbol}: no real rows")
            not_covered.append(symbol)
            time.sleep(args.sleep_seconds)
            continue

        last_real_date = date.fromisoformat(rows[-1]["date"])
        gap_days = days_from_nearest_end_date(last_real_date, end_dates_by_ticker[symbol])
        genuine = is_likely_genuine_delisting(last_real_date, end_dates_by_ticker[symbol])
        covered_report[symbol] = {
            "real_row_count": len(rows),
            "first_real_date": rows[0]["date"],
            "last_real_date": rows[-1]["date"],
            "sp500_end_dates": [d.isoformat() for d in sorted(end_dates_by_ticker[symbol])],
            "days_from_nearest_sp500_end_date": gap_days,
            "likely_genuine_delisting": genuine,
        }
        status = "GENUINE" if genuine else "still-trading-after-removal"
        print(f"  [{i + 1}/{len(candidates)}] {symbol}: {len(rows)} real row(s), {rows[0]['date']} to {rows[-1]['date']} ({status})")

        if genuine:
            out_path = args.out_dir / f"{symbol}.csv"
            with out_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_OUTPUT_COLUMNS)
                writer.writeheader()
                writer.writerows(to_file_import_row(r) for r in rows)

        time.sleep(args.sleep_seconds)

    genuine_count = sum(1 for r in covered_report.values() if r["likely_genuine_delisting"])
    report = {
        "candidate_ticker_count": len(candidates),
        "covered_ticker_count": len(covered_report),
        "not_covered_ticker_count": len(not_covered),
        "likely_genuine_delisting_count": genuine_count,
        "likely_still_trading_after_index_removal_count": len(covered_report) - genuine_count,
        "genuine_delisting_gap_days_threshold": 90,
        "covered_tickers": covered_report,
        "not_covered_tickers": sorted(not_covered),
    }
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2))

    print()
    print(f"Candidates checked: {len(candidates)}")
    print(f"Covered: {len(covered_report)}, of which likely genuine delistings: {genuine_count}")
    print(f"Not covered: {len(not_covered)}")
    print(f"Report written to: {args.report_out}")
    print(f"Per-symbol CSVs (genuine only) written to: {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
