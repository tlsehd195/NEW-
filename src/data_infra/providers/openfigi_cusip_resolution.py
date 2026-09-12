"""Resolves CUSIPs (SEC Form 13F's own security identifier, which this
project's `SecurityMaster` has never carried) to a real US-listed
ticker via OpenFIGI's free, no-API-key-required `/v3/mapping` endpoint
-- closing the second gap `data_infra.institutional_holding_models`'s
own module docstring names ("SEC's own 13F data is keyed by CUSIP, and
this project's `SecurityMaster` has never carried a CUSIP field").

**Real, verified request/response shape** (this session; the account
owner tested this directly, never guessed from documentation alone):

    POST https://api.openfigi.com/v3/mapping
    Content-Type: application/json
    [{"idType":"ID_CUSIP","idValue":"02005N100","exchCode":"US"}]

    -> [{"data":[{"figi":"BBG000BC2R71","name":"ALLY FINANCIAL INC",
                  "ticker":"ALLY","exchCode":"US", ...}]}]

**Without `exchCode: "US"` in the request, OpenFIGI returns every
listing worldwide** -- confirmed directly: the same CUSIP without that
filter returned 100+ entries (ADRs, currency-hedged share classes,
foreign exchange listings like `ALLYEUR`/`ALLYGBP`/`GMZ`). Adding
`exchCode: "US"` to the request itself (not client-side filtering
afterward) is what collapses the real response down to exactly the one
real US-primary-listing ticker -- confirmed with the identical real
CUSIP, both with and without the filter, in the same session.

**A CUSIP OpenFIGI cannot resolve returns `{"data":[]}` or
`{"error": "..."}` for that position in the response array** (OpenFIGI's
documented shape for a request batch) -- `parse_mapping_response`
reports that CUSIP's ticker as `None`, never fabricates one, and never
lets one failed entry corrupt the others' real results (`zip` pairs
each response entry back to its original CUSIP by request-array
position, the same order-preserving contract OpenFIGI's own docs
specify)."""

from __future__ import annotations

from typing import Optional, Sequence

_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
_BATCH_LIMIT_WITHOUT_API_KEY = 100


def build_mapping_request(cusips: Sequence[str]) -> list[dict]:
    """One request-body entry per CUSIP, in the SAME order they must be
    passed back to `parse_mapping_response` (OpenFIGI's response array
    is positional, not keyed by the input value). Raises `ValueError`
    if more than `_BATCH_LIMIT_WITHOUT_API_KEY` CUSIPs are given --
    never silently truncates a caller's real list."""
    if len(cusips) > _BATCH_LIMIT_WITHOUT_API_KEY:
        raise ValueError(
            f"{len(cusips)} CUSIPs given, but OpenFIGI's no-API-key tier accepts at most "
            f"{_BATCH_LIMIT_WITHOUT_API_KEY} per request -- split into batches"
        )
    return [{"idType": "ID_CUSIP", "idValue": cusip, "exchCode": "US"} for cusip in cusips]


def parse_mapping_response(cusips: Sequence[str], response_json: Sequence[dict]) -> dict[str, Optional[str]]:
    """`cusips` must be the exact same list (same order) passed to
    `build_mapping_request`. Returns `{cusip: ticker_or_None}` -- `None`
    for a CUSIP OpenFIGI could not resolve to a US-listed ticker
    (either `{"data":[]}` or an `{"error": ...}` entry), never a
    fabricated or guessed value. When multiple US listings are somehow
    still returned for one CUSIP, the FIRST is used (OpenFIGI's own
    documented behavior lists the primary/composite listing first)."""
    if len(cusips) != len(response_json):
        raise ValueError(f"cusips ({len(cusips)}) and response_json ({len(response_json)}) must be the same length and order")
    result: dict[str, Optional[str]] = {}
    for cusip, entry in zip(cusips, response_json):
        data = entry.get("data")
        result[cusip] = data[0]["ticker"] if data else None
    return result
