#!/usr/bin/env python3
"""Re-stamps already-ingested corporate actions with ADR-0216's
`available_time` rule, so a catalog built before that rule stops hiding
every historical split/dividend from as-of queries.

**Root cause** (reproduced on the real research-catalogs-v1 price
catalog, 2026-09-26): Tiingo/Alpha Vantage corporate actions used to be
stamped `available_time = ingestion_time`. For a backfill ingested on
2026-09-11, every split and dividend back to 2010 therefore read as
"not known until 2026-09-11", while the raw price bars of the very same
days (stamped at their own session close, `bar_available_time`) stayed
visible. Every backtest before 2026-09-11 saw the post-split raw price
drop without the split: a 2014 AAPL buy-and-hold read the 7:1 split as
a -84% drawdown, dividends were never paid, the SPY TOTAL_RETURN
benchmark was price-only, and `SplitAdjustedInstitutionalHoldingRepository`
applied 0 splits.

**Fix**: for every tiingo/alphavantage row, `available_time` becomes
`min(available_time, COALESCE(effective_time, event_time) + 20h)` --
exactly `data_infra.provider.corporate_action_available_time` applied to
the stored `ingestion_time`. `ingestion_time` and every other column are
left untouched. This is an in-place UPDATE of the `corporate_actions`
DuckDB table, not an appended copy: `add_corporate_action` keys on
`provenance_source_record_id`, and `CorporateActionApplier` is
idempotent on that same key, so a second copy of the same event under a
new id would be applied twice once both became visible.

Makes NO network call. Idempotent: a second `--apply` finds nothing to
change.

Usage (dry run, the default):
    python3 scripts/repair_corporate_action_available_time.py --db-path ./data/price_catalog
Usage (writes the change):
    python3 scripts/repair_corporate_action_available_time.py --db-path ./data/price_catalog --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import END_OF_SESSION_OFFSET  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_SOURCES = ("tiingo", "alphavantage")
_OFFSET_HOURS = int(END_OF_SESSION_OFFSET.total_seconds() // 3600)
_TARGET = f"COALESCE(effective_time, event_time) + INTERVAL {_OFFSET_HOURS} HOUR"
_WHERE = (
    f"provenance_source IN ({', '.join('?' * len(_SOURCES))}) "
    f"AND COALESCE(effective_time, event_time) IS NOT NULL AND available_time > {_TARGET}"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="A price catalog directory (contains catalog.duckdb)")
    parser.add_argument("--apply", action="store_true", help="Actually update the rows (default: dry run)")
    args = parser.parse_args(argv)

    if not args.db_path.is_dir():
        print(f"FATAL: {args.db_path} does not exist or is not a directory", file=sys.stderr)
        return 1

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    try:
        connection = engine.connection
        counts = connection.execute(
            f"SELECT action_type, COUNT(*) FROM corporate_actions WHERE {_WHERE} GROUP BY 1 ORDER BY 1", list(_SOURCES),
        ).fetchall()
        total = sum(n for _, n in counts)
        if total == 0:
            print("No corporate action has available_time later than its event-date close -- nothing to repair.")
            return 0
        print(f"{total} corporate action(s) have available_time later than their event-date close:")
        for action_type, n in counts:
            print(f"  {action_type}: {n}")
        for row in connection.execute(
            f"SELECT security_id, action_type, COALESCE(effective_time, event_time), available_time, details_json "
            f"FROM corporate_actions WHERE {_WHERE} AND action_type IN ('SPLIT', 'REVERSE_SPLIT') ORDER BY 3",
            list(_SOURCES),
        ).fetchall():
            print(f"    {row[0]} {row[1]} effective={row[2]:%Y-%m-%d} available_time={row[3]:%Y-%m-%d} {row[4]}")
        if not args.apply:
            print("\nDry run only -- re-run with --apply to write the change.")
            return 0
        connection.execute(f"UPDATE corporate_actions SET available_time = {_TARGET} WHERE {_WHERE}", list(_SOURCES))
        print(f"\nUpdated available_time on {total} corporate action(s).")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
