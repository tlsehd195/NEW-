"""One-shot probe: why did Tiingo reject X, XEC and XL on 2026-09-28?

The extension run (ADR-0224) got a non-array body for those symbols
after 297 of 432 names, while the account page still showed hourly and
daily requests left. The free plan's third limit, 500 unique symbols a
month, is not on that page. This asks for a few days of prices for one
symbol already fetched this month (AAPL) and for the three that failed,
and prints each status and the start of each body, so the reason comes
from Tiingo itself.

Costs at most three new symbols. Sends the key in a header, never in the
URL, and prints nothing account-related.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_SYMBOLS = ("AAPL", "XL", "X", "XEC")


def _get(symbol: str, key: str) -> tuple[int, str]:
    url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices?startDate=2016-01-04&endDate=2016-01-08&format=json"
    request = urllib.request.Request(url, headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def main() -> int:
    key = os.environ.get("MARKET_DATA_API_KEY", "")
    if not key:
        print("MARKET_DATA_API_KEY is not set")
        return 1
    for symbol in _SYMBOLS:
        status, text = _get(symbol, key)
        try:
            body = json.loads(text)
        except ValueError:
            body = None
        shape = f"array of {len(body)} rows" if isinstance(body, list) else type(body).__name__
        print(f"{symbol}: HTTP {status}, {shape}: {text[:300].replace(key, '***')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
