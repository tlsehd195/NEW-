#!/usr/bin/env python3
"""One-shot reconnaissance: do Twelve Data / Alpha Vantage free keys serve
prices for S&P 500 names that were removed, went bankrupt, or that Tiingo
returned nothing for (ADR-0224)? Also checks whether Twelve Data prices
are split-adjusted, since its free plan has no /splits (ADR-0203).

About ten calls in total. Keys come from the environment and are never
printed. Runs on a GitHub Actions runner because both hosts are blocked
from interactive sessions.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TWELVE = "https://api.twelvedata.com/time_series"
ALPHA = "https://www.alphavantage.co/query"

TWELVE_PROBES = [
    ("AAPL split week 2014 (adjusted?)", {"symbol": "AAPL", "start_date": "2014-06-05", "end_date": "2014-06-11"}),
    ("LEH 2008 (bankrupt)", {"symbol": "LEH", "start_date": "2008-01-02", "end_date": "2008-01-08"}),
    ("WM 2007 (Washington Mutual)", {"symbol": "WM", "start_date": "2007-01-03", "end_date": "2007-01-09"}),
    ("BSC 2007 (Bear Stearns)", {"symbol": "BSC", "start_date": "2007-01-03", "end_date": "2007-01-09"}),
    ("CFC 2007 (Countrywide)", {"symbol": "CFC", "start_date": "2007-01-03", "end_date": "2007-01-09"}),
    ("MDP 2020 (Meredith; Tiingo returned 0 bars)", {"symbol": "MDP", "start_date": "2020-01-02", "end_date": "2020-01-08"}),
    ("XLNX 2021 (acquired 2022)", {"symbol": "XLNX", "start_date": "2021-01-04", "end_date": "2021-01-08"}),
    ("AAPL 2000 (history depth)", {"symbol": "AAPL", "start_date": "2000-01-03", "end_date": "2000-01-07"}),
]
ALPHA_PROBES = [
    ("LEH daily (bankrupt)", {"function": "TIME_SERIES_DAILY", "symbol": "LEH", "outputsize": "compact"}),
    ("XLNX daily (acquired 2022)", {"function": "TIME_SERIES_DAILY", "symbol": "XLNX", "outputsize": "compact"}),
]


def _get(url: str, params: dict, key_name: str, key: str) -> tuple[int, str]:
    query = urllib.parse.urlencode({**params, key_name: key})
    try:
        with urllib.request.urlopen(f"{url}?{query}", timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace").replace(key, "***")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace").replace(key, "***")


def main() -> int:
    twelve_key = os.environ.get("TWELVEDATA_API_KEY", "")
    alpha_key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    for label, params in TWELVE_PROBES:
        status, body = _get(TWELVE, {**params, "interval": "1day", "order": "ASC"}, "apikey", twelve_key)
        print(f"== Twelve Data {label}: HTTP {status}\n{body[:900]}\n", flush=True)
        time.sleep(8)  # free plan: 8 requests a minute
    for label, params in ALPHA_PROBES:
        status, body = _get(ALPHA, params, "apikey", alpha_key)
        print(f"== Alpha Vantage {label}: HTTP {status}\n{body[:600]}\n", flush=True)
        time.sleep(2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
