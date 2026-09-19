#!/usr/bin/env python3
"""Selects the REAL, point-in-time-correct S&P 500 constituent set as of
a given historical date -- the concrete "limited connection" (account
owner's own scoping choice, independent audit P1-2) between this
project's already-existing point-in-time index-membership data
(`data_infra.providers.sp500_index_constituent_history`, built from the
real, MIT-licensed `fja05680/sp500` dataset, ADR-0? ) and any script
that wants an actually historically-accurate universe instead of
`data_infra.universe`'s `PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE4`
(both of which only ever contain TODAY's current holdings, per those
definitions' own docstrings).

Pure, no network call -- mirrors `select_delisted_candidates_since.py`'s
own established shape exactly: takes an already-fetched real
`sp500_ticker_start_end.csv` and reuses this project's own existing
`parse_ticker_intervals`/`constituents_as_of` (no new selection logic).

**This does NOT itself close the audit's `RESEARCH_UNIVERSE_STAGE4`
survivorship-bias gap** (see ADR-0176's own "Negative / Trade-offs"
section) -- it makes the already-existing real point-in-time data
usable as an explicit, opt-in `--symbols` list for
`ingest_real_market_data.py` and (via `run_long_horizon_validation.py`'s
new `--point-in-time-as-of`/`--point-in-time-csv-path` flags) as an
opt-in backtest universe for ONE historical date. Every existing
default (production paper trading, `RESEARCH_UNIVERSE_STAGE4` itself)
is completely untouched.

Usage:
    python3 scripts/select_point_in_time_universe.py \\
        --sp500-intervals-csv ./data/sp500_ticker_start_end.csv \\
        --as-of 2015-01-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    constituents_as_of,
    parse_ticker_intervals,
)


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def select_universe(csv_path: Path, as_of) -> list[str]:
    intervals = parse_ticker_intervals(csv_path)
    return sorted(constituents_as_of(intervals, as_of))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sp500-intervals-csv", required=True, type=Path, help="Path to fja05680/sp500's sp500_ticker_start_end.csv")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD -- the real, historical S&P 500 constituent set on this exact date, including tickers no longer in today's index")
    args = parser.parse_args(argv)

    tickers = select_universe(args.sp500_intervals_csv, args.as_of)
    if not tickers:
        print(
            f"FATAL: no real S&P 500 constituents found for {args.as_of} in {args.sp500_intervals_csv} "
            "-- this date likely falls outside the dataset's own coverage range "
            "(data_infra.providers.sp500_index_constituent_history.dataset_coverage_start), "
            "never a genuinely empty index.",
            file=sys.stderr,
        )
        return 1
    print(" ".join(tickers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
