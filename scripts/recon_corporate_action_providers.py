#!/usr/bin/env python3
"""One-shot reconnaissance: does Twelve Data or Alpha Vantage's real
free-tier API actually return corporate-action (split/dividend) data?

Context (2026-09-25): `scripts/ingest_real_market_data.py` fetches
corporate actions from Tiingo ONLY -- `TwelveDataDataProvider`/
`AlphaVantageDataProvider` both declare
`supports_corporate_actions=False` in their own `metadata()`, and their
module docstrings say this was "deliberately" not implemented, without
stating whether the underlying Twelve Data/Alpha Vantage APIs actually
lack this data or whether it simply was never wired in. Because
corporate actions have no fallback, a day where Tiingo's own hourly
request budget (ADR-0160, shared with price-bar fetching) is exhausted
before corporate-action collection runs fails corporate actions for
EVERY requested symbol, which this project's own exit-code gate treats
as fatal for the whole ingestion run (see run #44, 2026-09-25).

Public web search found real product pages for both providers'
corporate-action data (Twelve Data's `/dividends`/`/splits` endpoints;
Alpha Vantage's `SPLITS`/`DIVIDENDS` functions), but could not confirm
free-tier availability with real, Tier-1 evidence -- this project's own
egress proxy blocks both `twelvedata.com` and `alphavantage.co`
directly from an interactive session (same reachability gap
`recon_kenneth_french_library.py` already worked around by running from
a GitHub Actions runner instead). This script makes the real calls,
using the SAME already-configured `TWELVEDATA_API_KEY`/
`ALPHAVANTAGE_API_KEY` secrets production ingestion already uses, and
just prints the real HTTP status + response body -- no parsing, no
provider wiring, no assumption about the result. What to build (if
anything) is decided from what this recon actually shows.

Test symbols: GE (this project's own chosen `REVERSE_SPLIT` edge case,
docs/operations/MARKET-DATA-PROVIDER.md -- reverse split effective
2021-08-02) for splits, AAPL (regular dividend payer, well past its
2020-08-31 forward split) for dividends.

Makes real network calls -- meant to run where egress is NOT blocked
(this project's GitHub Actions runners; unverified from an interactive
session, same caveat `recon_kenneth_french_library.py` already
documents).

Usage:
    TWELVEDATA_API_KEY=... ALPHAVANTAGE_API_KEY=... \\
        python3 scripts/recon_corporate_action_providers.py
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

_MAX_BODY_PREVIEW_BYTES = 2000

_SPLIT_TEST_SYMBOL = "GE"
_DIVIDEND_TEST_SYMBOL = "AAPL"

# (label, url-builder). Each takes the resolved API key and returns a
# full URL -- keys are never logged or included in printed output
# beyond being embedded in a URL this script itself constructs and
# immediately discards.
_TWELVEDATA_CANDIDATES = [
    ("Twelve Data /dividends", lambda key: f"https://api.twelvedata.com/dividends?symbol={_DIVIDEND_TEST_SYMBOL}&apikey={key}"),
    ("Twelve Data /splits", lambda key: f"https://api.twelvedata.com/splits?symbol={_SPLIT_TEST_SYMBOL}&apikey={key}"),
]
_ALPHAVANTAGE_CANDIDATES = [
    ("Alpha Vantage DIVIDENDS", lambda key: f"https://www.alphavantage.co/query?function=DIVIDENDS&symbol={_DIVIDEND_TEST_SYMBOL}&apikey={key}"),
    ("Alpha Vantage SPLITS", lambda key: f"https://www.alphavantage.co/query?function=SPLITS&symbol={_SPLIT_TEST_SYMBOL}&apikey={key}"),
]


def _fetch(url: str) -> tuple[int | None, str]:
    """Returns (status, body_preview). Never raises -- a real network
    failure or an HTTP error status is itself part of the answer this
    script exists to observe, same discipline as
    `recon_kenneth_french_library.py::_fetch`."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(_MAX_BODY_PREVIEW_BYTES).decode("utf-8", errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(_MAX_BODY_PREVIEW_BYTES).decode("utf-8", errors="replace") if exc.fp is not None else ""
        return exc.code, body
    except urllib.error.URLError as exc:
        return None, f"URLError: {exc.reason}"


def main() -> int:
    checks = [
        ("TWELVEDATA_API_KEY", _TWELVEDATA_CANDIDATES),
        ("ALPHAVANTAGE_API_KEY", _ALPHAVANTAGE_CANDIDATES),
    ]
    for env_var, candidates in checks:
        api_key = os.environ.get(env_var)
        if not api_key:
            print(f"=== {env_var} not set -- skipping its candidates ===\n")
            continue
        for label, build_url in candidates:
            url = build_url(api_key)
            print(f"=== {label} ===")
            status, body = _fetch(url)
            print(f"status: {status}")
            print(f"body preview (cap {_MAX_BODY_PREVIEW_BYTES} bytes): {body}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
