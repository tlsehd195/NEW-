#!/usr/bin/env python3
"""Exports every table in a real --paper-store DuckDB catalog to plain
JSON files -- a durable, git-committed backup outside GitHub Actions
artifacts' 90-day retention window (external review, "Paper Trading
100-point evaluation" report: the paper trading ledger's ONLY
persistence today is a GitHub Actions artifact, so 90+ days of
scheduled-run failures in a row could lose the entire order/fill/trade
history with nothing left to restore from).

Read-only against --paper-store (StorageEngine(read_only=True) -- never
mutates the real catalog); introspects the DuckDB catalog's own table
list rather than hardcoding repository classes, so a future new table
is backed up automatically without this script needing an update.

Each run OVERWRITES the previous snapshot at --out-dir (never
accumulates one folder per day) -- every table dump is the FULL current
table, not an incremental diff, so the latest commit is always a
complete, standalone restore point on its own.

Usage:
    python3 scripts/export_paper_store_backup.py \\
        --paper-store ./data/paper_trading_store \\
        --out-dir ./data/paper_trading_backup
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")


def export_paper_store_backup(paper_store: Path, out_dir: Path) -> dict[str, int]:
    """Returns {table_name: row_count} for every table actually present
    in this --paper-store's DuckDB file. Empty dict if the catalog has
    no tables yet (a freshly-initialized, never-run store)."""
    engine = StorageEngine(StorageConfig(root_dir=paper_store), read_only=True)
    try:
        conn = engine.connection
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        ]
        out_dir.mkdir(parents=True, exist_ok=True)
        row_counts: dict[str, int] = {}
        for table in tables:
            cursor = conn.execute(f"SELECT * FROM {table}")
            columns = [d[0] for d in cursor.description]
            records = [dict(zip(columns, row)) for row in cursor.fetchall()]
            (out_dir / f"{table}.json").write_text(
                json.dumps(records, indent=2, default=_json_default, sort_keys=True)
            )
            row_counts[table] = len(records)
        return row_counts
    finally:
        engine.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paper-store", required=True, type=Path, help="A real --paper-store directory to back up")
    parser.add_argument("--out-dir", required=True, type=Path, help="Where the JSON snapshot is written (overwritten each run)")
    args = parser.parse_args(argv)

    if not args.paper_store.is_dir():
        print(f"FATAL: {args.paper_store} does not exist or is not a directory", file=sys.stderr)
        return 1

    row_counts = export_paper_store_backup(args.paper_store, args.out_dir)
    if not row_counts:
        print(f"No tables found in {args.paper_store} -- nothing to back up (freshly-initialized store?)")
        return 0

    total_rows = sum(row_counts.values())
    print(f"Exported {len(row_counts)} table(s), {total_rows} row(s) total, to {args.out_dir}")
    for table, count in sorted(row_counts.items()):
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
