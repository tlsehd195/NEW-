#!/usr/bin/env python3
"""Builds a real, doubly-confirmed `{ticker: cusip}` map for a given
symbol list -- the one-time (re-run only if the universe changes)
prerequisite step for `scripts/backfill_institutional_holdings_from_
sec_bulk.py`'s multi-quarter real institutional-ownership backfill.

**Needs no new, unverified capability** -- reuses two ALREADY real,
verified pieces of this project's own infrastructure instead of
guessing at a company name or a ticker->CUSIP direction OpenFIGI has
never been confirmed to support for free:

    1. `data_infra.providers.sec_edgar.resolve_company_title` reads the
       real company name straight out of `company_tickers.json`, the
       SAME file `scripts/ingest_insider_transactions.py` already
       fetches for real, every real run (Phase 33/`ADR-0042`) -- no
       new network call type.
    2. `data_infra.providers.openfigi_cusip_resolution` -- the CUSIP->
       ticker direction `ADR-0131` already real-verified. A CANDIDATE
       CUSIP found by name-matching is only trusted once THIS already-
       verified direction confirms it resolves back to the expected
       ticker (never trusting a text match alone -- see `scripts/
       verify_sec_13f_bulk_dataset.py`'s own real 2026-09-26 run for
       why: AAPL alone had 8 name-matched candidate CUSIPs, and exactly
       one confirmed real).

Real network calls: `www.sec.gov` (`company_tickers.json` + one bulk
13F window ZIP, ~86MB real size observed 2026-09-26) and
`api.openfigi.com` (batched, 10 CUSIPs/request, 2.5s between batches --
`ADR-0131`'s own real, confirmed no-API-key limits).

**Real bug found and fixed (2026-09-26, first real run of this
script)**: the automatic "most recent window" selection originally
assumed a window is published as soon as its own `end` date has
passed. Real, confirmed wrong: on 2026-09-26, the `01jun2026-
31aug2026` window (ended 2026-08-31, weeks earlier) still 404'd -- SEC
publishes a real, unknown lag AFTER a window closes. Fixed by trying
the last 8 completed windows newest-first, falling back to an earlier
one on a real 404, rather than assuming the newest is always ready.

**ADR-0231 (2026-10-02)**: the map now keeps EVERY CUSIP a company has
used (`{ticker: [cusip, ...]}`), found by name-matching the company's
current AND former SEC names (`formerNames` in its EDGAR submissions)
across one 13F file per year since 2013 plus the latest published one,
and confirmed per `data_infra.providers.sec_13f_cusip_history`. OpenFIGI
per-item errors (e.g. rate limits) are retried and every unmatched
ticker is printed with the reason, instead of silently becoming "no
match" (the 2026-09-26 run dropped XOM, BAC, WFC and 9 more that way).

Usage:
    python3 scripts/build_institutional_ownership_cusip_map.py \\
        --user-agent "NEW- you@example.com" \\
        --universe RESEARCH_UNIVERSE \\
        --out cusip_map.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data_infra.provider import PermanentProviderError, TransientProviderError  # noqa: E402
from data_infra.providers.openfigi_cusip_resolution import build_mapping_request  # noqa: E402
from data_infra.providers.sec_13f_cusip_history import company_names, confirm_cusips, name_matches  # noqa: E402
from data_infra.providers.sec_13f_bulk_dataset import generate_filing_windows  # noqa: E402
from data_infra.providers.sec_edgar import SecEdgarFundamentalsProvider, resolve_cik, resolve_company_title  # noqa: E402
from data_infra.providers.sec_edgar_config import SecEdgarConfig  # noqa: E402
from data_infra.providers.sec_edgar_transport import SecEdgarHttpTransport  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402

_WWW_HOST = "https://www.sec.gov"
_DATA_HOST = "https://data.sec.gov"
_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}
_OPENFIGI_BATCH_SIZE = 10  # ADR-0131's own real, confirmed no-API-key limit
_OPENFIGI_RETRIES = 3
_FIRST_13F_YEAR = 2013  # SEC's structured 13F data sets start with 2013 Q3 filings
_RENAMES_CSV = Path(__file__).resolve().parent.parent / "docs" / "research" / "reference" / "sp500_ticker_renames.csv"


def _download_zip(url: str, user_agent: str) -> Optional[bytes]:
    """`None` on a real HTTP 404 (window not published, or never
    published that far back). Any other error propagates."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _iter_infotable(raw_zip: bytes):
    """Streams (NAMEOFISSUER, CUSIP) from a window's INFOTABLE.tsv, so a
    multi-million-row file is never held in memory as dicts."""
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        names = [n for n in zf.namelist() if Path(n).name.upper() == "INFOTABLE.TSV"]
        if not names:
            raise FileNotFoundError(f"INFOTABLE.tsv not found in archive; entries: {zf.namelist()}")
        with zf.open(names[0]) as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"):
                yield row.get("NAMEOFISSUER", ""), row.get("CUSIP", "").strip().upper()


