#!/usr/bin/env python3
"""Computes the `--start` date for the next real scheduled invocation
of `scripts/ingest_real_market_data.py` (ADR-0085).

**The real problem this fixes**: `.github/workflows/paper_trading_
cycle.yml` (ADR-0082) re-requests the ENTIRE historical range
(`$START_DATE` to today) from the market-data provider on every single
scheduled run, relying on `DuckDBDataRepository.append_bars`'s natural-
key dedup to make that safe -- ADR-0082 already documented this as a
"redundant but not incorrect" cost. A real run surfaced that this cost
is not merely redundant: fetching 88 symbols' full ~2.5-year history in
one run exhausted the provider's (Tiingo's) rate limit partway through,
leaving 10 symbols -- including `SPY`, the benchmark -- with ZERO bars
that day (`ingestion_status: PARTIAL_SUCCESS`). Re-requesting the full
range every day does not fix itself over time; it recurs on every run.

**The fix**: request only a small trailing window from the LAST known
bar already in the restored catalog forward, instead of the full fixed
`$START_DATE`. `append_bars`'s own dedup makes re-requesting a few
already-known days safe (and useful -- it catches late-arriving
provider corrections to recent bars), so a `_OVERLAP_DAYS`-day overlap
is deliberate, not a bug. Falls back to the caller's own
`--fallback-start` when the catalog has no price bars yet (a fresh
`--db-path`, e.g. the very first scheduled run, or an artifact-
retention gap) -- exactly the case this function cannot shrink the
request for, since there is no prior bar to compute an overlap from.
"""

from __future__ import annotations

import argparse
import glob
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import duckdb

# Long enough to catch a provider's typical late corporate-action/
# split-adjustment correction window on recent bars, short enough that
# even a daily run's "overlap" request stays a tiny fraction of the
# full historical range this function exists to stop re-requesting.
_OVERLAP_DAYS = 7


def _max_known_bar_date(db_path: Path) -> Optional[date]:
    pattern = str(db_path / "parquet" / "price_bars" / "*.parquet")
    if not glob.glob(pattern):
        return None
    row = duckdb.connect().execute(f"SELECT MAX(timestamp) FROM read_parquet('{pattern}')").fetchone()
    max_ts = row[0] if row else None
    if max_ts is None:
        return None
    return max_ts.date() if isinstance(max_ts, datetime) else max_ts


def compute_start_date(db_path: Path, fallback_start: str) -> str:
    """The date string to pass as `ingest_real_market_data.py --start`.
    Never earlier than `fallback_start` (a fresh catalog, or a catalog
    whose only known bars are already older than the fallback, both
    fall back to it unchanged) and never later than necessary to still
    include the `_OVERLAP_DAYS` trailing window."""
    fallback = datetime.strptime(fallback_start, "%Y-%m-%d").date()
    max_known = _max_known_bar_date(db_path)
    if max_known is None:
        return fallback.isoformat()
    candidate = max_known - timedelta(days=_OVERLAP_DAYS)
    return max(candidate, fallback).isoformat()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="Same --db-path passed to ingest_real_market_data.py")
    parser.add_argument("--fallback-start", required=True, help="YYYY-MM-DD, used when the catalog has no price bars yet")
    args = parser.parse_args(argv)
    print(compute_start_date(args.db_path, args.fallback_start))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
