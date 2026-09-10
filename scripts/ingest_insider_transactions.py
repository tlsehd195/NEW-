#!/usr/bin/env python3
"""Real SEC Form 4 insider-transaction ingestion CLI (Session 36
continued, ADR-0086).

Mirrors `ingest_fundamentals_data.py`'s own reasoning exactly, applied
to SEC EDGAR's Form 4 (insider ownership) filings instead of XBRL
company facts: this development environment's outbound network is
blocked to `www.sec.gov`/`data.sec.gov` (same blocker already
confirmed for the fundamentals script, ADR-0042 Decision 2) -- this
script is NEVER executed by this repository's own automated test
suite, and it makes REAL network calls when run. Run it only in an
environment with real internet access.

Every module this script imports (`SecEdgarFundamentalsProvider`'s 5
Form 4 methods, `SecEdgarHttpTransport`, `resolve_cik`,
`DuckDBInsiderRepository`) already exists and is already covered by
this repository's own fixture-based test suite (`test_sec_edgar_form4.py`,
`test_insider_repository.py`) -- this script performs no new
data-handling logic itself, it only wires those exact, unmodified
pieces together against a real network and a real on-disk DuckDB
catalog, the same division of responsibility `ingest_fundamentals_data.py`
already established.

**Single host, unlike `ingest_fundamentals_data.py`'s two hosts**: every
Form 4 endpoint this script calls (`company_tickers.json`,
`/cgi-bin/browse-edgar` for the filing list, `/Archives/edgar/data/...`
for the filing's own index.json and XML document) lives on
`www.sec.gov` -- never `data.sec.gov`, which `SecEdgarFundamentalsProvider`'s
constructor still requires a transport for (its XBRL-company-facts-only
methods), but which this script never calls, so a single throwaway
`SecEdgarHttpTransport` satisfies that unused constructor argument.

Usage:
    python3 scripts/ingest_insider_transactions.py \\
        --universe RESEARCH_UNIVERSE \\
        --user-agent "YourProjectName your-real-email@example.com" \\
        --as-of 2026-09-05 \\
        --db-path ./data/insider_data

`--user-agent`/`--as-of` have the identical no-default-placeholder /
stand-in-for-wall-clock-time reasoning `ingest_fundamentals_data.py`'s
own docstring already gives -- see that module for the full argument,
unchanged here.

Rate limiting: identical fixed delay to `ingest_fundamentals_data.py`,
applied per FILING (not per symbol) -- a Form 4 ingestion run makes
roughly `2 + 2*filings_seen` real requests per symbol (ticker map is
fetched once for the whole run, then filing-list pages + index.json +
XML document per filing), several times more requests per symbol than
the one-request-per-symbol company-facts script.

**Pagination (ADR-0088, corrected for real by ADR-0089)**: a single
un-paginated `fetch_form4_filing_list` call caps out at whatever
`count` EDGAR returns per page -- the first real run of this script
(Session 36 continued, default `count=40`) turned out to only reach
back to 2023-09 for every one of 87 real large-cap symbols
(`insider_buying`'s raw IC screen against the standard 2010-2023-04-28
window then found ZERO observations, since none of the ingested data
existed in that window at all). ADR-0088's first fix used EDGAR's
`dateb` parameter to page backward -- a real second re-ingestion run
still found ZERO observations, and a direct diagnostic proved why:
`dateb` does not filter this endpoint's `output=atom` response at all
(every "next page" request came back byte-for-byte identical to the
first). ADR-0089 replaces it with `start` (a plain 0-based offset),
verified for real against AAPL's live filing history before being
trusted (`start=100` returned exactly the next 100 filings, zero
overlap with `start=0`). `--min-filing-date` (default `2009-06-01`,
giving the trailing-6-month `insider_buying_score` window margin
before the project's standard 2010-01-01 raw-IC start) drives
`_fetch_paginated_filing_list`, which now walks `start` forward by
`--page-size` each call until either that target date is reached or
`--max-filings-per-symbol` (a safety cap against an extremely active
filer's history) is hit.
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
from storage.config import StorageConfig  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402
from storage.insider_repository import DuckDBInsiderRepository  # noqa: E402

_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}

# Same real, verified CIK-orphaning fix `ingest_fundamentals_data.py`
# already applies (ADR-0042) -- Form 4 filings are indexed by the same
# CIK company-facts uses, so the identical override is needed here.
_KNOWN_CIK_OVERRIDES = {"XOM": "0000034088"}

_WWW_HOST = "https://www.sec.gov"
_REQUEST_DELAY_SECONDS = 0.3
_DEFAULT_PAGE_SIZE = 100
# Margin before this project's standard 2010-01-01 raw-IC-screening
# start date -- insider_buying_score looks back a trailing 6 months
# from its own as_of_time, so history must reach a bit earlier than
# 2010-01-01 itself for the first few real rebalance dates in that
# window to see any data at all.
_DEFAULT_MIN_FILING_DATE = "2009-06-01"
# Safety cap, not a target -- an extremely active filer (many insiders,
# frequent trading) could otherwise make one symbol's pagination run
# for a very long time; this stops it well short of that regardless of
# how far --min-filing-date asks to go back.
_DEFAULT_MAX_FILINGS_PER_SYMBOL = 3000


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _fetch_paginated_filing_list(
    provider, cik: str, transport, *, page_size: int, min_filing_date: datetime, max_filings: int,
) -> list[dict]:
    """Walks EDGAR's Form 4 filing list backward in time using the
    `start` offset (ADR-0089) -- see module docstring for why a single
    un-paginated call is not enough, and for the real diagnostic that
    corrected the original ADR-0088 design (`dateb` does not filter
    this endpoint's `output=atom` response at all -- a real re-
    ingestion run's raw IC screen came back with zero observations,
    traced to every page coming back byte-for-byte identical to the
    first; `start`, EDGAR's plain 0-based offset into the same newest-
    first ordering, was then verified for real: `start=100` returned
    exactly the next 100 filings with zero overlap against `start=0`).
    Stops once the oldest filing seen so far is at or before
    `min_filing_date`, once a page comes back with nothing new (either
    genuinely exhausted history, or -- defensively, in case `start`'s
    real behavior has some other boundary quirk not yet observed -- a
    page that repeats prior filings), a partial page (fewer than
    `page_size`, meaning EDGAR has no more history left), or once
    `max_filings` accumulated filings is reached, whichever comes
    first. Deduplicates by `accession_number` across pages regardless,
    as a defensive measure that costs nothing when pages are already
    disjoint (the normal, now-verified case)."""
    all_filings: list[dict] = []
    seen_accessions: set[str] = set()
    start = 0
    while len(all_filings) < max_filings:
        page = provider.fetch_form4_filing_list(cik, transport, count=page_size, start=start)
        new_filings = [f for f in page if f["accession_number"] not in seen_accessions]
        if not new_filings:
            break
        for f in new_filings:
            seen_accessions.add(f["accession_number"])
        all_filings.extend(new_filings)
        oldest = min(f["filing_date"] for f in new_filings)
        if oldest <= min_filing_date:
            break
        if len(page) < page_size:
            break  # EDGAR returned a partial page -- history is exhausted
        start += page_size
    return all_filings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE", help="Named universe from src/data_infra/universe.py (default: RESEARCH_UNIVERSE)")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely (advanced/ad-hoc use)")
    parser.add_argument(
        "--min-filing-date", type=_parse_date, default=_parse_date(_DEFAULT_MIN_FILING_DATE),
        help=f"YYYY-MM-DD. Paginate backward through each symbol's Form 4 history until a filing at or before this date is reached (default: {_DEFAULT_MIN_FILING_DATE}, ADR-0088 -- see module docstring for why a single un-paginated page is not enough).",
    )
    parser.add_argument("--page-size", type=int, default=_DEFAULT_PAGE_SIZE, help=f"Filings requested per EDGAR page (default: {_DEFAULT_PAGE_SIZE})")
    parser.add_argument("--max-filings-per-symbol", type=int, default=_DEFAULT_MAX_FILINGS_PER_SYMBOL, help=f"Safety cap on total filings fetched per symbol regardless of --min-filing-date (default: {_DEFAULT_MAX_FILINGS_PER_SYMBOL})")
    parser.add_argument("--user-agent", required=True, help="Descriptive contact string SEC's fair-access policy requires, e.g. 'YourProjectName you@example.com' -- no default")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD, stands in for this run's real-world timestamp (retrieved_at/ingestion_time) -- never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/insider_ingestion_manifest.json)")
    parser.add_argument(
        "--cik-overrides", nargs="+", default=[], metavar="SYMBOL:CIK",
        help="Manual SYMBOL:CIK pairs (e.g. XOM:0000034088) -- see ingest_fundamentals_data.py's identical flag for the full real-incident reasoning.",
    )
    args = parser.parse_args(argv)

    manifest_path = args.manifest_out or (args.db_path / "insider_ingestion_manifest.json")

    if args.symbols is not None:
        symbols = list(args.symbols)
    else:
        symbols = list(_UNIVERSES[args.universe].symbol_ids)

    cik_overrides: dict[str, str] = dict(_KNOWN_CIK_OVERRIDES)
    for pair in args.cik_overrides:
        symbol, _, cik = pair.partition(":")
        if not symbol or not cik:
            print(f"FATAL: --cik-overrides entry {pair!r} is not in SYMBOL:CIK form", file=sys.stderr)
            return 1
        cik_overrides[symbol.upper()] = cik.zfill(10)

    config = SecEdgarConfig(user_agent=args.user_agent)
    www_transport = SecEdgarHttpTransport(_WWW_HOST, user_agent=config.user_agent)
    # `config`'s own base_url (data.sec.gov) is never actually contacted
    # by this script -- every Form 4 method takes its transport
    # explicitly (module docstring) -- so `www_transport` also
    # satisfies the constructor's otherwise-unused `transport` argument.
    provider = SecEdgarFundamentalsProvider(config, www_transport)

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBInsiderRepository(engine)

    try:
        print(f"Fetching SEC EDGAR ticker map from {_WWW_HOST} (a multi-MB file, may take a moment)...", flush=True)
        try:
            ticker_map = provider.fetch_ticker_map(www_transport)
        except (TransientProviderError, PermanentProviderError) as exc:
            print(f"FATAL: could not fetch SEC EDGAR ticker map: {exc}", file=sys.stderr)
            return 1
        print(f"Ticker map fetched ({len(ticker_map)} entries). Fetching {len(symbols)} symbol(s)...", flush=True)

        per_symbol_results = []
        unresolved_symbols = []
        total_transactions_persisted = 0

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
                per_symbol_results.append({
                    "security_id": symbol, "cik": None, "cik_source": None, "filings_seen": 0,
                    "transactions_persisted": 0, "error": "ticker not found in SEC EDGAR company_tickers.json",
                })
                continue

            print(f"  [{i}/{len(symbols)}] {symbol} (CIK {cik}, source={cik_source}): fetching Form 4 filing list (paginating back to {args.min_filing_date.date()})...", flush=True)
            symbol_transactions = 0
            filing_errors = []
            try:
                filings = _fetch_paginated_filing_list(
                    provider, cik, www_transport, page_size=args.page_size,
                    min_filing_date=args.min_filing_date, max_filings=args.max_filings_per_symbol,
                )
            except (TransientProviderError, PermanentProviderError) as exc:
                per_symbol_results.append({
                    "security_id": symbol, "cik": cik, "cik_source": cik_source, "filings_seen": 0,
                    "transactions_persisted": 0, "error": str(exc),
                })
                print(f"      -> FAILED to fetch filing list: {exc}", flush=True)
                continue

            for filing in filings:
                accession_number = filing["accession_number"]
                filing_date = filing["filing_date"]
                time.sleep(_REQUEST_DELAY_SECONDS)
                try:
                    index_json = provider.fetch_form4_index(cik, accession_number, www_transport)
                    filename = provider.select_form4_primary_document(index_json)
                    if filename is None:
                        filing_errors.append({"accession_number": accession_number, "error": "no ownership-document XML found in index.json"})
                        continue
                    time.sleep(_REQUEST_DELAY_SECONDS)
                    xml_text = provider.fetch_form4_document(cik, accession_number, filename, www_transport)
                    transactions = provider.normalize_form4_document(
                        symbol, xml_text, accession_number=accession_number,
                        filing_date=filing_date, retrieved_at=args.as_of, ingestion_time=args.as_of,
                    )
                    repository.add_insider_transactions(transactions)
                    symbol_transactions += len(transactions)
                except (TransientProviderError, PermanentProviderError, ValueError) as exc:
                    # A single malformed filing must not abort every
                    # other filing for this symbol (or every other
                    # symbol) -- the identical per-item degradation
                    # discipline ingest_fundamentals_data.py's own
                    # per-symbol except clause already established.
                    filing_errors.append({"accession_number": accession_number, "error": str(exc)})

            total_transactions_persisted += symbol_transactions
            per_symbol_results.append({
                "security_id": symbol, "cik": cik, "cik_source": cik_source, "filings_seen": len(filings),
                "transactions_persisted": symbol_transactions, "filing_errors": filing_errors, "error": None,
            })
            print(f"      -> {len(filings)} filing(s) seen, {symbol_transactions} transaction(s) persisted", flush=True)

        checksum = compute_data_version(
            {
                "symbols": sorted(symbols),
                "min_filing_date": args.min_filing_date.date().isoformat(),
                "page_size": args.page_size,
                "max_filings_per_symbol": args.max_filings_per_symbol,
                "per_symbol_transaction_counts": {r["security_id"]: r["transactions_persisted"] for r in per_symbol_results},
            }
        )

        manifest = {
            "note": (
                "This manifest describes a real ingestion run against SEC "
                "EDGAR's live Form 4 endpoints. Transaction counts reflect "
                "whatever EDGAR actually returned at run time -- they are "
                "NOT reproduced or asserted by this repository's own test "
                "suite, which never makes real network calls."
            ),
            "data_status": "REAL",
            "provider": "sec_edgar_form4",
            "universe_name": args.universe if args.symbols is None else None,
            "symbols": list(symbols),
            "symbol_count": len(symbols),
            "min_filing_date": args.min_filing_date.date().isoformat(),
            "page_size": args.page_size,
            "max_filings_per_symbol": args.max_filings_per_symbol,
            "as_of": args.as_of.isoformat(),
            "cik_overrides": dict(cik_overrides),
            "unresolved_symbols": unresolved_symbols,
            "total_transactions_persisted": total_transactions_persisted,
            "per_symbol_results": per_symbol_results,
            "db_path": str(args.db_path),
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

        print(f"Symbols requested: {len(symbols)}")
        print(f"Unresolved symbols (no CIK found): {unresolved_symbols}")
        print(f"Total insider transactions persisted: {total_transactions_persisted}")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        return 0 if not unresolved_symbols and total_transactions_persisted > 0 else 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
