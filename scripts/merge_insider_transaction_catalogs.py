#!/usr/bin/env python3
"""Merges multiple shard DuckDB catalogs (each produced by a parallel
`ingest_insider_transactions.py` matrix job against its own ISOLATED
`--db-path`, see `scripts/select_universe_shard.py`'s own module
docstring for why per-job isolation is required) into one combined
catalog.

`insider_transactions` is a native DuckDB table (unlike `price_bars`,
which is Parquet-file-based and can be combined by simply copying
files into one directory) -- rows from N shard catalogs cannot be
merged by a filesystem operation. This uses DuckDB's own `ATTACH` to
open each shard catalog read-only alongside the target, then
`INSERT ... SELECT ... ON CONFLICT (provenance_source_record_id) DO
NOTHING` to copy its rows in -- the identical idempotent-insert
natural key `DuckDBInsiderRepository.add_insider_transaction` already
uses for a single writer, so running this twice (or feeding it
overlapping shards) never creates a duplicate row.

Makes NO network call -- reads/writes only local DuckDB catalog files.

Usage:
    python3 scripts/merge_insider_transaction_catalogs.py \\
        --target-db-path ./data/insider_combined \\
        --shard-db-path ./data/insider_shard_0 \\
        --shard-db-path ./data/insider_shard_1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-db-path", required=True, type=Path, help="Directory for the combined DuckDB catalog (created if it does not exist)")
    parser.add_argument("--shard-db-path", action="append", required=True, type=Path, dest="shard_db_paths", metavar="PATH", help="A shard's --db-path directory from ingest_insider_transactions.py -- repeat for each shard")
    args = parser.parse_args(argv)

    engine = StorageEngine(StorageConfig(root_dir=args.target_db_path))
    try:
        before = engine.connection.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0]
        for i, shard_path in enumerate(args.shard_db_paths):
            shard_db_file = shard_path / "catalog.duckdb"
            if not shard_db_file.is_file():
                print(f"  shard {shard_path}: no catalog.duckdb found, skipping", flush=True)
                continue
            alias = f"shard_{i}"
            engine.connection.execute(f"ATTACH '{shard_db_file}' AS {alias} (READ_ONLY)")
            try:
                shard_count = engine.connection.execute(f"SELECT COUNT(*) FROM {alias}.insider_transactions").fetchone()[0]
                engine.connection.execute(
                    f"INSERT INTO insider_transactions SELECT * FROM {alias}.insider_transactions "
                    "ON CONFLICT (provenance_source_record_id) DO NOTHING"
                )
                print(f"  shard {shard_path}: {shard_count} row(s) in shard, merged", flush=True)
            finally:
                engine.connection.execute(f"DETACH {alias}")

        after = engine.connection.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0]
        print(f"Combined catalog: {before} row(s) before merge, {after} row(s) after ({after - before} new)")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
