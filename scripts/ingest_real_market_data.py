#!/usr/bin/env python3
"""Real market data ingestion CLI (Phase 23, instruction section 6).

This script exists because this development environment's outbound
network is blocked to every market-data provider domain (confirmed this
session: `api.tiingo.com`, `stooq.com` both return a 403 CONNECT
rejection at the egress proxy -- see
`docs/operations/MARKET-DATA-PROVIDER.md`'s Phase 23 section). It is
NEVER executed by this repository's own automated test suite, and it
makes a REAL network call when run -- run it only in an environment with
real internet access, with a real Tiingo API key set in the environment
variable `MARKET_DATA_API_KEY` (never pass a key on the command line or
write one into a file).

Every module this script imports (`TiingoDataProvider`,
`StooqDataProvider`, `FallbackDataProvider`, `IngestionRunner`,
`DuckDBDataRepository`, `DataQualityFramework`) already exists and is
already covered by this repository's own fixture-based test suite
(Phase 20-22) -- this script performs no new data-handling logic itself,
it only wires those exact, unmodified pieces together against a real
network and a real on-disk DuckDB catalog.

Usage:
    export MARKET_DATA_API_KEY=<your real Tiingo API key>
    python3 scripts/ingest_real_market_data.py \\
        --start 2024-01-02 --end 2024-06-28 \\
        --db-path ./data/real_market_data

Every provider call's `end` date is exactly what you pass on the command
line -- this script never reads wall-clock time to decide what "now" is,
so re-running it with the same arguments against a fresh database
directory is expected to be reproducible up to whatever the providers
themselves return differently over time (a real, external fact this
script cannot control, and does not attempt to hide -- see the
manifest's `note` field).

**Phase 24 update**: `--universe` selects a named, versioned
`UniverseDefinition` from `src/data_infra/universe.py`
(`PILOT_UNIVERSE` or `RESEARCH_UNIVERSE`, default `PILOT_UNIVERSE`)
instead of a symbol list hardcoded in this script -- the benchmark
symbol (`SPY`) is always additionally ingested and always tracked
separately from the universe's own tradeable membership (instruction
section 32). `--symbols` remains available as an explicit override for
ad-hoc runs. The script now also populates `SecurityMaster`/
`UniverseMembership` records for the selected universe (previously it
only wrote price bars), and records a content checksum
(`data_infra.versioning.compute_data_version`, unmodified) in the
manifest for reproducibility tracking.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import IngestionRunner  # noqa: E402
from data_infra.providers.fallback import FallbackDataProvider  # noqa: E402
from data_infra.providers.stooq import StooqDataProvider  # noqa: E402
from data_infra.providers.stooq_config import DEFAULT_STOOQ_CONFIG  # noqa: E402
from data_infra.providers.stooq_transport import StooqHttpTransport  # noqa: E402
from data_infra.providers.tiingo import TiingoDataProvider  # noqa: E402
from data_infra.providers.tiingo_config import DEFAULT_TIINGO_CONFIG  # noqa: E402
from data_infra.providers.tiingo_transport import TiingoHttpTransport  # noqa: E402
from data_infra.quality import DataQualityFramework  # noqa: E402
from data_infra.universe import (  # noqa: E402
    BENCHMARK_SYMBOL,
    PILOT_UNIVERSE_V1,
    RESEARCH_UNIVERSE_STAGE1,
    build_security_masters,
    build_universe_memberships,
)
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE1}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="PILOT_UNIVERSE", help="Named universe from src/data_infra/universe.py (default: PILOT_UNIVERSE). SPY is always additionally ingested as the benchmark, tracked separately.")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely (advanced/ad-hoc use)")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date, YYYY-MM-DD -- also used as the ingestion's available_time/as_of reference; never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog + Parquet store (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/ingestion_manifest.json)")
    args = parser.parse_args()

    manifest_path = args.manifest_out or (args.db_path / "ingestion_manifest.json")

    if args.symbols is not None:
        universe = None
        symbols = list(args.symbols)
    else:
        universe = _UNIVERSES[args.universe]
        symbols = list(universe.symbol_ids) + [BENCHMARK_SYMBOL]

    tiingo = TiingoDataProvider(DEFAULT_TIINGO_CONFIG, TiingoHttpTransport(DEFAULT_TIINGO_CONFIG.base_url))
    stooq = StooqDataProvider(DEFAULT_STOOQ_CONFIG, StooqHttpTransport(DEFAULT_STOOQ_CONFIG.base_url))
    provider = FallbackDataProvider(tiingo, stooq)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    try:
        if universe is not None:
            for record in build_security_masters(universe, valid_from=args.start):
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
            all_bars, dataset="phase24_real_ingestion", data_version="real-run",
            known_security_ids=set(symbols), as_of_now=args.end,
        )

        checksum = compute_data_version(
            {
                "symbols": sorted(symbols),
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "per_symbol_bar_counts": {
                    symbol: sum(1 for b in all_bars if b.security_id == symbol) for symbol in sorted(symbols)
                },
            }
        )

        manifest = {
            "note": (
                "This manifest describes a real ingestion run against live "
                "provider APIs. Bar counts and quality findings reflect "
                "whatever the providers actually returned at run time -- "
                "they are NOT reproduced or asserted by this repository's "
                "own test suite, which never makes real network calls."
            ),
            "universe_name": universe.name if universe is not None else None,
            "universe_version": universe.version if universe is not None else None,
            "symbols": list(symbols),
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
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
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"Ingestion status: {result.status.value}")
        print(f"Total bars persisted: {len(all_bars)}")
        print(f"Data quality status: {quality_run.status.value} ({len(quality_run.issues)} issue(s))")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        return 0 if result.status.value == "SUCCESS" else 1
    finally:
        engine.close()


if __name__ == "__main__":
    main()
