#!/usr/bin/env python3
"""Real fundamentals data ingestion CLI (Phase 33, ADR-0042).

Mirrors `ingest_real_market_data.py`'s own reasoning exactly, applied
to SEC EDGAR instead of Tiingo/Stooq: this development environment's
outbound network is blocked to `data.sec.gov` (re-confirmed this
phase, see ADR-0042 Decision 2) -- this script is NEVER executed by
this repository's own automated test suite, and it makes REAL network
calls when run. Run it only in an environment with real internet
access (ADR-0042 already confirmed `data.sec.gov` is reachable from
the user's own environment, and that `SecEdgarFundamentalsProvider`'s
parsing contract matches real EDGAR responses field-for-field).

Every module this script imports (`SecEdgarFundamentalsProvider`,
`SecEdgarHttpTransport`, `resolve_cik`, `DuckDBFundamentalsRepository`)
already exists and is already covered by this repository's own
fixture-based test suite -- this script performs no new data-handling
logic itself, it only wires those exact, unmodified pieces together
against a real network and a real on-disk DuckDB catalog, the same
division of responsibility `ingest_real_market_data.py` already
established.

Usage:
    python3 scripts/ingest_fundamentals_data.py \\
        --universe RESEARCH_UNIVERSE \\
        --user-agent "YourProjectName your-real-email@example.com" \\
        --as-of 2026-08-29 \\
        --db-path ./data/fundamentals_data

`--user-agent` has no default placeholder here (unlike
`SecEdgarConfig.user_agent`'s own dataclass default, which exists only
so the config type can be constructed in tests without a real value) --
SEC's fair-access policy requires a genuine descriptive contact string
on every request, so this script refuses to run without one explicitly
supplied.

`--as-of` (like `ingest_real_market_data.py`'s own `--end`) stands in
for "when this ingestion run happened" for `retrieved_at`/
`ingestion_time` -- never read from wall-clock time, so two runs with
identical arguments against a fresh database are reproducible up to
whatever EDGAR itself returns differently at different real moments (a
fact this script cannot control and does not hide, matching the price
ingestion script's own manifest `note` field).

Rate limiting: a small fixed delay between per-symbol requests, well
under SEC's own published ~10 req/sec fair-access guidance -- this
project's universes are small (dozens of symbols, not thousands), so
no adaptive backoff is implemented; `TransientProviderError` (429/5xx,
already handled by `SecEdgarHttpTransport`) surfaces as a per-symbol
ingestion failure recorded in the manifest, not a retry loop (no
concrete need for one yet, same reasoning ADR-0039 applied to
portfolio optimization).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import PermanentProviderError, TransientProviderError  # noqa: E402
from data_infra.providers.sec_edgar import SecEdgarFundamentalsProvider, resolve_cik  # noqa: E402
from data_infra.providers.sec_edgar_config import SecEdgarConfig  # noqa: E402
from data_infra.providers.sec_edgar_transport import SecEdgarHttpTransport  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE2  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.fundamentals_repository import DuckDBFundamentalsRepository  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE2}

# A short, deliberately chosen starting set (ADR-0042 Decision 4) --
# not exhaustive, not fixed for all time; --concepts overrides it.
# Core income-statement/balance-sheet line items with broad us-gaap
# reporting coverage across most large-cap filers.
_DEFAULT_CONCEPTS = ("Revenues", "NetIncomeLoss", "Assets", "Liabilities", "StockholdersEquity")

_REQUEST_DELAY_SECONDS = 0.3
_TICKER_MAP_HOST = "https://www.sec.gov"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE", help="Named universe from src/data_infra/universe.py (default: RESEARCH_UNIVERSE)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely (advanced/ad-hoc use)")
    parser.add_argument("--concepts", nargs="+", default=list(_DEFAULT_CONCEPTS), help=f"us-gaap XBRL concept names to fetch (default: {list(_DEFAULT_CONCEPTS)})")
    parser.add_argument("--user-agent", required=True, help="Descriptive contact string SEC's fair-access policy requires, e.g. 'YourProjectName you@example.com' -- no default")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD, stands in for this run's real-world timestamp (retrieved_at/ingestion_time) -- never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/fundamentals_ingestion_manifest.json)")
    args = parser.parse_args(argv)

    manifest_path = args.manifest_out or (args.db_path / "fundamentals_ingestion_manifest.json")

    if args.symbols is not None:
        symbols = list(args.symbols)
    else:
        symbols = list(_UNIVERSES[args.universe].symbol_ids)

    config = SecEdgarConfig(user_agent=args.user_agent)
    facts_transport = SecEdgarHttpTransport(config.base_url, user_agent=config.user_agent)
    ticker_map_transport = SecEdgarHttpTransport(_TICKER_MAP_HOST, user_agent=config.user_agent)
    provider = SecEdgarFundamentalsProvider(config, facts_transport)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBFundamentalsRepository(engine)

    try:
        # Printed with flush=True and before/after each real network
        # call (not batched to the end) -- fetching all of company_tickers.json
        # (a multi-MB file listing every SEC filer) plus each symbol's
        # full XBRL company-facts response (multi-MB for a large-cap
        # with a long filing history) genuinely takes real wall-clock
        # time; without incremental output a terminal watching this run
        # looks indistinguishable from a hang.
        print(f"Fetching SEC EDGAR ticker map from {_TICKER_MAP_HOST} (a multi-MB file, may take a moment)...", flush=True)
        try:
            ticker_map = provider.fetch_ticker_map(ticker_map_transport)
        except (TransientProviderError, PermanentProviderError) as exc:
            print(f"FATAL: could not fetch SEC EDGAR ticker map: {exc}", file=sys.stderr)
            return 1
        print(f"Ticker map fetched ({len(ticker_map)} entries). Fetching {len(symbols)} symbol(s)...", flush=True)

        per_symbol_results = []
        unresolved_symbols = []
        total_records_persisted = 0

        for i, symbol in enumerate(symbols, start=1):
            cik = resolve_cik(symbol, ticker_map)
            if cik is None:
                print(f"  [{i}/{len(symbols)}] {symbol}: no CIK found, skipping", flush=True)
                unresolved_symbols.append(symbol)
                per_symbol_results.append({"security_id": symbol, "cik": None, "records_persisted": 0, "error": "ticker not found in SEC EDGAR company_tickers.json"})
                continue

            print(f"  [{i}/{len(symbols)}] {symbol} (CIK {cik}): fetching company facts...", flush=True)
            try:
                raw_facts = provider.fetch_company_facts(cik)
                records = provider.normalize_company_facts(
                    symbol, raw_facts, args.concepts, retrieved_at=args.as_of, ingestion_time=args.as_of
                )
                repository.add_fundamentals(records)
                total_records_persisted += len(records)
                per_symbol_results.append({"security_id": symbol, "cik": cik, "records_persisted": len(records), "error": None})
                print(f"      -> {len(records)} record(s) persisted", flush=True)
            except (TransientProviderError, PermanentProviderError) as exc:
                per_symbol_results.append({"security_id": symbol, "cik": cik, "records_persisted": 0, "error": str(exc)})
                print(f"      -> FAILED: {exc}", flush=True)

            time.sleep(_REQUEST_DELAY_SECONDS)

        checksum = compute_data_version(
            {
                "symbols": sorted(symbols),
                "concepts": sorted(args.concepts),
                "per_symbol_record_counts": {r["security_id"]: r["records_persisted"] for r in per_symbol_results},
            }
        )

        manifest = {
            "note": (
                "This manifest describes a real ingestion run against SEC "
                "EDGAR's live XBRL API. Record counts reflect whatever "
                "EDGAR actually returned at run time -- they are NOT "
                "reproduced or asserted by this repository's own test "
                "suite, which never makes real network calls."
            ),
            "data_status": "REAL",
            "provider": "sec_edgar",
            "universe_name": args.universe if args.symbols is None else None,
            "symbols": list(symbols),
            "symbol_count": len(symbols),
            "concepts": list(args.concepts),
            "as_of": args.as_of.isoformat(),
            "unresolved_symbols": unresolved_symbols,
            "total_records_persisted": total_records_persisted,
            "per_symbol_results": per_symbol_results,
            "db_path": str(args.db_path),
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))

        print(f"Symbols requested: {len(symbols)}")
        print(f"Unresolved symbols (no CIK found): {unresolved_symbols}")
        print(f"Total fundamental records persisted: {total_records_persisted}")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        return 0 if not unresolved_symbols and total_records_persisted > 0 else 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
