#!/usr/bin/env python3
"""Selects real S&P 500 removed-ticker candidates whose LAST known
`end_date` is on or after a given cutoff -- the concrete, real filter
this project needed once it confirmed (2026-09-19 recon, real Wayback
Machine CDX + snapshot fetches against AVB) that
`stockanalysis.com` itself did not exist before ~2020, so Wayback
Machine snapshots of its pages cannot help recover price history for
any ticker delisted before that era regardless of how thorough the
scrape is.

Pure, no network call -- takes an already-fetched real
`fja05680/sp500` `sp500_ticker_start_end.csv` (same file
`report_survivorship_price_coverage.py`/`check_wiki_prices_delisted_
coverage.py` already consume) and reuses the exact same
`removed_since()` this project's own audit tooling already uses --
no new selection logic, just a different cutoff for a different real
constraint.

Usage:
    python3 scripts/select_delisted_candidates_since.py \\
        --sp500-intervals-csv ./data/sp500_ticker_start_end.csv \\
        --since 2020-01-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    parse_ticker_intervals,
    removed_since,
)

_DEFAULT_SINCE = "2020-01-01"


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def select_candidates(csv_path: Path, since) -> list[str]:
    intervals = parse_ticker_intervals(csv_path)
    removed = removed_since(intervals, since)
    return sorted({iv.ticker for iv in removed})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sp500-intervals-csv", required=True, type=Path, help="Path to fja05680/sp500's sp500_ticker_start_end.csv")
    parser.add_argument("--since", type=_parse_date, default=_parse_date(_DEFAULT_SINCE), help=f"YYYY-MM-DD -- only tickers whose last known end_date is on/after this (default: {_DEFAULT_SINCE}, the earliest real stockanalysis.com Wayback snapshot found)")
    args = parser.parse_args(argv)

    tickers = select_candidates(args.sp500_intervals_csv, args.since)
    if not tickers:
        print(f"FATAL: no candidates with end_date >= {args.since} found in {args.sp500_intervals_csv}", file=sys.stderr)
        return 1
    print(" ".join(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
