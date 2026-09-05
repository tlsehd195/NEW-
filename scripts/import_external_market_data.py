#!/usr/bin/env python3
"""External market data import CLI (Phase 31, instruction section 21).

Unlike `scripts/ingest_real_market_data.py` (which requires live
network access this sandboxed session has never had), this script
reads pre-downloaded, already-normalized CSV files from local disk --
it makes NO network call, ever. This is the external acquisition
workflow instruction section 21 asks for:

    external environment (user's own network access)
        -> provider/dataset acquisition (Tiingo, Nasdaq Data Link, CRSP, ...)
        -> user's own preprocessing into the CSV schema documented in
           data_infra.providers.file_import
        -> one CSV file per security_id, placed in a local directory
        -> THIS SCRIPT
        -> the exact same IngestionRunner / DataQualityFramework /
           DuckDBDataRepository pipeline `ingest_real_market_data.py`
           uses (Phase 1/4/20, unmodified)

Because it never touches the network, this script IS safe to exercise
directly in the automated test suite (see
`tests/data_infra/test_import_external_market_data_cli.py`) -- unlike
`ingest_real_market_data.py`, which is deliberately never imported or
executed by the suite.

No API key is read or required by this script. `--source-name` must
honestly describe where the CSV files actually came from (never a
guess, never a default) -- it becomes `Provenance.source` on every
persisted bar and is what a future `run_long_horizon_validation.py
--data-status REAL` run's provenance cross-check keys off of. If the
CSV files were produced from data the user does not have a legitimate
license/right to redistribute or use, that is the user's
responsibility to verify -- this script performs no licensing check
(instruction section 4H notes licensing as a per-provider concern to
document, not something this script can verify).

Usage:
    python3 scripts/import_external_market_data.py \\
        --source-name nasdaq_data_link_sharadar \\
        --data-dir /path/to/preprocessed/csv/files \\
        --universe PILOT_UNIVERSE \\
        --start 2010-01-01 --end 2024-12-31 \\
        --db-path ./data/external_import
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.enums import SecurityStatus  # noqa: E402
from data_infra.provider import IngestionRunner  # noqa: E402
from data_infra.providers.file_import import FileImportConfig, LocalFileDataProvider  # noqa: E402
from data_infra.quality import DataQualityFramework  # noqa: E402
from data_infra.universe import (  # noqa: E402
    BENCHMARK_SYMBOL,
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE4,
    build_security_masters,
    build_universe_memberships,
)
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-name", required=True,
        help="Honest name of the external source these CSV files actually came from "
        "(e.g. nasdaq_data_link_sharadar, crsp, tiingo_manual_export). Becomes Provenance.source.",
    )
    parser.add_argument("--data-dir", required=True, type=Path, help="Directory containing one <security_id>.csv per symbol")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE", help="Named universe from src/data_infra/universe.py")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date, YYYY-MM-DD -- also used as the ingestion's available_time/as_of reference")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog + Parquet store (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/import_manifest.json)")
    args = parser.parse_args(argv)

    manifest_path = args.manifest_out or (args.db_path / "import_manifest.json")

    if args.symbols is not None:
        universe = None
        symbols = list(args.symbols)
    else:
        universe = _UNIVERSES[args.universe]
        symbols = list(universe.symbol_ids) + [BENCHMARK_SYMBOL]

    provider = LocalFileDataProvider(FileImportConfig(source_name=args.source_name, data_dir=args.data_dir))

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    try:
        security_masters = []
        if universe is not None:
            security_masters = build_security_masters(universe, valid_from=args.start)
            for record in security_masters:
                repository.add_security(record)
            for record in build_universe_memberships(universe, valid_from=args.start):
                repository.add_universe_membership(record)

        runner = IngestionRunner(provider, repository)
        result = runner.run(symbols, args.start, args.end)

        quality = DataQualityFramework()
        all_bars = []
        for symbol in symbols:
            all_bars.extend(repository.get_bars(symbol, args.start, args.end, as_of_time=args.end))
        quality_run = quality.run(
            all_bars, dataset="phase31_external_import", data_version="external-import-run",
            known_security_ids=set(symbols), as_of_now=args.end,
        )

        checksum = compute_data_version(
            {
                "source_name": args.source_name,
                "symbols": sorted(symbols),
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "per_symbol_bar_counts": {
                    symbol: sum(1 for b in all_bars if b.security_id == symbol) for symbol in sorted(symbols)
                },
            }
        )

        actual_data_start = min((b.timestamp for b in all_bars), default=None)
        actual_data_end = max((b.timestamp for b in all_bars), default=None)
        delisted_count = sum(1 for s in security_masters if s.status == SecurityStatus.DELISTED)
        active_count = len(security_masters) - delisted_count if security_masters else None
        providers_used = sorted({b.provenance.source for b in all_bars})
        bar_counts_by_symbol = {symbol: 0 for symbol in symbols}
        for b in all_bars:
            bar_counts_by_symbol[b.security_id] = bar_counts_by_symbol.get(b.security_id, 0) + 1
        missing_symbols = sorted(symbol for symbol, count in bar_counts_by_symbol.items() if count == 0)
        historical_universe_membership_available = (
            any(s.listed_from is not None or s.listed_to is not None for s in universe.symbols)
            if universe is not None
            else None
        )

        manifest = {
            "note": (
                "This manifest describes an EXTERNAL IMPORT run -- the CSV files under "
                "--data-dir were NOT fetched over the network by this script. Whether "
                "their content is genuinely real market data depends entirely on how the "
                "user acquired and prepared them; this script only validates their "
                "SHAPE (schema, OHLC/volume sanity, point-in-time consistency), never "
                "their truthfulness."
            ),
            "data_status": "REAL",
            "source_name": args.source_name,
            "data_dir": str(args.data_dir),
            "universe_name": universe.name if universe is not None else None,
            "universe_version": universe.version if universe is not None else None,
            "symbols": list(symbols),
            "symbol_count": len(symbols),
            "active_count": active_count,
            "delisted_count": delisted_count,
            "missing_symbols": missing_symbols,
            "providers_used": providers_used,
            "historical_universe_membership_available": historical_universe_membership_available,
            "survivorship_mitigation_applied": historical_universe_membership_available,
            "requested_start": args.start.isoformat(),
            "requested_end": args.end.isoformat(),
            "actual_data_start": actual_data_start.isoformat() if actual_data_start is not None else None,
            "actual_data_end": actual_data_end.isoformat() if actual_data_end is not None else None,
            "db_path": str(args.db_path),
            "ingestion_run_id": result.run_id,
            "ingestion_status": result.status.value,
            "per_symbol_results": [
                {"security_id": r.security_id, "status": r.status.value, "bars_ingested": r.bars_ingested, "error": r.error}
                for r in result.results
            ],
            "total_bars_persisted": len(all_bars),
            "data_quality_status": quality_run.status.value,
            "data_quality_issue_count": len(quality_run.issues),
            "data_quality_issues": [
                {"check": i.check, "severity": i.severity.value, "security_id": i.security_id, "message": i.message}
                for i in quality_run.issues
            ],
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"Ingestion status: {result.status.value}")
        print(f"Total bars persisted: {len(all_bars)}")
        print(f"ACTUAL_DATA_START: {manifest['actual_data_start']}")
        print(f"ACTUAL_DATA_END: {manifest['actual_data_end']}")
        print(f"Missing symbols (zero bars): {missing_symbols}")
        print(f"Data quality status: {quality_run.status.value} ({len(quality_run.issues)} issue(s))")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        return 0 if result.status.value == "SUCCESS" else 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
