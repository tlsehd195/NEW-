#!/usr/bin/env python3
"""One-shot reconnaissance for the "stockanalysis.com 무인증 백필"
backlog item (docs/PROJECT_STATUS.md, 2026-09-17 entry #1): this
session's own egress blocks `stockanalysis.com` outright (confirmed by
direct `curl`/WebFetch attempts, both returning EGRESS_BLOCKED), so
nothing about its real page/API shape for delisted stocks can be
verified from here. No public, documented API for delisted-stock price
history was found either (the closest reverse-engineered API docs
found via web search list only active-symbol endpoints -- `/api/
symbol/s/{ticker}/history`, `/api/quotes/s/{ticker}`, etc. -- with no
delisted-specific endpoint).

This script makes NO assumption about what is actually there. It just
requests a handful of plausible URLs (the public delisted-stocks list
page, and the one documented active-symbol history endpoint applied to
a real, well-known delisted ticker, as a test of whether it still
serves historical data for a symbol no longer listed) and prints the
real HTTP status + a bounded prefix of each response body -- nothing
more. The actual scraping/ingestion code this backlog item ultimately
needs should be written from what this reconnaissance run actually
shows, not from a guess.

Makes real network calls -- meant to run where egress is NOT blocked
(this project's GitHub Actions runners; unverified from this session).

Usage:
    python3 scripts/recon_stockanalysis_delisted.py
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MAX_BODY_PREVIEW_BYTES = 2000

_CANDIDATE_URLS = [
    "https://stockanalysis.com/list/delisted-stocks/",
    # LEH (Lehman Brothers) -- a real, long-delisted ticker, used only
    # to test whether the one DOCUMENTED active-symbol history endpoint
    # still serves anything for a symbol no longer listed.
    "https://stockanalysis.com/api/symbol/s/LEH/history?type=chart",
]


def _fetch(url: str) -> tuple[int, str] | tuple[None, str]:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(_MAX_BODY_PREVIEW_BYTES).decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(_MAX_BODY_PREVIEW_BYTES).decode("utf-8", errors="replace")
        return exc.code, body
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}"


def main() -> int:
    for url in _CANDIDATE_URLS:
        print(f"=== {url} ===")
        status, body = _fetch(url)
        print(f"status: {status}")
        print(f"body (first {_MAX_BODY_PREVIEW_BYTES} bytes):")
        print(body)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
