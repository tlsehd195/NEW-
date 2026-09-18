#!/usr/bin/env python3
"""Diagnoses what's actually behind a real ingestion run's aggregate
data quality severity counts (e.g. "Data quality status: FAILED (867
issue(s))") by querying `data_quality_flags` directly against a real
`--db-path` catalog -- per-check counts, per-security counts, and a
sample of the real issue messages for the worst-offending check.

**Why this script exists**: `scripts/ingest_real_market_data.py` only
ever printed the aggregate severity breakdown to stdout (e.g. `{'ERROR':
866, ...}`) -- with hundreds of ERROR-severity issues on a single real
run, that number alone gives no way to tell a narrow, already-understood
problem from a broad, unexamined one, and this project's own CI
environment cannot download the GitHub Actions artifact holding the
real catalog to look closer (its egress proxy blocks Azure Blob
Storage, same as every other non-allowlisted domain). Run this locally
(or in Colab) against a downloaded-and-unzipped `market-data-catalog`
artifact instead.

Usage:
    python3 scripts/diagnose_data_quality_flags.py --db-path ./market-data-catalog

Read-only (StorageEngine(read_only=True)) -- never mutates the real
catalog.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_SAMPLE_SIZE = 10


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="A market-data catalog directory (e.g. the unzipped market-data-catalog artifact)")
    parser.add_argument("--sample-size", type=int, default=_SAMPLE_SIZE, help=f"How many real issue messages to print per check (default: {_SAMPLE_SIZE})")
    args = parser.parse_args(argv)

    if not args.db_path.is_dir():
        print(f"FATAL: {args.db_path} does not exist or is not a directory", file=sys.stderr)
        return 1

    engine = StorageEngine(StorageConfig(root_dir=args.db_path), read_only=True)
    conn = engine.connection

    total = conn.execute("SELECT COUNT(*) FROM data_quality_flags").fetchone()[0]
    print(f"Total data_quality_flags rows in this catalog: {total}\n")

    print("=== By severity ===")
    for severity, count in conn.execute(
        "SELECT severity, COUNT(*) AS n FROM data_quality_flags GROUP BY severity ORDER BY n DESC"
    ).fetchall():
        print(f"  {severity}: {count}")

    print("\n=== By check_name (all severities) ===")
    check_rows = conn.execute(
        "SELECT check_name, severity, COUNT(*) AS n FROM data_quality_flags "
        "GROUP BY check_name, severity ORDER BY n DESC"
    ).fetchall()
    for check_name, severity, count in check_rows:
        print(f"  {check_name} [{severity}]: {count}")

    print("\n=== Securities with the most ERROR-severity flags (top 20) ===")
    for security_id, count in conn.execute(
        "SELECT security_id, COUNT(*) AS n FROM data_quality_flags WHERE severity = 'ERROR' "
        "GROUP BY security_id ORDER BY n DESC LIMIT 20"
    ).fetchall():
        print(f"  {security_id}: {count}")

    if check_rows:
        worst_check = check_rows[0][0]
        print(f"\n=== Sample real messages for the worst-offending check ('{worst_check}') ===")
        for security_id, timestamp, message in conn.execute(
            "SELECT security_id, timestamp, message FROM data_quality_flags WHERE check_name = ? "
            "ORDER BY timestamp LIMIT ?",
            [worst_check, args.sample_size],
        ).fetchall():
            print(f"  [{security_id} @ {timestamp}] {message}")

    engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
