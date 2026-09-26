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
from data_infra.providers.openfigi_cusip_resolution import build_mapping_request, parse_mapping_response  # noqa: E402
from data_infra.providers.sec_13f_bulk_dataset import generate_filing_windows  # noqa: E402
from data_infra.providers.sec_edgar import SecEdgarFundamentalsProvider, resolve_company_title  # noqa: E402
from data_infra.providers.sec_edgar_config import SecEdgarConfig  # noqa: E402
from data_infra.providers.sec_edgar_transport import SecEdgarHttpTransport  # noqa: E402
from data_infra.universe import PILOT_UNIVERSE_V1, RESEARCH_UNIVERSE_STAGE4  # noqa: E402

_WWW_HOST = "https://www.sec.gov"
_UNIVERSES = {"PILOT_UNIVERSE": PILOT_UNIVERSE_V1, "RESEARCH_UNIVERSE": RESEARCH_UNIVERSE_STAGE4}
_OPENFIGI_BATCH_SIZE = 10  # ADR-0131's own real, confirmed no-API-key limit

_TRAILING_TOKENS_TO_STRIP = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED",
    "LLC", "PLC", "GROUP", "HOLDINGS", "HOLDING", "COM",
}


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum() or ch.isspace()).strip()


def _core_name(title: str) -> str:
    """Strips a leading "THE " and trailing corporate-suffix tokens
    (INC/CORP/CO/...) from an already-`_normalize`d real company title
    -- real 13F `NAMEOFISSUER` text varies in exactly these suffixes
    (`ADR-0131`'s own real Berkshire filing observation), so matching
    on the stripped core is deliberately more permissive than an exact
    title match. Never trusted alone -- every candidate this produces
    still goes through the real OpenFIGI CUSIP->ticker confirmation
    below before being accepted."""
    text = _normalize(title)
    if text.startswith("THE "):
        text = text[4:]
    tokens = text.split()
    while tokens and tokens[-1] in _TRAILING_TOKENS_TO_STRIP:
        tokens.pop()
    return " ".join(tokens)


def _download_zip(url: str) -> Optional[bytes]:
    """Returns `None` on a real HTTP 404 (this window has not been
    published yet -- a real, confirmed lag exists between a window's
    own end date and SEC actually publishing it, found the hard way:
    2026-09-26, `01jun2026-31aug2026` -- ended 2026-08-31, weeks
    before this run -- still 404'd). Any other error propagates."""
    req = urllib.request.Request(url, headers={"User-Agent": "NEW- sdh08060900@gmail.com"})
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _read_tsv_from_zip(zf: zipfile.ZipFile, filename_upper: str) -> list[dict]:
    candidates = [n for n in zf.namelist() if Path(n).name.upper() == filename_upper]
    if not candidates:
        raise FileNotFoundError(f"{filename_upper} not found in archive; real entries: {zf.namelist()}")
    with zf.open(candidates[0]) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        return list(csv.DictReader(text, delimiter="\t"))


