"""TwelveDataHttpTransport: the one real, network-capable component in
`data_infra.providers.twelvedata`. stdlib-only (`urllib.request`), no
new dependency added to `pyproject.toml` -- mirrors
`data_infra.providers.tiingo_transport.TiingoHttpTransport`'s identical
pattern.

Never constructed by anything in this repository's own tests, backtests,
or CI (no automated test in this repository may ever call the real
Twelve Data API). `tests/data_infra/test_twelvedata_transport.py` is the
only test file allowed to import this module, and it stubs
`urllib.request.urlopen` rather than reaching the network.

**Only handles real HTTP-level failures here** (5xx/429/401/403/404) --
Twelve Data's own quota/rate-limit errors are reported as HTTP 200 with
an error object in the JSON body (`{"code": 429, "status": "error",
...}`, a documented API quirk, not this project's guess), so that
body-shape interpretation lives in `TwelveDataDataProvider.fetch()`
instead, mirroring how `StooqDataProvider.fetch()` (not its transport)
interprets Stooq's own CSV-body "no data" shape. In practice a real
production run (ADR-0164's own follow-up correction) found Twelve Data
returns a real HTTP 429 for a burst of requests, handled by the
ordinary 429 branch below -- the body-shape branch in `fetch()` remains
for the documented quirk, not because the 429 branch here was wrong.

ADR-0164 (follow-up correction): owns a `TwelveDataRateLimiter` (one
per instance, shared by whichever caller holds this instance) and
paces every real call through it -- see that module's own docstring
for why a real production run made this necessary (the same category
of real-usage gap `TiingoRequestBudget`/ADR-0160 found for Tiingo,
just per-minute instead of per-hour).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from data_infra.provider import PermanentProviderError, TransientProviderError, parse_retry_after_seconds
from data_infra.providers.twelvedata_ratelimit import TwelveDataRateLimiter

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after", "x-request-id"}


def _filter_headers(raw_headers) -> dict[str, str]:
    result = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = raw_headers.get(key)
        if value is not None:
            result[key] = value
    return result


@dataclass(frozen=True)
class TwelveDataTransportResponse:
    status_code: int
    body: Optional[object]  # parsed JSON -- a dict, or None if unparseable
    headers: dict[str, str]


class TwelveDataHttpTransport:
    def __init__(self, base_url: str, *, rate_limiter: Optional[TwelveDataRateLimiter] = None) -> None:
        self._base_url = base_url.rstrip("/")
        # A fresh, instance-owned limiter when the caller does not
        # supply one -- constructing exactly one TwelveDataHttpTransport
        # and reusing it is what makes this shared without any caller
        # having to pass one explicitly, same discipline
        # TiingoHttpTransport's own budget parameter already has.
        self._rate_limiter = rate_limiter if rate_limiter is not None else TwelveDataRateLimiter()

    def get(self, path: str, *, params: dict[str, str], timeout: float) -> TwelveDataTransportResponse:
        self._rate_limiter.wait_if_needed()
        self._rate_limiter.record_request()

        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self._base_url}{path}?{query}" if query else f"{self._base_url}{path}"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as raw_response:
                status_code = raw_response.status
                raw_text = raw_response.read().decode("utf-8")
                response_headers = _filter_headers(raw_response.headers)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            raw_text = exc.read().decode("utf-8") if exc.fp is not None else None
            response_headers = _filter_headers(exc.headers) if exc.headers is not None else {}
        except TimeoutError as exc:
            raise TransientProviderError(f"request to {path} timed out after {timeout}s") from exc
        except urllib.error.URLError as exc:
            raise TransientProviderError(f"connection failure calling {path}: {exc.reason}") from exc

        if status_code >= 500:
            raise TransientProviderError(
                f"provider error: HTTP {status_code} calling {path}",
                retry_after_seconds=parse_retry_after_seconds(response_headers.get("retry-after")),
            )
        if status_code == 429:
            raise TransientProviderError(
                f"rate limited calling {path}",
                retry_after_seconds=parse_retry_after_seconds(response_headers.get("retry-after")),
            )
        if status_code in (401, 403):
            raise PermanentProviderError(f"authentication/authorization failed calling {path}: HTTP {status_code}")
        if status_code == 404:
            raise PermanentProviderError(f"not found calling {path}")

        parsed_body: Optional[object] = None
        if raw_text:
            try:
                parsed_body = json.loads(raw_text)
            except json.JSONDecodeError:
                parsed_body = None

        return TwelveDataTransportResponse(status_code=status_code, body=parsed_body, headers=response_headers)
