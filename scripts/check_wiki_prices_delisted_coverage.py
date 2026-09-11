#!/usr/bin/env python3
"""Checks how many REAL historical S&P 500 constituents that have since
left the index (`data_infra.providers.sp500_index_constituent_history`,
ADR-0120/ADR-0122, real `fja05680/sp500` data) actually have real
(volume > 0) price rows in a downloaded Quandl WIKI/PRICES export
(ADR-0126) -- a bulk version of the manual `grep`/`awk` spot-checks
(`DELL`/`DTV`/`LNKD`/`TWX`/`YHOO` confirmed present; `LEH`/`BSC`/`WCOM`/
`MER`/`ENRN` confirmed absent) this session ran by hand.

Makes NO network call -- it only reads two local files: the already-
fetched `sp500_ticker_start_end.csv` (`scripts/fetch_sp500_index_
history.py --save-csv ...`) and the user's downloaded `WIKI_PRICES.csv`
(ADR-0126). Streams the (potentially multi-GB) WIKI file once.

For each candidate ticker (every ticker with a real `end_date` in the
S&P 500 interval file -- i.e., it left the index at some point, the
exact class of security this project's survivorship-bias problem is
about), reports: real (volume > 0) row count, first/last real date,
and the ticker's own recorded S&P 500 `end_date`(s) for comparison
(a genuine match, like DELL's 2013-10-29 real-data end lining up with
its real LBO close, is itself corroborating evidence -- a caller
should look at this, not just trust a nonzero row count blindly).

Usage:
    python3 scripts/check_wiki_prices_delisted_coverage.py \\
        --sp500-intervals-csv ./data/sp500_ticker_start_end.csv \\
        --wiki-prices-csv /path/to/WIKI_PRICES.csv \\
        --out ./data/wiki_prices_delisted_coverage_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.sp500_index_constituent_history import parse_ticker_intervals  # noqa: E402

_SOURCE_REQUIRED_COLUMNS = ("ticker", "date", "volume")


def _removed_tickers_with_end_dates(intervals) -> dict[str, list[str]]:
    end_dates_by_ticker: dict[str, list[str]] = {}
    for iv in intervals:
        if iv.end_date is None:
            continue
        end_dates_by_ticker.setdefault(iv.ticker, []).append(iv.end_date.isoformat())
    return end_dates_by_ticker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sp500-intervals-csv", required=True, type=Path, help="Path to fja05680/sp500's sp500_ticker_start_end.csv")
    parser.add_argument("--wiki-prices-csv", required=True, type=Path, help="Path to the downloaded WIKI_PRICES.csv")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the JSON coverage report")
    args = parser.parse_args(argv)

    if not args.sp500_intervals_csv.is_file():
        print(f"FATAL: {args.sp500_intervals_csv} does not exist", file=sys.stderr)
        return 1
    if not args.wiki_prices_csv.is_file():
        print(f"FATAL: {args.wiki_prices_csv} does not exist", file=sys.stderr)
        return 1

    intervals = parse_ticker_intervals(args.sp500_intervals_csv)
    end_dates_by_ticker = _removed_tickers_with_end_dates(intervals)
    candidates = set(end_dates_by_ticker)
    if not candidates:
        print("FATAL: no removed (end_date set) tickers found in the S&P 500 interval file", file=sys.stderr)
        return 1

    real_dates_by_ticker: dict[str, list[str]] = {t: [] for t in candidates}

    with args.wiki_prices_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing_columns = set(_SOURCE_REQUIRED_COLUMNS) - set(reader.fieldnames or ())
        if missing_columns:
            print(
                f"FATAL: {args.wiki_prices_csv} is missing required column(s) {sorted(missing_columns)}",
                file=sys.stderr,
            )
            return 1
        for row in reader:
            ticker = row["ticker"]
            if ticker not in candidates:
                continue
            try:
                volume = float(row["volume"])
            except ValueError:
                continue
            if volume == 0.0:
                continue
            real_dates_by_ticker[ticker].append(row["date"])

    covered = sorted(t for t, dates in real_dates_by_ticker.items() if dates)
    not_covered = sorted(t for t in candidates if not real_dates_by_ticker[t])

    per_ticker_report = {}
    for ticker in covered:
        dates = sorted(real_dates_by_ticker[ticker])
        per_ticker_report[ticker] = {
            "real_row_count": len(dates),
            "first_real_date": dates[0],
            "last_real_date": dates[-1],
            "sp500_end_dates": sorted(end_dates_by_ticker[ticker]),
        }

    report = {
        "candidate_ticker_count": len(candidates),
        "covered_ticker_count": len(covered),
        "not_covered_ticker_count": len(not_covered),
        "covered_tickers": per_ticker_report,
        "not_covered_tickers": not_covered,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"Candidate (ever-removed-from-S&P-500) tickers checked: {len(candidates)}")
    print(f"Covered (real volume > 0 rows found) in WIKI Prices: {len(covered)}")
    print(f"Not covered: {len(not_covered)}")
    print(f"Full report written to: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
