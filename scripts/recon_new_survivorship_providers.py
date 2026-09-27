#!/usr/bin/env python3
"""One-shot reconnaissance: do Finnhub's, SiftingIO's, and Quotient's
(RapidAPI) real free-tier APIs return usable historical daily OHLCV for
a DELISTED/bankrupt US stock, and how far back does the history
actually go?

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

Quotient's real endpoint (`GET /equity/daily?symbol=...&from=...&to=...
&adjust=...`, host `quotient.p.rapidapi.com`, auth via
`x-rapidapi-key`/`x-rapidapi-host` headers) was obtained from the
account owner's own RapidAPI console (2026-09-27) after the public
RapidAPI page itself could not be read reliably in this session
(JS-rendered) -- the account owner also pasted a real key into the
project chat by mistake while getting this, which they were told to
regenerate; this script only ever reads it from the environment.

Usage:
    FINNHUB_API_KEY=... SIFTINGIO_API_KEY=... QUOTIENT_API_KEY=... \\
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


def _rate_limit_headers(headers) -> dict[str, str]:
    if headers is None:
        return {}
    return {k: v for k, v in headers.items() if "rate" in k.lower() or "quota" in k.lower() or "limit" in k.lower()}


def _fetch(url: str, headers: dict[str, str] | None = None) -> tuple[int | None, str, dict[str, str]]:
    """Returns (status, body_preview, rate_limit_headers). Never raises --
    a real network failure or an HTTP error status is itself part of the
    answer this script exists to observe, same discipline as
    `recon_corporate_action_providers.py::_fetch`. Decompresses a gzip
    Content-Encoding before truncating to the preview cap, so the cap
    applies to readable text, not opaque compressed bytes. Also surfaces
    any response header whose name mentions rate/quota/limit, since a
    provider's real request budget is exactly what a one-shot recon
    can't see from public docs alone."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            # Read the WHOLE body -- a partial read of a gzip stream is
            # not itself valid gzip (confirmed 2026-09-27: truncating to
            # a fixed byte cap before decompressing raised
            # "Compressed file ended before the end-of-stream marker").
            # This is a one-shot recon script fetching a handful of
            # single-day bar responses, not a bulk job, so an unbounded
            # read here is bounded in practice by what the API returns.
            raw = response.read()
            body = _decode_body(raw, response.headers.get("Content-Encoding"))
            return response.status, body[:_MAX_BODY_PREVIEW_BYTES], _rate_limit_headers(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp is not None else b""
        body = _decode_body(raw, exc.headers.get("Content-Encoding") if exc.headers else None)
        return exc.code, body[:_MAX_BODY_PREVIEW_BYTES], _rate_limit_headers(exc.headers)
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}", {}


def _run_finnhub(api_key: str) -> None:
    # https://finnhub.io/docs/api/stock-candles -- resolution "D" (daily),
    # from/to are Unix seconds. 2007-01-01 -> 2008-12-31.
    from_ts = 1167609600  # 2007-01-01 UTC
    to_ts = 1230508800  # 2008-12-31 UTC
    for label, symbol in (("Finnhub candle (LEH, bankrupt, 2007-2008)", _BANKRUPT_SYMBOL), ("Finnhub candle (AAPL, control, 2007-2008)", _CONTROL_SYMBOL)):
        url = f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}&resolution=D&from={from_ts}&to={to_ts}&token={api_key}"
        print(f"=== {label} ===")
        status, body, rl = _fetch(url)
        print(f"status: {status}")
        print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
        if rl:
            print(f"rate-limit headers: {rl}")
        print()
        time.sleep(1.1)
    # Control check: is the key itself valid, or is /stock/candle
    # specifically gated to a paid plan? /quote is Finnhub's own
    # documented always-free real-time-quote endpoint -- if THIS also
    # 403s, the key/account itself is the problem, not just candles.
    quote_url = f"https://finnhub.io/api/v1/quote?symbol={_CONTROL_SYMBOL}&token={api_key}"
    print("=== Finnhub quote (AAPL, control endpoint -- documented free) ===")
    status, body, rl = _fetch(quote_url)
    print(f"status: {status}")
    print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
    if rl:
        print(f"rate-limit headers: {rl}")
    print()


