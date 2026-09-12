"""Pure (no-network) helpers for turning a real Financial Modeling Prep
(FMP) `stable/historical-price-eod/full` API response into this
project's `LocalFileDataProvider` CSV schema (`data_infra.providers.
file_import`), and for classifying whether a covered ticker's real
data plausibly reflects a genuine delisting (vs. simply leaving an
index while remaining listed elsewhere) -- the identical concept
`check_wiki_prices_delisted_coverage.py`/ADR-0126 established for the
Quandl WIKI Prices source, applied here to a second, independently
real, CONTINUOUSLY UPDATED source that covers the 2018+ window WIKI
Prices cannot (ADR-0128).

**Real, verified response shape** (this session; fetched by the
account owner from `https://financialmodelingprep.com/stable/
historical-price-eod/full?symbol=ATVI&apikey=...`, never guessed from
documentation alone):

    {"symbol": "ATVI", "date": "2023-10-20", "open": 94.42,
     "high": 94.42, "low": 94.42, "close": 94.42, "volume": 0,
     "change": 0, "changePercent": 0, "vwap": 94.42}

**Confirmed dummy-tail artifact, same pattern as ADR-0126's WIKI
Prices finding**: after ATVI's real last trade (2023-10-12,
volume=7,323,451, close=$94.42 -- matching Microsoft's real
acquisition close date of 2023-10-13 almost exactly), FMP's API keeps
returning IDENTICAL `open=high=low=close=94.42, volume=0` rows through
the query's `to` date. This module drops every `volume == 0` row for
the same reason ADR-0126 does -- a genuine zero-volume day is not
realistic for any of this project's research-universe-scale
securities, and the artifact's own shape (a constant price held
forever, starting immediately after the last real trade) is
unambiguous.

**No `adjusted_close`/`adjusted_high`/`adjusted_low` fields exist in
this response at all** -- unlike Quandl WIKI Prices, this FMP endpoint
returns `vwap`/`change`/`changePercent` instead, none of which is a
split-adjusted price. This module never fabricates those columns; the
converted row leaves them blank, the same discipline `StooqDataProvider`
already applies for a source with no adjusted-price field of its own.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

_GENUINE_DELISTING_GAP_DAYS = 90


def is_dummy_row(row: dict) -> bool:
    """True for FMP's confirmed zero-volume flat-fill artifact -- never
    a guess, the same disciplined `volume == 0` filter ADR-0126
    established for a different source, applied here to this one."""
    return float(row.get("volume", 0)) == 0.0


def real_rows(fmp_response: Sequence[dict]) -> list[dict]:
    """Every row from a real FMP `historical-price-eod/full` response
    with the confirmed dummy tail dropped, sorted ascending by date."""
    return sorted((r for r in fmp_response if not is_dummy_row(r)), key=lambda r: r["date"])


def to_file_import_row(fmp_row: dict) -> dict:
    """Maps one real (non-dummy) FMP row to the schema `data_infra.
    providers.file_import.LocalFileDataProvider` expects. No
    `adj_close`/`adj_high`/`adj_low` -- this response has no
    split-adjusted fields to map (see module docstring)."""
    return {
        "date": fmp_row["date"],
        "open": fmp_row["open"],
        "high": fmp_row["high"],
        "low": fmp_row["low"],
        "close": fmp_row["close"],
        "volume": fmp_row["volume"],
        "adj_close": "",
        "adj_high": "",
        "adj_low": "",
    }


def days_from_nearest_end_date(last_real_date: date, end_dates: Sequence[date]) -> int:
    """Minimum gap in days between `last_real_date` and any of
    `end_dates` -- identical concept to `check_wiki_prices_delisted_
    coverage.py`'s own function (ADR-0126 Decision 5), applied here to
    this second source so both sources classify genuine delistings by
    the same rule."""
    return min(abs((last_real_date - d).days) for d in end_dates)


def is_likely_genuine_delisting(last_real_date: date, end_dates: Sequence[date]) -> bool:
    """`True` when the real data's own last trading date lands within
    `_GENUINE_DELISTING_GAP_DAYS` of some recorded S&P 500 removal
    date for the ticker -- a disclosed heuristic threshold, not a
    certainty, matching the exact `ATVI`/`DELL` pattern of a near-zero
    day gap."""
    return days_from_nearest_end_date(last_real_date, end_dates) <= _GENUINE_DELISTING_GAP_DAYS
