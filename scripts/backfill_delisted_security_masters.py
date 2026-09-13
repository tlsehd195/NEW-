#!/usr/bin/env python3
"""Backfills `SecurityMaster` records, derived from real persisted
price bars, for securities that have real bars in an existing DuckDB
catalog but no `SecurityMaster` of their own -- the exact gap
`scripts/import_external_market_data.py --symbols` (used to ingest
ADR-0126/ADR-0128's 59 recovered delisted tickers) leaves behind. See
`data_infra.security_master_backfill` for the full rationale (why
`valid_from`/`valid_to` come from the bars themselves, never from a
different dataset's dates, and why `exchange`/`company_id` use the
same honest sentinels `data_infra.universe.build_security_masters`
already established).

Makes NO network call -- reads and writes only the local DuckDB
catalog at `--db-path` -- so, like `scripts/report_survivorship_price_
coverage.py`, this script IS exercised by the automated test suite.

Usage:
    python3 scripts/backfill_delisted_security_masters.py \\
        --db-path ./data/wiki_prices_delisted_db \\
        --symbols DELL ATVI MRO TWTR VIAC WBA ... \\
        --as-of 2026-09-12
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.security_master_backfill import build_delisted_security_masters_from_bars  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="Existing DuckDB catalog containing the real price bars to backfill")
    parser.add_argument("--symbols", nargs="+", required=True, help="security_id(s) to backfill (must already have real bars in --db-path)")
    parser.add_argument("--price-history-start", type=str, default="1900-01-01", help="Earliest date to look for bars (default: 1900-01-01)")
    parser.add_argument("--as-of", required=True, type=str, help="YYYY-MM-DD; the as_of_time/window-end for the bar lookup")
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"FATAL: {args.db_path} does not exist", file=sys.stderr)
        return 1

    as_of_time = datetime.strptime(args.as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    price_history_start = datetime.strptime(args.price_history_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    try:
        repository = DuckDBDataRepository(engine)
        records = build_delisted_security_masters_from_bars(
            repository, args.symbols, price_history_start=price_history_start, as_of_time=as_of_time,
        )
        for record in records:
            repository.add_security(record)
    finally:
        engine.close()

    if not records:
        print("FATAL: none of the given symbols have any real bars in this catalog", file=sys.stderr)
        return 1

    backfilled = sorted(r.security_id for r in records)
    skipped = sorted(s for s in args.symbols if s not in backfilled)

    print(f"Backfilled SecurityMaster for {len(records)} security(ies): {backfilled}")
    for record in records:
        print(f"  {record.security_id}: DELISTED, valid_from={record.valid_from.date()}, valid_to={record.valid_to.date()}")
    if skipped:
        print(f"Skipped (no real bars found in this catalog): {skipped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
