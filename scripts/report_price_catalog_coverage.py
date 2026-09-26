#!/usr/bin/env python3
"""Per-symbol coverage of a price catalog (ADR-0213): bar count and
earliest/latest bar date for every symbol in `--universe` plus the
benchmark, printed as a table.

Exits 1 when any symbol has zero bars, so
`ingest_research_price_catalog.yml` never publishes a catalog missing a
whole symbol. A symbol whose earliest bar is well after `--start` is
listed separately but is NOT fatal: that is expected for a company that
listed later (e.g. META), and this script has no verified listing date
to tell that apart from a truncated history -- a human reads the list.

Makes no network call.

Usage:
    python3 scripts/report_price_catalog_coverage.py \\
        --db-path data/research_price_catalog \\
        --universe RESEARCH_UNIVERSE_STAGE5 --start 2000-01-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.universe import (  # noqa: E402
    BENCHMARK_SYMBOL,
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE4,
    RESEARCH_UNIVERSE_STAGE5,
)
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_UNIVERSES = {
    "PILOT_UNIVERSE": PILOT_UNIVERSE_V1,
    "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4,
    "RESEARCH_UNIVERSE_STAGE5": RESEARCH_UNIVERSE_STAGE5,
}

# A first bar more than this far after --start is listed for review.
_LATE_START_TOLERANCE = timedelta(days=30)


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--universe", required=True, choices=sorted(_UNIVERSES))
    parser.add_argument("--start", required=True, type=_parse_date)
    args = parser.parse_args()

    symbols = sorted(_UNIVERSES[args.universe].symbol_ids) + [BENCHMARK_SYMBOL]
    far_past = datetime(1900, 1, 1, tzinfo=timezone.utc)
    far_future = datetime(2200, 1, 1, tzinfo=timezone.utc)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    try:
        repository = DuckDBDataRepository(engine)
        rows = []
        for symbol in symbols:
            bars = repository.get_bars(symbol, far_past, far_future, far_future, include_quality_rejected=True)
            if bars:
                timestamps = [b.timestamp for b in bars]
                rows.append((symbol, len(bars), min(timestamps), max(timestamps)))
            else:
                rows.append((symbol, 0, None, None))
    finally:
        engine.close()

    print(f"{'symbol':<8} {'bars':>6}  {'first':<10}  {'last':<10}")
    for symbol, count, first, last in rows:
        print(
            f"{symbol:<8} {count:>6}  {first.date().isoformat() if first else '-':<10}  "
            f"{last.date().isoformat() if last else '-':<10}"
        )

    missing = [r[0] for r in rows if r[1] == 0]
    late = [(r[0], r[2].date().isoformat()) for r in rows if r[2] is not None and r[2] - args.start > _LATE_START_TOLERANCE]
    print(f"\nSymbols: {len(rows)}; with bars: {len(rows) - len(missing)}; zero bars: {len(missing)}")
    print(f"First bar more than {_LATE_START_TOLERANCE.days} days after {args.start.date()} ({len(late)}): {late}")
    if missing:
        print(f"FATAL: zero bars for {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
