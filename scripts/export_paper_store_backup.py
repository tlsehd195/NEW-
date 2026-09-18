#!/usr/bin/env python3
"""Exports the Paper Trading LEDGER tables in a real --paper-store
DuckDB catalog to plain JSON files -- a durable, git-committed backup
outside GitHub Actions artifacts' 90-day retention window (external
review, "Paper Trading 100-point evaluation" report: the paper trading
ledger's ONLY persistence today is a GitHub Actions artifact, so 90+
days of scheduled-run failures in a row could lose the entire
order/fill/trade history with nothing left to restore from).

ADR-0156 (external review, first real `workflow_dispatch` exercise of
this script against a production-sized catalog): the original design
(ADR-0150) introspected `information_schema.tables` and dumped EVERY
table unconditionally, on the theory that a future new table would
then be covered automatically with no script update needed. In
practice this also swept in several large, per-cycle-per-security
Learning Engine/telemetry tables that were never this backup's actual
target (`regime_observations`/`regime_composites`/`predictions`/
`decision_outputs`/`position_sizing_results`/`risk_assessments` --
`regime_observations` alone serialized to 2.28 GB against a real
catalog with ~61,600 decision cycles), which made `git push` fail
atomically on GitHub's 100 MB per-file limit -- and because a rejected
push is all-or-nothing, the tiny, actually-critical ledger tables
(`paper_orders`/`paper_fills`/`decisions`/`trades`, each a few thousand
rows at most) silently never got backed up either, every single day,
until this was caught by manually re-running the workflow. Fixed by
scoping to an explicit `_LEDGER_TABLES` allowlist matching what
ADR-0150's own Context section actually named ("order/fill/trade/
decision history") -- a Learning Engine artifact table lost to a real
90-day artifact-expiry incident is reconstructable by re-running
ingestion/Learning Cycle against the surviving ledger; the ledger
itself is not reconstructable from anything else, which is the whole
reason this backup exists. A `_MAX_TABLE_JSON_BYTES` safety cap is kept
as defense in depth: even a ledger table unexpectedly growing past a
safe size in the future is skipped (loudly, to stderr) rather than
silently blocking every other table's push again.

Read-only against --paper-store (StorageEngine(read_only=True) -- never
mutates the real catalog).

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

# ADR-0156: the Paper Trading ledger, matching ADR-0150's own stated
# scope -- orders/fills/status history, the Trade Journal (decisions
# recorded only for a real resulting order, trades, their post-trade
# analysis/counterfactual/correction audit trail), and performance
# reports. Deliberately NOT the Learning Engine/telemetry tables
# (predictions, decision_outputs, position_sizing_results,
# risk_assessments, regime_observations, regime_composites,
# experience_records, candidate_models, ...) -- those are real, but
# reconstructable by re-running ingestion/Learning Cycle, and were the
# actual cause of this backup silently failing in production (see
# module docstring, ADR-0156).
_LEDGER_TABLES = (
    "corrections",
    "counterfactuals",
    "decisions",
    "order_status_events",
    "paper_fills",
    "paper_orders",
    "paper_performance_reports",
    "post_trade_analyses",
    "trades",
)

# GitHub's own hard per-file push limit is 100 MB -- this stays well
# under it so a table that somehow grows large still fails loudly (one
# skipped file, a stderr warning) instead of silently blocking every
# other table's push atomically, the exact failure mode ADR-0156 fixes.
_MAX_TABLE_JSON_BYTES = 50 * 1024 * 1024


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")


def export_paper_store_backup(paper_store: Path, out_dir: Path) -> dict[str, int]:
    """Returns {table_name: row_count} for every LEDGER table (see
    `_LEDGER_TABLES`) actually present in this --paper-store's DuckDB
    file. A ledger table absent from this particular catalog (e.g. an
    older store predating a newer table) is simply skipped, not an
    error. A table whose JSON serialization exceeds
    `_MAX_TABLE_JSON_BYTES` is skipped with a stderr warning rather than
    written -- its row count is NOT included in the returned dict, so a
    caller can tell it was skipped rather than genuinely empty. Empty
    dict if the catalog has no ledger tables yet (a freshly-initialized,
    never-run store)."""
    engine = StorageEngine(StorageConfig(root_dir=paper_store), read_only=True)
    try:
        conn = engine.connection
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        tables = [t for t in _LEDGER_TABLES if t in existing_tables]
        out_dir.mkdir(parents=True, exist_ok=True)
        row_counts: dict[str, int] = {}
        for table in tables:
            cursor = conn.execute(f"SELECT * FROM {table}")
            columns = [d[0] for d in cursor.description]
            records = [dict(zip(columns, row)) for row in cursor.fetchall()]
            encoded = json.dumps(records, indent=2, default=_json_default, sort_keys=True)
            if len(encoded.encode("utf-8")) > _MAX_TABLE_JSON_BYTES:
                print(
                    f"WARNING: {table}.json exceeds {_MAX_TABLE_JSON_BYTES} bytes -- "
                    f"skipping this table's backup this run (real row count: {len(records)})",
                    file=sys.stderr,
                )
                continue
            (out_dir / f"{table}.json").write_text(encoded)
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
