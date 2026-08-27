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
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

# Phase 22's fixed 16-symbol US long-term Paper Trading universe
# (docs/operations/MARKET-DATA-PROVIDER.md). This script does not accept
# an arbitrary/unbounded symbol list by default -- expanding the
# universe is explicitly out of scope for this phase (instruction
# section 7).
DEFAULT_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
    "JPM", "V", "MA", "COST", "WMT", "JNJ", "XOM", "SPY",
)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_UNIVERSE), help="Symbols to ingest (default: the Phase 22/23 16-symbol universe)")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date, YYYY-MM-DD -- also used as the ingestion's available_time/as_of reference; never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog + Parquet store (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/ingestion_manifest.json)")
    args = parser.parse_args()

    manifest_path = args.manifest_out or (args.db_path / "ingestion_manifest.json")

    tiingo = TiingoDataProvider(DEFAULT_TIINGO_CONFIG, TiingoHttpTransport(DEFAULT_TIINGO_CONFIG.base_url))
    stooq = StooqDataProvider(DEFAULT_STOOQ_CONFIG, StooqHttpTransport(DEFAULT_STOOQ_CONFIG.base_url))
    provider = FallbackDataProvider(tiingo, stooq)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)

    try:
        runner = IngestionRunner(provider, repository)
        result = runner.run(args.symbols, args.start, args.end)

        quality = DataQualityFramework()
        all_bars = []
        for symbol in args.symbols:
            all_bars.extend(repository.get_bars(symbol, args.start, args.end, as_of_time=args.end))
        quality_run = quality.run(
            all_bars, dataset="phase23_real_ingestion", data_version="real-run",
            known_security_ids=set(args.symbols), as_of_now=args.end,
        )

        manifest = {
            "note": (
                "This manifest describes a real ingestion run against live "
                "provider APIs. Bar counts and quality findings reflect "
                "whatever the providers actually returned at run time -- "
                "they are NOT reproduced or asserted by this repository's "
                "own test suite, which never makes real network calls."
            ),
            "symbols": list(args.symbols),
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
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"Ingestion status: {result.status.value}")
        print(f"Total bars persisted: {len(all_bars)}")
        print(f"Data quality status: {quality_run.status.value} ({len(quality_run.issues)} issue(s))")
        print(f"Manifest written to: {manifest_path}")
        return 0 if result.status.value == "SUCCESS" else 1
    finally:
        engine.close()


if __name__ == "__main__":
    main()