def _sample_window_urls(today: date) -> list[str]:
    """One file per year: the legacy Q3 file (2013-2023), the 01jun
    window (2024 on), plus the two newest windows. Unpublished ones 404
    and are skipped by the caller."""
    windows = generate_filing_windows(_FIRST_13F_YEAR, today - timedelta(days=1))
    legacy = [w.url for w in windows if w.url.endswith("q3_form13f.zip")]
    window_style = [w for w in windows if "q" not in Path(w.url).name.split("_")[0] and w.end < today]
    yearly = [w.url for w in window_style if w.start.month == 6]
    return legacy + yearly + [w.url for w in window_style[-2:] if w.url not in yearly]


def _resolve_cusips_via_openfigi(cusips: list[str]) -> tuple[dict[str, Optional[str]], dict[str, str]]:
    """CUSIP -> ticker (None if unresolved) plus CUSIP -> OpenFIGI error
    text for the ones that never resolved. Items that error (rather
    than return no data) are retried after a pause."""
    resolved: dict[str, Optional[str]] = {}
    errors: dict[str, str] = {}
    pending = list(cusips)
    for attempt in range(_OPENFIGI_RETRIES):
        retry: list[str] = []
        for i in range(0, len(pending), _OPENFIGI_BATCH_SIZE):
            batch = pending[i : i + _OPENFIGI_BATCH_SIZE]
            body = json.dumps(build_mapping_request(batch)).encode("utf-8")
            req = urllib.request.Request(
                "https://api.openfigi.com/v3/mapping", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    response_json = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    raise
                retry.extend(batch)
                errors.update({c: "HTTP 429" for c in batch})
                time.sleep(60)
                continue
            for cusip, entry in zip(batch, response_json):
                data = entry.get("data")
                if data:
                    resolved[cusip] = data[0]["ticker"]
                    errors.pop(cusip, None)
                elif "error" in entry and "No identifier found" not in str(entry["error"]):
                    retry.append(cusip)
                    errors[cusip] = str(entry["error"])
                else:
                    resolved[cusip] = None
                    errors.pop(cusip, None)
            time.sleep(2.6)  # real confirmed cap is 25 req/60s
        if not retry:
            break
        print(f"  OpenFIGI: retrying {len(retry)} CUSIPs after errors (attempt {attempt + 2}/{_OPENFIGI_RETRIES})", flush=True)
        time.sleep(60)
        pending = retry
    for cusip in pending:
        resolved.setdefault(cusip, None)
    return resolved, errors


def _aliases_by_ticker() -> dict[str, set[str]]:
    """Former tickers from the S&P 500 rename list (old -> new)."""
    aliases: dict[str, set[str]] = defaultdict(set)
    if _RENAMES_CSV.exists():
        with _RENAMES_CSV.open() as fh:
            for row in csv.DictReader(fh):
                aliases[row["new_ticker"].strip()].add(row["old_ticker"].strip())
    return aliases


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-agent", required=True, help="SEC fair-access contact string (real, reachable identifier)")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely")
    parser.add_argument("--window-url", action="append", default=None, help="13F bulk ZIP URL(s) to name-match against (default: one per year since 2013 plus the latest)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the {ticker: [cusip, ...]} JSON map")
    args = parser.parse_args(argv)

    symbols = list(args.symbols) if args.symbols is not None else list(_UNIVERSES[args.universe].symbol_ids)
    config = SecEdgarConfig(user_agent=args.user_agent)
    www_transport = SecEdgarHttpTransport(_WWW_HOST, user_agent=config.user_agent)
    data_transport = SecEdgarHttpTransport(_DATA_HOST, user_agent=config.user_agent)
    provider = SecEdgarFundamentalsProvider(config, data_transport)

    print(f"Fetching SEC EDGAR ticker map from {_WWW_HOST} ...", flush=True)
    try:
        ticker_map = provider.fetch_ticker_map(www_transport)
    except (TransientProviderError, PermanentProviderError) as exc:
        print(f"FATAL: could not fetch SEC EDGAR ticker map: {exc}", file=sys.stderr)
        return 1

    names_by_ticker: dict[str, list[str]] = {}
    reasons: dict[str, str] = {}
    for ticker in symbols:
        title = resolve_company_title(ticker, ticker_map)
        cik = resolve_cik(ticker, ticker_map)
        if title is None or cik is None:
            reasons[ticker] = "not in SEC company_tickers.json"
            continue
        try:
            submissions = provider.fetch_submissions(cik)
        except (TransientProviderError, PermanentProviderError) as exc:
            print(f"  WARNING: {ticker} submissions unavailable ({exc}); current name only", file=sys.stderr)
            submissions = None
        names_by_ticker[ticker] = company_names(title, submissions)
        time.sleep(0.15)  # SEC fair access: well under 10 requests/second
    print(f"Company names for {len(names_by_ticker)}/{len(symbols)} symbols "
          f"({sum(len(v) > 1 for v in names_by_ticker.values())} with former names).")

    urls = args.window_url or _sample_window_urls(date.today())
    candidates_by_ticker: dict[str, set[str]] = defaultdict(set)
    scanned = 0
    for url in urls:
        print(f"Downloading {url} ...", flush=True)
        raw_zip = _download_zip(url, args.user_agent)
        if raw_zip is None:
            print("  not published (404) -- skipped", flush=True)
            continue
        scanned += 1
        seen: set[tuple[str, str]] = set()
        for issuer, cusip in _iter_infotable(raw_zip):
            if not cusip or (issuer, cusip) in seen:
                continue
            seen.add((issuer, cusip))
            for ticker, cores in names_by_ticker.items():
                if name_matches(issuer, cores):
                    candidates_by_ticker[ticker].add(cusip)
        print(f"  {len(seen):,} distinct issuer/CUSIP pairs; candidates so far: "
              f"{sum(len(v) for v in candidates_by_ticker.values())}", flush=True)
    if scanned == 0:
        print("FATAL: no 13F file could be downloaded", file=sys.stderr)
        return 1

    all_cusips = sorted({c for cs in candidates_by_ticker.values() for c in cs})
    print(f"Confirming {len(all_cusips)} candidate CUSIPs via OpenFIGI ...", flush=True)
    try:
        resolved, errors = _resolve_cusips_via_openfigi(all_cusips)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"FATAL: OpenFIGI confirmation call failed: {exc}", file=sys.stderr)
        return 1

    confirmed = confirm_cusips(candidates_by_ticker, resolved, _aliases_by_ticker())
    for ticker in symbols:
        if ticker in confirmed or ticker in reasons:
            continue
        cands = sorted(candidates_by_ticker.get(ticker, ()))
        if not cands:
            reasons[ticker] = f"no 13F issuer name matched {names_by_ticker.get(ticker)}"
        else:
            shown = ", ".join(f"{c}->{resolved.get(c) or errors.get(c, 'unresolved')}" for c in cands[:8])
            reasons[ticker] = f"{len(cands)} candidates, none resolved to it: {shown}"
    for ticker, cusips in confirmed.items():
        if len(cusips) > 1:
            print(f"  {ticker}: {len(cusips)} CUSIPs {cusips}")
    print(f"\nConfirmed: {len(confirmed)}/{len(symbols)} from {scanned} 13F files.")
    for ticker, reason in sorted(reasons.items()):
        print(f"  UNMATCHED {ticker}: {reason}")
    args.out.write_text(json.dumps(confirmed, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.out} ({len(confirmed)} entries).")
    return 0 if confirmed else 1


if __name__ == "__main__":
    sys.exit(main())
