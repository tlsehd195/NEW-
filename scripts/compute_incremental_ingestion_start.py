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

**ADR-0115 fix (previously a real gap, not just a doc inconsistency)**:
the original version computed a single catalog-wide `MAX(timestamp)`
across every symbol, not per symbol. A symbol that got ZERO bars in a
prior partial-failure run (the exact scenario that motivated this
script -- a rate limit exhausted partway through, per the module
docstring above) never widens that global max backward, since it
contributes no rows at all; the computed `--start` then stays recent
(dominated by the many symbols that DID get bars), and the empty
symbol's true, much older gap is never re-requested on any subsequent
run. This function now computes the `--start` from the LEAST
caught-up symbol among those the run actually requests (an entirely
missing symbol counts as needing the fallback start, same as an empty
catalog), so a partial-failure tail is actually caught up by the next
run instead of being silently, permanently skipped.
"""

from __future__ import annotations

import argparse
import glob
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import BENCHMARK_SYMBOL, PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402

# Mirrors ingest_real_market_data.py's own _UNIVERSES -- kept in sync
# manually since that script is not importable as a library module
# (its own top-level argparse/network-call code runs on import).
_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}

# Long enough to catch a provider's typical late corporate-action/
# split-adjustment correction window on recent bars, short enough that
# even a daily run's "overlap" request stays a tiny fraction of the
# full historical range this function exists to stop re-requesting.
_OVERLAP_DAYS = 7


def _min_known_bar_date(db_path: Path, symbols: Sequence[str]) -> Optional[date]:
    """The per-symbol `MAX(timestamp)` among catalog bars, minimized
    across `symbols` -- a symbol with zero bars in the catalog
    contributes no row and is therefore treated as needing the
    fallback (see `compute_start_date`), so the result is only as
    recent as the LEAST caught-up symbol requested, never skewed
    recent by symbols that already have plenty of history."""
    pattern = str(db_path / "parquet" / "price_bars" / "*.parquet")
    if not glob.glob(pattern):
        return None
    placeholders = ",".join("?" for _ in symbols)
    sql = f"SELECT security_id, MAX(timestamp) FROM read_parquet(?) WHERE security_id IN ({placeholders}) GROUP BY security_id"
    rows = duckdb.connect().execute(sql, [pattern, *symbols]).fetchall()
    known = {sid: (ts.date() if isinstance(ts, datetime) else ts) for sid, ts in rows}
    if len(known) < len(set(symbols)):
        # At least one requested symbol has zero bars in the catalog
        # at all -- its own true gap needs the full fallback range,
        # which is earlier than any per-symbol max could be.
        return None
    return min(known.values())


def compute_start_date(db_path: Path, fallback_start: str, symbols: Sequence[str]) -> str:
    """The date string to pass as `ingest_real_market_data.py --start`.
    Never earlier than `fallback_start` (a fresh catalog, or a catalog
    whose least-caught-up requested symbol is already older than the
    fallback, both fall back to it unchanged) and never later than
    necessary to still include the `_OVERLAP_DAYS` trailing window for
    every requested symbol, including one with zero bars so far."""
    fallback = datetime.strptime(fallback_start, "%Y-%m-%d").date()
    min_known = _min_known_bar_date(db_path, symbols)
    if min_known is None:
        return fallback.isoformat()
    candidate = min_known - timedelta(days=_OVERLAP_DAYS)
    return max(candidate, fallback).isoformat()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="Same --db-path passed to ingest_real_market_data.py")
    parser.add_argument("--fallback-start", required=True, help="YYYY-MM-DD, used when the catalog has no price bars yet")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE", help="Same --universe passed to ingest_real_market_data.py -- determines which symbols' catch-up state is checked. SPY is always additionally included, matching that script's own benchmark handling.")
    parser.add_argument("--symbols", nargs="+", default=None, help="Same --symbols override passed to ingest_real_market_data.py, if used instead of --universe")
    args = parser.parse_args(argv)

    if args.symbols is not None:
        symbols = list(args.symbols)
    else:
        symbols = list(_UNIVERSES[args.universe].symbol_ids) + [BENCHMARK_SYMBOL]

    print(compute_start_date(args.db_path, args.fallback_start, symbols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