# Deep pass (2026-09-27, after SiftingIO alone survived the first-pass
# check): the account owner's own bankruptcy test set, reused from this
# project's existing survivorship-pit-universe-status memory --
# ENRN/WCOM predate LEH's 2008 crash and probe the OLDER end of the
# 2000-2016-07-11 research window, since a provider's free tier could
# plausibly cap history at "the last N years from whenever it was
# built" rather than a fixed calendar date.
_DEEP_BANKRUPTCY_CASES = (
    ("ENRN", "2000-06-01", "2001-12-31"),  # Enron, filed 2001-12-02
    ("WCOM", "2000-06-01", "2002-07-31"),  # WorldCom, filed 2002-07-21
    ("WAMUQ", _OLD_START, _OLD_END),  # Washington Mutual, seized 2008-09-25
    ("BSC", _OLD_START, _OLD_END),  # Bear Stearns, JPM rescue 2008-03
)


def _run_siftingio(api_key: str) -> None:
    headers = {"X-API-Key": api_key, "Accept-Encoding": "gzip"}
    for label, symbol in (("SiftingIO bars (LEH, bankrupt, 2007-2008)", _BANKRUPT_SYMBOL), ("SiftingIO bars (AAPL, control, 2007-2008)", _CONTROL_SYMBOL)):
        url = f"https://api.sifting.io/v1/hist/stocks/{symbol}/bars?start={_OLD_START}&end={_OLD_END}&interval=1d"
        print(f"=== {label} ===")
        status, body, rl = _fetch(url, headers=headers)
        print(f"status: {status}")
        print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
        if rl:
            print(f"rate-limit headers: {rl}")
        print()
        time.sleep(1.1)

    print("--- SiftingIO deep pass: more bankruptcies, older window ---\n")
    for symbol, start, end in _DEEP_BANKRUPTCY_CASES:
        url = f"https://api.sifting.io/v1/hist/stocks/{symbol}/bars?start={start}&end={end}&interval=1d"
        print(f"=== SiftingIO bars ({symbol}, {start}..{end}) ===")
        status, body, rl = _fetch(url, headers=headers)
        print(f"status: {status}")
        print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
        if rl:
            print(f"rate-limit headers: {rl}")
        print()
        time.sleep(1.1)
    # AAPL at the research window's earliest edge (2000-01) -- separate
    # from the bankruptcy set, this is purely a "does free-tier history
    # go back to 2000 at all" check, on a symbol guaranteed to have real
    # data if the provider's history depth allows it.
    url = f"https://api.sifting.io/v1/hist/stocks/{_CONTROL_SYMBOL}/bars?start=2000-01-01&end=2000-03-31&interval=1d"
    print(f"=== SiftingIO bars (AAPL, research-window earliest edge, 2000-01..2000-03) ===")
    status, body, rl = _fetch(url, headers=headers)
    print(f"status: {status}")
    print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
    if rl:
        print(f"rate-limit headers: {rl}")
    print()


def _run_quotient(api_key: str) -> None:
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "quotient.p.rapidapi.com"}
    for label, symbol in (("Quotient equity/daily (LEH, bankrupt, 2007-2008)", _BANKRUPT_SYMBOL), ("Quotient equity/daily (AAPL, control, 2007-2008)", _CONTROL_SYMBOL)):
        url = f"https://quotient.p.rapidapi.com/equity/daily?symbol={symbol}&from={_OLD_START}&to={_OLD_END}&adjust=false"
        print(f"=== {label} ===")
        status, body, rl = _fetch(url, headers=headers)
        print(f"status: {status}")
        print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
        if rl:
            print(f"rate-limit headers: {rl}")
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

    quotient_key = os.environ.get("QUOTIENT_API_KEY")
    if quotient_key:
        _run_quotient(quotient_key)
    else:
        print("=== QUOTIENT_API_KEY not set -- skipping ===\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