def _resolve_cusips_via_openfigi(cusips: list[str]) -> dict[str, Optional[str]]:
    resolved: dict[str, Optional[str]] = {}
    for i in range(0, len(cusips), _OPENFIGI_BATCH_SIZE):
        batch = cusips[i : i + _OPENFIGI_BATCH_SIZE]
        body = json.dumps(build_mapping_request(batch)).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openfigi.com/v3/mapping", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            response_json = json.loads(response.read().decode("utf-8"))
        resolved.update(parse_mapping_response(batch, response_json))
        if i + _OPENFIGI_BATCH_SIZE < len(cusips):
            time.sleep(2.5)  # real confirmed cap is 25 req/60s -- stay well under it
    return resolved


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-agent", required=True, help="SEC fair-access contact string (real, reachable identifier)")
    parser.add_argument("--universe", choices=sorted(_UNIVERSES), default="RESEARCH_UNIVERSE")
    parser.add_argument("--symbols", nargs="+", default=None, help="Explicit symbol list, overriding --universe entirely")
    parser.add_argument("--window-url", default=None, help="Real SEC 13F bulk data set ZIP URL to name-match against (default: the most recently completed real window)")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the real {ticker: cusip} JSON map")
    args = parser.parse_args(argv)

    symbols = list(args.symbols) if args.symbols is not None else list(_UNIVERSES[args.universe].symbol_ids)

    config = SecEdgarConfig(user_agent=args.user_agent)
    www_transport = SecEdgarHttpTransport(_WWW_HOST, user_agent=config.user_agent)
    provider = SecEdgarFundamentalsProvider(config, www_transport)

    print(f"Fetching SEC EDGAR ticker map from {_WWW_HOST} (a multi-MB file, may take a moment)...", flush=True)
    try:
        ticker_map = provider.fetch_ticker_map(www_transport)
    except (TransientProviderError, PermanentProviderError) as exc:
        print(f"FATAL: could not fetch SEC EDGAR ticker map: {exc}", file=sys.stderr)
        return 1
    print(f"Ticker map fetched ({len(ticker_map)} entries).")

    core_name_by_ticker: dict[str, str] = {}
    for ticker in symbols:
        title = resolve_company_title(ticker, ticker_map)
        if title is None:
            print(f"  WARNING: {ticker} not found in SEC EDGAR ticker map -- skipped", file=sys.stderr)
            continue
        core_name_by_ticker[ticker] = _core_name(title)
    print(f"Resolved real company names for {len(core_name_by_ticker)}/{len(symbols)} symbols.")

    if args.window_url is not None:
        candidate_urls = [args.window_url]
    else:
        # Try the most recently COMPLETED real windows, NEWEST first,
        # falling back to an earlier one on a real 404 -- SEC publishes
        # a window's real data set with a real, confirmed lag AFTER
        # the window's own end date (found the hard way, 2026-09-26:
        # `01jun2026-31aug2026` had already ended weeks earlier and
        # still 404'd), so "ended before today" alone does not mean
        # "published." Tries the last 8 completed windows (~2 years)
        # before giving up -- an explicit --window-url always wins.
        today = date.today()
        windows = generate_filing_windows(today.year - 2, today - timedelta(days=1))
        completed = [w for w in windows if w.end < today]
        if not completed:
            print("FATAL: could not determine a completed real filing window automatically -- pass --window-url explicitly", file=sys.stderr)
            return 1
        candidate_urls = [w.url for w in reversed(completed[-8:])]

    raw_zip: Optional[bytes] = None
    window_url: Optional[str] = None
    for candidate_url in candidate_urls:
        print(f"Downloading {candidate_url} ...", flush=True)
        try:
            raw_zip = _download_zip(candidate_url)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"FATAL: could not download the bulk data set: {exc}", file=sys.stderr)
            return 1
        if raw_zip is not None:
            window_url = candidate_url
            break
        print(f"  Not published by SEC yet (real 404) -- trying an earlier window.", file=sys.stderr)

    if raw_zip is None or window_url is None:
        print(f"FATAL: none of the {len(candidate_urls)} most recent candidate windows are published yet -- pass --window-url explicitly for a known-good one", file=sys.stderr)
        return 1
    print(f"Downloaded {len(raw_zip):,} bytes from {window_url}.")

    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
        infotable = _read_tsv_from_zip(zf, "INFOTABLE.TSV")
    print(f"INFOTABLE.tsv: {len(infotable)} rows.")

    candidates_by_ticker: dict[str, set[str]] = defaultdict(set)
    for row in infotable:
        name = _normalize(row.get("NAMEOFISSUER", ""))
        cusip = row.get("CUSIP", "").strip()
        if not cusip:
            continue
        for ticker, core_name in core_name_by_ticker.items():
            if core_name and core_name in name:
                candidates_by_ticker[ticker].add(cusip)

    all_candidate_cusips = sorted({c for cusips in candidates_by_ticker.values() for c in cusips})
    print(f"Candidate CUSIPs found by name-matching: {len(all_candidate_cusips)} distinct across {len(candidates_by_ticker)} symbols.")
    if not all_candidate_cusips:
        print("FATAL: zero candidate CUSIPs found for any symbol -- name-matching found nothing.", file=sys.stderr)
        return 1

    print("Confirming candidates via the real, verified OpenFIGI CUSIP->ticker direction...", flush=True)
    try:
        resolved = _resolve_cusips_via_openfigi(all_candidate_cusips)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"FATAL: OpenFIGI confirmation call failed: {exc}", file=sys.stderr)
        return 1

    confirmed: dict[str, str] = {}
    ambiguous: list[str] = []
    for ticker, candidate_cusips in candidates_by_ticker.items():
        matches = [c for c in candidate_cusips if resolved.get(c) == ticker]
        if len(matches) == 1:
            confirmed[ticker] = matches[0]
        elif len(matches) > 1:
            ambiguous.append(ticker)
            print(f"  WARNING: {ticker} has multiple OpenFIGI-confirmed CUSIPs -- excluded, needs manual review: {matches}", file=sys.stderr)

    unmatched = sorted(set(symbols) - set(confirmed))
    print(f"\nConfirmed: {len(confirmed)}/{len(symbols)}. Unmatched/excluded: {unmatched}")

    args.out.write_text(json.dumps(confirmed, indent=2, sort_keys=True))
    print(f"Wrote {args.out} ({len(confirmed)} entries).")
    return 0 if confirmed else 1


if __name__ == "__main__":
    sys.exit(main())
