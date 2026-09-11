#!/usr/bin/env python3
"""Fetches the real, MIT-licensed `fja05680/sp500` ticker-start/end
history CSV and computes a point-in-time S&P 500 index constituent
report -- the fetch+compute counterpart of
`data_infra.providers.sp500_index_constituent_history` (see that
module's docstring for the full source evaluation and honesty
discipline).

**Makes a real network call** to `raw.githubusercontent.com` -- unlike
every commercial market-data provider host this project has tested,
GitHub's raw-content host IS reachable from this sandboxed session
(confirmed directly, `curl`/`WebFetch`, this session). This mirrors
`scripts/compute_sp500_pit_listed_from.py`'s own precedent of doing a
real computation directly in-session once GitHub reachability was
confirmed (ADR-0061) -- the difference here is this script also
performs the download itself, since the source file is a small
(~40KB) single CSV directly fetchable over HTTPS, not a 6.7MB file
that needed a full `git clone`.

Because this script makes a real network call, it is -- like
`ingest_insider_transactions.py`/`ingest_fundamentals_data.py` -- never
imported or executed by the automated test suite; only the pure
`sp500_index_constituent_history` parsing/query module is
unit-tested.

`--out` always receives a JSON report; `--save-csv` additionally saves
the raw fetched CSV to a local path (not committed to this repository,
matching `LocalFileDataProvider`/ADR-0037's external-dataset
discipline -- large or frequently-refreshed third-party source files
are never checked in, only the code that consumes them).

`--db-path`, when supplied, additionally PERSISTS every parsed
interval as a `UniverseMembership` record (via `data_infra.providers.
sp500_index_constituent_history.build_sp500_index_universe_
memberships`) into a DuckDB catalog at that path, under the
`SP500_INDEX_HISTORICAL` universe name -- making the data queryable
afterward via `DuckDBDataRepository.get_universe("US_EQUITY",
SP500_INDEX_HISTORICAL_UNIVERSE_NAME, as_of_time=...)`. This does NOT
touch `SecurityMaster`/price-bar tables or any existing universe
(`PILOT_UNIVERSE_V1`/`RESEARCH_UNIVERSE_STAGE*`) -- it is purely
additive rows in the same `universe_membership` table, distinguished
by the `universe` column. The underlying insert is idempotent
(`ON CONFLICT (security_id, universe, valid_from) DO NOTHING`,
`storage.data_repository.DuckDBDataRepository.add_universe_membership`,
unmodified) -- re-running this script against a fresh copy of the
source file is always safe.

Usage:
    python3 scripts/fetch_sp500_index_history.py \\
        --as-of 2026-09-11 \\
        --out ./data/sp500_index_membership_report.json \\
        --save-csv ./data/sp500_ticker_start_end.csv \\
        --db-path ./data/sp500_index_history_db
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    SP500_INDEX_HISTORICAL_UNIVERSE_NAME,
    build_sp500_index_universe_memberships,
    constituents_as_of,
    history_for_ticker,
    parse_ticker_intervals,
    removed_since,
)
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_SOURCE_URL = (
    "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
)
_SOURCE_NAME = "fja05680_sp500_ticker_start_end"


def _fetch(url: str, *, timeout: float) -> str:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {url} failed with status {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GET {url} failed: {exc.reason}") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--as-of", required=True, type=str, help="YYYY-MM-DD date to compute index constituents as of")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the JSON report")
    parser.add_argument("--save-csv", type=Path, default=None, help="Optional local path to also save the raw fetched CSV")
    parser.add_argument("--removed-since", type=str, default=None, help="Optional YYYY-MM-DD; also report tickers removed on/after this date")
    parser.add_argument("--tickers", nargs="+", default=None, help="Optional explicit ticker list to report full history for")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds (default: 30)")
    parser.add_argument("--db-path", type=Path, default=None, help="Optional directory for a DuckDB catalog to persist every interval as a UniverseMembership record (created if it does not exist)")
    args = parser.parse_args(argv)

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    retrieved_at = datetime.now(timezone.utc)

    print(f"Fetching {_SOURCE_URL} ...", flush=True)
    try:
        raw_csv = _fetch(_SOURCE_URL, timeout=args.timeout)
    except RuntimeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    if args.save_csv is not None:
        args.save_csv.parent.mkdir(parents=True, exist_ok=True)
        args.save_csv.write_text(raw_csv, encoding="utf-8")
        csv_path = args.save_csv
        print(f"Saved raw CSV to {csv_path}", flush=True)
    else:
        import tempfile

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
        tmp.write(raw_csv)
        tmp.close()
        csv_path = Path(tmp.name)

    intervals = parse_ticker_intervals(csv_path)
    print(f"Parsed {len(intervals)} ticker-interval rows.", flush=True)

    constituents = sorted(constituents_as_of(intervals, as_of))
    print(f"{len(constituents)} tickers were S&P 500 constituents as of {as_of}.", flush=True)

    removed_report = None
    if args.removed_since is not None:
        removed_from = datetime.strptime(args.removed_since, "%Y-%m-%d").date()
        removed = removed_since(intervals, removed_from)
        removed_report = [
            {"ticker": iv.ticker, "start_date": iv.start_date.isoformat(), "end_date": iv.end_date.isoformat()}
            for iv in removed
        ]
        print(f"{len(removed_report)} tickers left the index on/after {removed_from}.", flush=True)

    ticker_history_report = None
    if args.tickers is not None:
        ticker_history_report = {
            t: [
                {"start_date": iv.start_date.isoformat(), "end_date": iv.end_date.isoformat() if iv.end_date else None}
                for iv in history_for_ticker(intervals, t)
            ]
            for t in args.tickers
        }

    persisted_count = None
    if args.db_path is not None:
        engine = StorageEngine(StorageConfig(root_dir=args.db_path))
        repository = DuckDBDataRepository(engine)
        memberships = build_sp500_index_universe_memberships(intervals)
        for record in memberships:
            repository.add_universe_membership(record)
        persisted_count = len(memberships)
        print(
            f"Persisted {persisted_count} UniverseMembership records under "
            f"{SP500_INDEX_HISTORICAL_UNIVERSE_NAME!r} to {args.db_path}",
            flush=True,
        )

    checksum = compute_data_version({
        "as_of": as_of.isoformat(),
        "constituents": constituents,
        "interval_count": len(intervals),
    })

    report = {
        "note": (
            "Real fja05680/sp500-derived (https://github.com/fja05680/sp500, MIT license) "
            "point-in-time S&P 500 index constituent membership -- see "
            "data_infra.providers.sp500_index_constituent_history module docstring for the "
            "full source evaluation, cross-verification against hanshof/sp500_constituents, "
            "and honesty caveats. This is index CONSTITUENT membership, not a tradeable "
            "universe -- it deliberately includes tickers no longer in today's S&P 500."
        ),
        "source_url": _SOURCE_URL,
        "source_name": _SOURCE_NAME,
        "retrieved_at": retrieved_at.isoformat(),
        "as_of": as_of.isoformat(),
        "interval_row_count": len(intervals),
        "distinct_ticker_count": len({iv.ticker for iv in intervals}),
        "constituent_count_as_of": len(constituents),
        "constituents_as_of": constituents,
        "removed_since": args.removed_since,
        "removed_tickers": removed_report,
        "ticker_history": ticker_history_report,
        "db_path": str(args.db_path) if args.db_path is not None else None,
        "universe_membership_records_persisted": persisted_count,
        "data_version_checksum": checksum,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote report to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
