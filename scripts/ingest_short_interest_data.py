#!/usr/bin/env python3
"""Short interest data import CLI (Session 36 continued -- found via a
GitHub/web search for borrowable strategies, ADR-0099).

Mirrors `import_external_market_data.py`'s own shape and reasoning
exactly, applied to FINRA short-interest reports instead of OHLCV bars:
this script reads pre-downloaded, already-normalized CSV files from
local disk -- it makes NO network call, ever (see `data_infra.providers.
short_interest_file_import`'s module docstring for why this project does
not parse FINRA's own real bulk-file format directly: this sandboxed
session cannot reach `finra.org` to observe it).

    external environment (user's own network access, reaches finra.org)
        -> FINRA Equity Short Interest file/API download
        -> user's own preprocessing into the CSV schema documented in
           data_infra.providers.short_interest_file_import
        -> one CSV file per security_id, placed in a local directory
        -> THIS SCRIPT
        -> DuckDBShortInterestRepository
        -> short_interest_score (strategy_research.factor_scores)

Because it never touches the network, this script IS safe to exercise
directly in the automated test suite (mirrors
`test_import_external_market_data_cli.py`'s own precedent) -- unlike
`ingest_insider_transactions.py`/`ingest_fundamentals_data.py`, which
make real network calls and are never imported or executed by the
suite.

No API key is read or required. `--source-name` must honestly describe
where the CSV files actually came from -- same `Provenance.source`
discipline `import_external_market_data.py`'s own docstring already
establishes.

Usage:
    python3 scripts/ingest_short_interest_data.py \\
        --source-name finra_manual_export \\
        --data-dir /path/to/preprocessed/csv/files \\
        --universe RESEARCH_UNIVERSE \\
        --as-of 2026-09-05 \\
        --db-path ./data/short_interest_data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import PermanentProviderError  # noqa: E402
from data_infra.providers.short_interest_file_import import (  # noqa: E402
    ShortInterestFileImportConfig,
    load_short_interest_csv,
)
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.short_interest_repository import DuckDBShortInterestRepository  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-name", required=True,
        help="Honest name of the external source these CSV files actually came from "
        "(e.g. finra_manual_export). Becomes Provenance.source.",
    )
    parser.add_argument("--data-dir", required=True, type=Path, help="Directory containing one <security_id>.csv per symbol")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE", help="Named universe from src/data_infra/universe.py")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD, stands in for this run's real-world timestamp (retrieved_at/ingestion_time) -- never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/short_interest_ingestion_manifest.json)")
    args = parser.parse_args(argv)

    manifest_path = args.manifest_out or (args.db_path / "short_interest_ingestion_manifest.json")

    if args.symbols is not None:
        symbols = list(args.symbols)
    else:
        symbols = list(_UNIVERSES[args.universe].symbol_ids)

    config = ShortInterestFileImportConfig(source_name=args.source_name, data_dir=args.data_dir)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBShortInterestRepository(engine)

    try:
        per_symbol_results = []
        missing_symbols = []
        total_records_persisted = 0

        for i, symbol in enumerate(symbols, start=1):
            try:
                records = load_short_interest_csv(config, symbol, retrieved_at=args.as_of)
            except PermanentProviderError as exc:
                print(f"  [{i}/{len(symbols)}] {symbol}: {exc}", flush=True)
                missing_symbols.append(symbol)
                per_symbol_results.append({"security_id": symbol, "records_persisted": 0, "error": str(exc)})
                continue

            repository.add_short_interest_records(records)
            total_records_persisted += len(records)
            per_symbol_results.append({"security_id": symbol, "records_persisted": len(records), "error": None})
            print(f"  [{i}/{len(symbols)}] {symbol}: {len(records)} record(s) persisted", flush=True)

        checksum = compute_data_version(
            {
                "source_name": args.source_name,
                "symbols": sorted(symbols),
                "per_symbol_record_counts": {r["security_id"]: r["records_persisted"] for r in per_symbol_results},
            }
        )

        manifest = {
            "note": (
                "This manifest describes a LOCAL FILE IMPORT run -- the CSV files "
                "under --data-dir were NOT fetched over the network by this script. "
                "Whether their content genuinely reflects FINRA's real reported short "
                "interest depends entirely on how the user acquired and prepared them; "
                "this script only validates their SHAPE, never their truthfulness "
                "(same discipline import_external_market_data.py's own manifest "
                "already documents)."
            ),
            "data_status": "REAL",
            "source_name": args.source_name,
            "data_dir": str(args.data_dir),
            "universe_name": args.universe if args.symbols is None else None,
            "symbols": list(symbols),
            "symbol_count": len(symbols),
            "missing_symbols": missing_symbols,
            "as_of": args.as_of.isoformat(),
            "total_records_persisted": total_records_persisted,
            "per_symbol_results": per_symbol_results,
            "db_path": str(args.db_path),
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

        print(f"Symbols requested: {len(symbols)}")
        print(f"Missing symbols (no local CSV): {missing_symbols}")
        print(f"Total short interest records persisted: {total_records_persisted}")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        return 0 if not missing_symbols and total_records_persisted > 0 else 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
