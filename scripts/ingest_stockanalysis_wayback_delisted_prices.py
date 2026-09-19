#!/usr/bin/env python3
"""Real ingestion of sparse, point-in-time delisted-stock prices from
Wayback Machine snapshots of `stockanalysis.com` -- fills part of the
real, honestly-measured survivorship-bias gap `report_survivorship_
price_coverage.py`/ADR-0129 already quantified (623 S&P 500 tickers
removed since 2000, only 59 with any real price data; 564 remain a
gap). `stockanalysis.com` itself has been directly blocked from this
project's own environments (403, confirmed for real from both this
session's sandbox and a GitHub Actions runner, ADR unresolved) -- this
instead reads its PAST content through the Wayback Machine, which a
real 2026-09-19 recon session confirmed does work (real AVB prices
recovered from real archived snapshots, cross-checked against AVB's
known real 2020/2024 trading range).

**Real, structural limitation, confirmed by that same recon, not
assumed**: `stockanalysis.com` itself did not exist before ~2020 (its
earliest Wayback snapshot for a real, continuously-tracked ticker is
2020-08-06) -- so this can only ever help tickers whose LAST index
membership ended in 2020 or later (`select_delisted_candidates_since.py
--since 2020-01-01`, real count: 142 of the 623). It also only
recovers sparse point-in-time prices (Wayback's own real capture
cadence for one page was ~28 snapshots across 6 years, roughly
quarterly) -- this is a coarse anchor series, never a substitute for
real daily OHLCV.

**Real, structural limitation #2, an explicit simplification, not
fabrication**: `stockanalysis.com`'s own page shows exactly one
point-in-time "last/current price" per snapshot, never a full
OHLCV bar. Every persisted `PriceBar` here therefore sets
``open == high == low == close`` to that single scraped value and
``volume = 0.0`` -- this is NOT a claim that the real bar had zero
range or zero volume, it is this script's own honest inability to
recover more than one number per snapshot. `provenance.source` is
always ``"stockanalysis_com_via_wayback_machine"`` specifically so a
future consumer can recognize and special-case this (e.g. exclude it
from any check that assumes real volume, mirroring
ADR-0126's own "confirmed scraper artifact, filtered by volume == 0"
precedent for a different real gap).

**Real site-layout changes, confirmed by real recon across all 28 AVB
snapshots (2020-08-06 through 2026-06-15), not assumed**: `stockanalysis.
com` was redesigned multiple times; three distinct real HTML
structures were found and are tried in order per snapshot:

1. (~2020-08 to ~2021-04) ``id="qLast">$PRICE</td>``
2. (~2021-10 to ~2023-03) ``class="p svelte-XXXXX">PRICE</div>`` (the
   Svelte scoped-class hash suffix varies by build, matched generically)
3. (~2023-04 onward) ``class="text-4xl font-bold ... inline-block">
   PRICE</div>`` (extra Tailwind classes were added over time between
   the two extra CSS classes; matched with a wildcard in between)

A snapshot matching none of these three real patterns is recorded as a
real parse failure in the manifest, never silently dropped.

The snapshot's own Wayback CDX ``timestamp`` (when the page was
archived) is used as the price's observation date -- these are
"current price" pages, so capture time is a reasonable real proxy for
observation time; no per-era date-text parsing is attempted (each of
the three eras phrases "as of" text differently, and parsing it would
only add fragility for no real benefit over the timestamp already
given by the CDX index itself).

Rate-limited (1 request per second, matching what a real recon session
found `archive.org` tolerates today -- it 429'd this same session
minutes earlier at a higher rate) -- a full 142-candidate run makes
real, moderate demands on a free, shared archival service and should
not be run casually or repeatedly.

Makes REAL network calls (archive.org) -- never exercised by this
repository's own automated test suite; see
`tests/scripts/test_ingest_stockanalysis_wayback_delisted_prices.py`
for the real, executable coverage of the three parsing patterns
(fixtures are the ACTUAL HTML fragments recovered during the real
2026-09-19 recon, not synthesized).

Usage:
    python3 scripts/ingest_stockanalysis_wayback_delisted_prices.py \\
        --symbols AVB CTL COTY \\
        --as-of 2026-09-19 \\
        --db-path ./data/wayback_delisted_prices
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.models import PriceBar, Provenance  # noqa: E402
from data_infra.versioning import compute_data_version  # noqa: E402
from storage.config import StorageConfig  # noqa: E402
from storage.data_repository import DuckDBDataRepository  # noqa: E402
from storage.engine import StorageEngine  # noqa: E402

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_REQUEST_DELAY_SECONDS = 1.0
_SOURCE = "stockanalysis_com_via_wayback_machine"

# Real, confirmed-by-recon patterns (see module docstring) -- tried in
# order, first match wins. Each captures the bare price number.
_PRICE_PATTERNS = [
    re.compile(r'id="qLast">\$?([\d,]+\.\d+)'),
    re.compile(r'class="p svelte-\w+">([\d,]+\.\d+)</div>'),
    re.compile(r'class="text-4xl font-bold[^"]*inline-block">([\d,]+\.\d+)</div>'),
]


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _parse_cdx_timestamp(value: str) -> datetime:
    """CDX ``timestamp`` is always ``YYYYMMDDHHMMSS`` in UTC (Wayback's
    own documented convention)."""
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def extract_price(html: str) -> float | None:
    """Tries each real, confirmed pattern in order; returns the first
    match's price, or ``None`` if none of the three known real
    `stockanalysis.com` layouts match (a real parse failure, never
    guessed at with a looser fallback)."""
    for pattern in _PRICE_PATTERNS:
        m = pattern.search(html)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def fetch_snapshot_list(ticker: str) -> list[dict]:
    """Real CDX query for every `stockanalysis.com/stocks/<ticker>`
    snapshot. Filters to real, fully-rendered HTML pages only
    (``statuscode == "200"``, ``mimetype == "text/html"``) -- a
    redirect (e.g. the real 308 seen for AVB on 2023-04-26, a trailing-
    slash normalization) or a failed capture carries no real page
    content to parse."""
    url = (
        "https://web.archive.org/cdx/search/cdx?url=stockanalysis.com/stocks/"
        f"{ticker.lower()}&output=json&limit=1000"
    )
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        rows = json.loads(response.read())
    if not rows:
        return []
    header, *data = rows
    snapshots = [dict(zip(header, row)) for row in data]
    return [s for s in snapshots if s.get("statuscode") == "200" and s.get("mimetype") == "text/html"]


def fetch_snapshot_html(timestamp: str, original_url: str) -> str:
    url = f"http://web.archive.org/web/{timestamp}/{original_url}"
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def build_price_bar(ticker: str, timestamp: str, price: float, *, as_of_time: datetime) -> PriceBar:
    observed_at = _parse_cdx_timestamp(timestamp)
    return PriceBar(
        security_id=ticker,
        timestamp=observed_at,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=0.0,
        available_time=as_of_time,
        ingestion_time=as_of_time,
        provenance=Provenance(
            source=_SOURCE,
            source_dataset=f"{_SOURCE}_{ticker}",
            source_record_id=f"{ticker}:{timestamp}",
            retrieved_at=as_of_time,
            data_version=compute_data_version({"ticker": ticker, "timestamp": timestamp, "price": price}),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", required=True, help="Delisted tickers to recover sparse Wayback-archived prices for (see select_delisted_candidates_since.py --since 2020-01-01 for the real, era-appropriate candidate list)")
    parser.add_argument("--as-of", required=True, type=_parse_date, help="YYYY-MM-DD, stands in for this run's real-world timestamp (retrieved_at/ingestion_time/available_time) -- never derived from wall-clock time")
    parser.add_argument("--db-path", required=True, type=Path, help="Directory for the DuckDB catalog + Parquet store (created if it does not exist)")
    parser.add_argument("--manifest-out", type=Path, default=None, help="Where to write the JSON reproducibility manifest (default: <db-path>/wayback_ingestion_manifest.json)")
    args = parser.parse_args(argv)

    manifest_path = args.manifest_out or (args.db_path / "wayback_ingestion_manifest.json")

    engine = StorageEngine(StorageConfig(root_dir=args.db_path))
    repository = DuckDBDataRepository(engine)
    try:
        per_symbol_results = []
        all_bars: list[PriceBar] = []

        for i, ticker in enumerate(args.symbols, start=1):
            print(f"  [{i}/{len(args.symbols)}] {ticker}: fetching Wayback snapshot list...", flush=True)
            try:
                snapshots = fetch_snapshot_list(ticker)
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                per_symbol_results.append({"security_id": ticker, "snapshots_seen": 0, "bars_persisted": 0, "parse_failures": 0, "error": str(exc)})
                print(f"      -> FAILED to fetch snapshot list: {exc}", flush=True)
                continue

            time.sleep(_REQUEST_DELAY_SECONDS)
            print(f"      -> {len(snapshots)} real snapshot(s) found, fetching each...", flush=True)
            symbol_bars: list[PriceBar] = []
            parse_failures = []
            for snapshot in snapshots:
                timestamp = snapshot["timestamp"]
                original_url = snapshot["original"]
                time.sleep(_REQUEST_DELAY_SECONDS)
                try:
                    html = fetch_snapshot_html(timestamp, original_url)
                except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                    parse_failures.append({"timestamp": timestamp, "error": str(exc)})
                    continue
                price = extract_price(html)
                if price is None:
                    parse_failures.append({"timestamp": timestamp, "error": "no known real price pattern matched"})
                    continue
                symbol_bars.append(build_price_bar(ticker, timestamp, price, as_of_time=args.as_of))

            all_bars.extend(symbol_bars)
            per_symbol_results.append({
                "security_id": ticker, "snapshots_seen": len(snapshots),
                "bars_persisted": len(symbol_bars), "parse_failures": len(parse_failures),
                "parse_failure_detail": parse_failures, "error": None,
            })
            print(f"      -> {len(snapshots)} snapshot(s) seen, {len(symbol_bars)} price(s) recovered, {len(parse_failures)} parse failure(s)", flush=True)

        written = repository.append_bars(all_bars)

        checksum = compute_data_version({
            "symbols": sorted(args.symbols),
            "per_symbol_bar_counts": {r["security_id"]: r["bars_persisted"] for r in per_symbol_results},
        })
        manifest = {
            "note": (
                "This manifest describes a real ingestion run against Wayback Machine "
                "archives of stockanalysis.com. Every bar has open == high == low == close "
                "(a single scraped point-in-time price, never real OHLC) and volume == 0.0 "
                "(unknown, not a real zero) -- see this script's own module docstring. "
                "Never reproduced or asserted by this repository's own test suite, which "
                "never makes real network calls."
            ),
            "data_status": "REAL",
            "provider": _SOURCE,
            "symbols": list(args.symbols),
            "symbol_count": len(args.symbols),
            "as_of": args.as_of.isoformat(),
            "per_symbol_results": per_symbol_results,
            "total_bars_written": written,
            "db_path": str(args.db_path),
            "content_checksum": checksum,
            "data_version": checksum,
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

        failed_symbols = [r["security_id"] for r in per_symbol_results if r["error"] is not None]
        print(f"Symbols requested: {len(args.symbols)}")
        print(f"Failed symbols (fetch error): {failed_symbols}")
        print(f"Total bars written: {written}")
        print(f"Content checksum: {checksum}")
        print(f"Manifest written to: {manifest_path}")
        return 0 if not failed_symbols else 1
    finally:
        engine.close()


if __name__ == "__main__":
    sys.exit(main())
