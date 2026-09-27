"""Helpers for extend_research_price_catalog.yml (ADR-0224).

    missing  -- keep the symbols in --symbols-file that have no bar in
                --db-path between --start and --end; write them to --out.
    coverage -- print how many S&P 500 members had price data on each
                Jan 1 of [--start, --end] (after --renames-csv), the same
                numbers run_long_horizon_validation.py --sp500-history-csv
                reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_infra.providers.sp500_index_constituent_history import (  # noqa: E402
    apply_ticker_renames,
    parse_ticker_intervals,
    parse_ticker_renames,
    point_in_time_members_with_prices,
)
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402


def _date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    missing = sub.add_parser("missing")
    missing.add_argument("--symbols-file", type=Path, required=True)
    missing.add_argument("--out", type=Path, required=True)
    coverage = sub.add_parser("coverage")
    coverage.add_argument("--sp500-intervals-csv", type=Path, required=True)
    coverage.add_argument("--renames-csv", type=Path, required=True)
    for p in (missing, coverage):
        p.add_argument("--db-path", type=Path, required=True)
        p.add_argument("--start", type=_date, required=True)
        p.add_argument("--end", type=_date, required=True)
    args = parser.parse_args(argv)

    repository = DuckDBDataRepository(StorageEngine(StorageConfig(root_dir=args.db_path)))
    if args.command == "missing":
        symbols = [s.strip() for s in args.symbols_file.read_text().splitlines() if s.strip()]
        todo = [s for s in symbols if not repository.get_bars(s, args.start, args.end, as_of_time=args.end)]
        args.out.write_text("".join(f"{s}\n" for s in todo))
        print(f"{len(symbols)} listed symbols, {len(symbols) - len(todo)} already in the catalog, {len(todo)} to fetch.")
        return 0

    intervals = apply_ticker_renames(
        parse_ticker_intervals(args.sp500_intervals_csv), parse_ticker_renames(args.renames_csv)
    )
    _, report = point_in_time_members_with_prices(intervals, repository, start=args.start, end=args.end)
    print(json.dumps({k: v for k, v in report.items() if k != "members_without_price_data"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
