#!/usr/bin/env python3
"""One-time (or on-demand) retroactive data quality rescan (Session 37,
ADR-0144 -- follow-up to ADR-0143).

ADR-0143 made `DuckDBDataRepository.get_bars()` exclude a CRITICAL-flagged
bar by default going forward, but it explicitly does NOT retroactively
re-examine bars a catalog already had before that change: the daily
`ingest_real_market_data.py` only ever quality-checks the INCREMENTAL
window it just fetched (`compute_incremental_ingestion_start.py`), so a
bar ingested by an earlier run -- before this gate existed, or from a
run whose findings were simply never persisted -- is never re-examined
by any later, normal ingestion run. Real example: "Paper Trading Daily
Cycle #7" (2026-09-11, PARTIAL_SUCCESS, 1628 data quality issues) --
whatever severity those issues actually were, they are sitting in the
catalog completely unflagged, and no future incremental run will ever
look at that date range again.

This script closes that specific gap: it re-runs
`DataQualityFramework` over EVERY bar currently in `--db-path`'s catalog
(`DuckDBDataRepository.all_bars()`, unfiltered -- bypasses the very
exclusion this script exists to apply) and persists the result via
`record_quality_issues()`, exactly like the two real-data ingestion
scripts do for their own incremental window. Any bar that gets a
CRITICAL finding here is excluded from `get_bars()`'s default result
from this point on, for every consumer of this same catalog.

Deliberately NOT scheduled daily/weekly: re-scanning the ENTIRE history
every day would be wasteful (duplicate/gap-style checks over a
growing, mostly-already-checked series) and noisy (the same historical
WARNING would be "re-found" every single day). This is a `workflow_dispatch`
-only operation (see `.github/workflows/data_quality_rescan.yml`) --
run it once now to catch up pre-ADR-0143 data, and again by hand any
time there is a specific reason to suspect the catalog needs re-checking.

Scope: unlike `ingest_real_market_data.py`, this script does NOT pass
`corporate_actions` to `DataQualityFramework.run()` (no `split_consistency`/
`dividend_consistency` checks here) -- collecting every corporate action
for every security already in the catalog is a bigger, separate
operation this focused backfill tool does not need in order to catch
the corruption-class findings (`non_finite_value`, `ohlc_consistency`,
`duplicate_records`, ...) ADR-0143's exclusion actually acts on.
`known_security_ids` is also not passed (so `symbol_mismatch` is
skipped) -- there is no independent "expected universe" to check
against here, only "what this catalog already has."

Makes NO network call -- reads only the already-persisted local
DuckDB/Parquet catalog at --db-path.

Usage:
    python3 scripts/rescan_data_quality.py \\
        --db-path ./data/real_market_data \\
        --out ./data/data_quality_rescan_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.enums import DataQualityRunStatus, DataQualitySeverity  # noqa: E402
from data_infra.quality import DataQualityFramework  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="Existing DuckDB/Parquet catalog to rescan (e.g. the restored market-data-catalog)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the JSON rescan report")
    args = parser.parse_args(argv)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    try:
        all_bars = list(repository.all_bars())
        if not all_bars:
            print("No bars found in this catalog -- nothing to rescan.")
            report = {
                "note": "Catalog was empty -- no bars to rescan.",
                "db_path": str(args.db_path),
                "bars_scanned": 0,
                "data_quality_status": None,
                "data_quality_severity_counts": {},
                "data_quality_flags_persisted": 0,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(report, indent=2))
            return 0

        as_of_now = max(b.available_time for b in all_bars)
        security_ids = sorted({b.security_id for b in all_bars})

        quality = DataQualityFramework()
        quality_run = quality.run(
            all_bars, dataset="phase37_retroactive_rescan", data_version="rescan-run",
            as_of_now=as_of_now,
        )
        quality_rows_written = repository.record_quality_issues(quality_run)
        severity_counts = {sev.value: 0 for sev in DataQualitySeverity}
        for issue in quality_run.issues:
            severity_counts[issue.severity.value] += 1

        report = {
            "note": (
                "Retroactive rescan of every bar already in this catalog -- see this "
                "script's own module docstring (ADR-0144) for why this exists and what "
                "it deliberately does not check (no corporate-action consistency checks, "
                "no symbol_mismatch)."
            ),
            "db_path": str(args.db_path),
            "security_ids_scanned": security_ids,
            "bars_scanned": len(all_bars),
            "as_of_now": as_of_now.isoformat(),
            "data_quality_status": quality_run.status.value,
            "data_quality_issue_count": len(quality_run.issues),
            "data_quality_severity_counts": severity_counts,
            "data_quality_flags_persisted": quality_rows_written,
            "data_quality_issues": [
                {
                    "check": i.check, "severity": i.severity.value, "security_id": i.security_id,
                    "timestamp": i.timestamp.isoformat() if i.timestamp is not None else None,
                    "message": i.message,
                }
                for i in quality_run.issues
            ],
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))

        print(f"Bars scanned: {len(all_bars)} across {len(security_ids)} security id(s)")
        print(f"Data quality status: {quality_run.status.value} ({len(quality_run.issues)} issue(s))")
        print(f"Data quality severity breakdown: {severity_counts}")
        print(f"Data quality flags newly persisted to catalog: {quality_rows_written}")
        print(f"Report written to: {args.out}")
        if quality_run.status == DataQualityRunStatus.CRITICAL_FAILURE:
            print(
                f"FATAL: {severity_counts['CRITICAL']} CRITICAL issue(s) found in this catalog's "
                "existing history. The affected bar(s) are now excluded from "
                "DuckDBDataRepository.get_bars()'s default result (Raw copies retained, not deleted).",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
