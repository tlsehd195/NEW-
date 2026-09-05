#!/usr/bin/env python3
"""Real sector-classification fetch CLI (Session 36, ADR-0055).

Mirrors `ingest_fundamentals_data.py`'s own reasoning exactly, applied
to a DIFFERENT SEC EDGAR endpoint (`/submissions/CIK....json` instead
of `/api/xbrl/companyfacts/CIK....json`): this development
environment's outbound network is blocked to `data.sec.gov`, so this
script is NEVER executed by this repository's own automated test suite
and makes REAL network calls when run. Run it only in an environment
with real internet access.

Every module this script imports (`SecEdgarFundamentalsProvider.
fetch_submissions`/`normalize_submissions`, `resolve_cik`,
`SecEdgarHttpTransport`) already exists and is already covered by this
repository's own fixture-based test suite (`tests/data_infra/
test_sec_edgar_provider.py`) -- this script performs no new
data-handling logic itself, it only wires those exact, unmodified
pieces together against a real network, the same division of
responsibility `ingest_fundamentals_data.py`/`ingest_real_market_data.py`
already established.

**Deliberately does NOT write into `src/data_infra/universe.py`.**
Every `SymbolMetadata` entry in that module is a hand-curated Python
literal (Stage 1-4 all follow this discipline, see that module's own
"manual_curation" convention) -- this script writes its real,
provider-sourced findings to a separate JSON report instead. Applying
them to `universe.py` (updating each symbol's `sector=` field with the
real value this report found) is a deliberate follow-up step for a
human/future session to do by hand, not something this script attempts
automatically -- there is no established "apply this JSON to a Python
source literal" mechanism in this project, and building one for a
one-time application would be more machinery than the task needs.

Usage:
    python3 scripts/fetch_sector_classifications.py \\
        --universe RESEARCH_UNIVERSE \\
        --user-agent "YourProjectName your-real-email@example.com" \\
        --as-of 2026-09-04 \\
        --out ./data/sector_classifications.json
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
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}

# Same real, verified correction `ingest_fundamentals_data.py` already
# applies by default (ADR-0042) -- XOM's current SEC ticker-map CIK
# points at a newly-registered holding-company CIK, not the operating
# company's real multi-decade filing history. Kept as an independent
# copy here (not imported from that script) matching this project's
# existing convention of each real-ingestion script being self-contained
# rather than importing from a sibling script.
_KNOWN_CIK_OVERRIDES = {"XOM": "0000034088"}

_REQUEST_DELAY_SECONDS = 0.3
_TICKER_MAP_HOST = "https://www.sec.gov"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE", help="Named universe from src/data_infra/universe.py (default: RESEARCH_UNIVERSE)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely (advanced/ad-hoc use)")
    parser.add_argument("--user-agent", required=True, help="Descriptive contact string SEC's fair-access policy requires, e.g. 'YourProjectName you@example.com' -- no default")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD, stands in for this run's real-world timestamp (report metadata only) -- never derived from wall-clock time")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the JSON report of findings")
    parser.add_argument(
        "--cik-overrides", nargs="+", default=[], metavar="SYMBOL:CIK",
        help="Manual SYMBOL:CIK pairs, same contract as ingest_fundamentals_data.py's own --cik-overrides.",
    )
    args = parser.parse_args(argv)

    if args.symbols is not None:
        symbols = list(args.symbols)
    else:
        symbols = list(_UNIVERSES[args.universe].symbol_ids)

    cik_overrides: dict[str, str] = dict(_KNOWN_CIK_OVERRIDES)
    for pair in args.cik_overrides:
        symbol, _, cik = pair.partition(":")
        if not symbol or not cik:
            print(f"FATAL: --cik-overrides entry {pair!r} is not SYMBOL:CIK", file=sys.stderr)
            return 1
        cik_overrides[symbol.upper()] = cik.zfill(10)

    config = SecEdgarConfig(user_agent=args.user_agent)
    transport = SecEdgarHttpTransport(config.base_url, user_agent=config.user_agent)
    ticker_map_transport = SecEdgarHttpTransport(_TICKER_MAP_HOST, user_agent=config.user_agent)
    provider = SecEdgarFundamentalsProvider(config, transport)

    print(f"Fetching SEC EDGAR ticker map from {_TICKER_MAP_HOST} (a multi-MB file, may take a moment)...", flush=True)
    try:
        ticker_map = provider.fetch_ticker_map(ticker_map_transport)
    except (TransientProviderError, PermanentProviderError) as exc:
        print(f"FATAL: could not fetch SEC EDGAR ticker map: {exc}", file=sys.stderr)
        return 1
    print(f"Ticker map fetched ({len(ticker_map)} entries). Fetching {len(symbols)} symbol(s)...", flush=True)

    per_symbol_results = []
    unresolved_symbols = []

    for i, symbol in enumerate(symbols, start=1):
        if symbol in cik_overrides:
            cik = cik_overrides[symbol]
            cik_source = "override"
        else:
            cik = resolve_cik(symbol, ticker_map)
            cik_source = "ticker_map"

        if cik is None:
            print(f"  [{i}/{len(symbols)}] {symbol}: no CIK found, skipping", flush=True)
            unresolved_symbols.append(symbol)
            per_symbol_results.append({"security_id": symbol, "cik": None, "cik_source": None, "sector": None, "exchange": None, "error": "ticker not found in SEC EDGAR company_tickers.json"})
            continue

        print(f"  [{i}/{len(symbols)}] {symbol} (CIK {cik}, source={cik_source}): fetching submissions...", flush=True)
        try:
            raw_submissions = provider.fetch_submissions(cik)
            metadata = provider.normalize_submissions(symbol, raw_submissions)
            per_symbol_results.append({
                "security_id": symbol, "cik": cik, "cik_source": cik_source,
                "sector": metadata.sector, "exchange": metadata.exchange, "error": None,
            })
            print(f"      -> sector={metadata.sector!r} exchange={metadata.exchange!r}", flush=True)
        except (TransientProviderError, PermanentProviderError, ValueError) as exc:
            # ValueError alongside the two provider errors -- same
            # per-symbol resilience discipline `ingest_fundamentals_
            # data.py`'s own per-symbol loop now applies (a real
            # crash from a single malformed EDGAR entry was found
            # and fixed there; this loop degrades identically rather
            # than losing every already-fetched symbol's progress).
            per_symbol_results.append({"security_id": symbol, "cik": cik, "cik_source": cik_source, "sector": None, "exchange": None, "error": str(exc)})
            print(f"      -> FAILED: {exc}", flush=True)

        time.sleep(_REQUEST_DELAY_SECONDS)

    checksum = compute_data_version({
        "symbols": sorted(symbols),
        "per_symbol_sectors": {r["security_id"]: r["sector"] for r in per_symbol_results},
    })

    report = {
        "note": (
            "Real SEC EDGAR /submissions/ findings, one entry per requested symbol. "
            "sector is the SEC's own SIC classification text (sicDescription), NOT a "
            "GICS sector label -- see SecEdgarFundamentalsProvider.normalize_submissions's "
            "own docstring. This report is NOT automatically applied to "
            "src/data_infra/universe.py's SymbolMetadata entries -- that update is a "
            "deliberate manual follow-up step, matching this project's existing hand-"
            "curation discipline for every SymbolMetadata field."
        ),
        "universe_name": args.universe if args.symbols is None else None,
        "as_of": args.as_of.isoformat(),
        "symbols_requested": len(symbols),
        "unresolved_symbols": unresolved_symbols,
        "per_symbol_results": per_symbol_results,
        "content_checksum": checksum,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    print(f"Symbols requested: {len(symbols)}")
    print(f"Unresolved symbols (no CIK found): {unresolved_symbols}")
    print(f"Content checksum: {checksum}")
    print(f"Report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
