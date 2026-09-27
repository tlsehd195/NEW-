#!/usr/bin/env python3
"""One-shot reconnaissance: do Finnhub's and SiftingIO's real free-tier
APIs return usable historical daily OHLCV for a DELISTED/bankrupt US
stock, and how far back does the history actually go?

Context (2026-09-27): the account owner independently researched these
as Tiingo-alternative candidates for the survivorship-bias price
backfill (2000-2016-07-11 window, see ADR-0223/0224). Public docs
answer some of this (SiftingIO's own docs say a halted/delisted symbol
comes back "200 OK, shaped like an empty window" -- but that's a
general statement, not a real observed response for a specific
bankrupt ticker) and leave the rest unverified (Finnhub's pricing page
could not be read reliably in this session). This script makes the
real calls and just prints status + response body -- no parsing, no
provider wiring -- so the real answer replaces the guess.

Test symbols: LEH (Lehman Brothers, delisted/bankrupt 2008-09, this
project's own recurring bankruptcy test case -- see
survivorship-pit-universe-status memory) and AAPL (a control: a normal,
currently-listed stock, to tell "this provider doesn't have LEH" apart
from "this provider's free tier doesn't work for me at all").

Makes real network calls -- meant to run where egress is NOT blocked
(this project's GitHub Actions runners), same caveat every other
recon_*.py script in this directory documents.

Usage:
    FINNHUB_API_KEY=... SIFTINGIO_API_KEY=... \\
        python3 scripts/recon_new_survivorship_providers.py
"""

from __future__ import annotations

import gzip
import os
import sys
import time
import urllib.error
import urllib.request

_MAX_BODY_PREVIEW_BYTES = 2000

_BANKRUPT_SYMBOL = "LEH"
_CONTROL_SYMBOL = "AAPL"

# Old-window dates (inside the 2000-2016-07-11 research window this
# project actually needs) -- if a provider's free tier silently caps
# history to "the last N years," a query dated in 2007 is what exposes
# that, not a query dated today.
_OLD_START = "2007-01-01"
_OLD_END = "2008-12-31"


def _decode_body(raw: bytes, content_encoding: str | None) -> str:
    # SiftingIO always gzip-compresses its response body regardless of
    # what urllib's default Accept-Encoding negotiates (confirmed
    # 2026-09-27: the first real run against it returned raw gzip magic
    # bytes (1f 8b) as "body preview" garbage because urllib does not
    # auto-decompress -- unlike `requests`/browsers, `urllib.request`
    # never transparently decodes Content-Encoding).
    if content_encoding and "gzip" in content_encoding.lower():
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass  # not actually gzip despite the header -- fall through and decode as-is
    return raw.decode("utf-8", errors="replace")


def _fetch(url: str, headers: dict[str, str] | None = None) -> tuple[int | None, str]:
    """Returns (status, body_preview). Never raises -- a real network
    failure or an HTTP error status is itself part of the answer this
    script exists to observe, same discipline as
    `recon_corporate_action_providers.py::_fetch`. Decompresses a gzip
    Content-Encoding before truncating to the preview cap, so the cap
    applies to readable text, not opaque compressed bytes."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(_MAX_BODY_PREVIEW_BYTES * 4)  # compressed bytes decode to more text
            body = _decode_body(raw, response.headers.get("Content-Encoding"))
            return response.status, body[:_MAX_BODY_PREVIEW_BYTES]
    except urllib.error.HTTPError as exc:
        raw = exc.read(_MAX_BODY_PREVIEW_BYTES * 4) if exc.fp is not None else b""
        body = _decode_body(raw, exc.headers.get("Content-Encoding") if exc.headers else None)
        return exc.code, body[:_MAX_BODY_PREVIEW_BYTES]
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}"


def _run_finnhub(api_key: str) -> None:
    # https://finnhub.io/docs/api/stock-candles -- resolution "D" (daily),
    # from/to are Unix seconds. 2007-01-01 -> 2008-12-31.
    from_ts = 1167609600  # 2007-01-01 UTC
    to_ts = 1230508800  # 2008-12-31 UTC
    for label, symbol in (("Finnhub candle (LEH, bankrupt, 2007-2008)", _BANKRUPT_SYMBOL), ("Finnhub candle (AAPL, control, 2007-2008)", _CONTROL_SYMBOL)):
        url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={from_ts}&to={to_ts}&token={api_key}"
        print(f"=== {label} ===")
        status, body = _fetch(url)
        print(f"status: {status}")
        print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
        print()
        time.sleep(1.1)
    # Control check: is the key itself valid, or is /stock/candle
    # specifically gated to a paid plan? /quote is Finnhub's own
    # documented always-free real-time-quote endpoint -- if THIS also
    # 403s, the key/account itself is the problem, not just candles.
    quote_url = f"https://finnhub.io/api/v1/quote?symbol={_CONTROL_SYMBOL}&token={api_key}"
    print("=== Finnhub quote (AAPL, control endpoint -- documented free) ===")
    status, body = _fetch(quote_url)
    print(f"status: {status}")
    print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
    print()


def _run_siftingio(api_key: str) -> None:
    headers = {"X-API-Key": api_key, "Accept-Encoding": "gzip"}
    for label, symbol in (("SiftingIO bars (LEH, bankrupt, 2007-2008)", _BANKRUPT_SYMBOL), ("SiftingIO bars (AAPL, control, 2007-2008)", _CONTROL_SYMBOL)):
        url = f"https://api.sifting.io/v1/hist/stocks/{symbol}/bars?start={_OLD_START}&end={_OLD_END}&interval=1d"
        print(f"=== {label} ===")
        status, body = _fetch(url, headers=headers)
        print(f"status: {status}")
        print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
        print()
        time.sleep(1.1)


def main() -> int:
    finnhub_key = os.environ.get("FINNHUB_API_KEY")
    if finnhub_key:
        _run_finnhub(finnhub_key)
    else:
        print("=== FINNHUB_API_KEY not set -- skipping ===\n")

    siftingio_key = os.environ.get("SIFTINGIO_API_KEY")
    if siftingio_key:
        _run_siftingio(siftingio_key)
    else:
        print("=== SIFTINGIO_API_KEY not set -- skipping ===\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
