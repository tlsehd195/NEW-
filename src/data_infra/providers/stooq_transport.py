"""StooqHttpTransport: the one real, network-capable transport for
Stooq -- stdlib-only (`urllib.request`), mirrors `broker.toss.transport.
TossHttpTransport`/`data_infra.providers.tiingo_transport.
TiingoHttpTransport`'s identical isolation pattern.

Stooq's daily-history endpoint (`stooq.com/q/d/l/`, ADR-0025) returns
CSV, not JSON -- `StooqTransportResponse.raw_text` is the primary
payload; `body` stays `None` (there is no JSON to parse).
`tests/data_infra/test_stooq_transport.py` is the only test file
permitted to import this module, and it stubs `urllib.request.urlopen`
rather than reaching the network.

ADR-0157 (external review, real production failure): the first real
exercise of this fallback path -- Tiingo rate-limited, so `Fallback
DataProvider` tried Stooq for real -- got a 404 on every single
request, including several highly liquid large-cap tickers (MS, WFC,
AXP, LLY, TMO, ABT, ADBE) that are extremely unlikely to genuinely be
absent from Stooq's coverage all at once. This module's own original
docstring already disclosed it had "never been exercised against a
live Stooq response in this environment" (ADR-0025's own network
policy blocks stooq.com here too) -- this was that first real
exercise, and it found a request built with NO `User-Agent` header at
all (Python's default `urllib` User-Agent is a well-known bot
signature many sites filter). A descriptive User-Agent is now sent, as
the same category of fix `SecEdgarHttpTransport` already applies for
the identical reason. This is a best-effort fix against a Tier 2 (never
independently verified) assumption about Stooq's real filtering
behavior -- it needs re-verification against a real scheduled/
`workflow_dispatch` run, the same way the original bug was found, not
assumed fixed from this reasoning alone.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional

from data_infra.provider import PermanentProviderError, TransientProviderError, parse_retry_after_seconds

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after", "x-request-id"}

# A real, current desktop-browser User-Agent string -- Stooq has no
# official API and no documented bot-identification convention (unlike
# SEC EDGAR, which requires a specific descriptive User-Agent by
# policy), so mimicking an ordinary browser is the standard workaround
# for this exact class of unofficial, no-auth scraping endpoint.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class StooqTransportResponse:
    __slots__ = ("status_code", "raw_text", "headers")

    def __init__(self, status_code: int, raw_text: Optional[str], headers: dict) -> None:
        self.status_code = status_code
        self.raw_text = raw_text
        self.headers = headers


def _filter_headers(raw_headers) -> dict:
    result = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = raw_headers.get(key)
        if value is not None:
            result[key] = value
    return result


class StooqHttpTransport:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def get(self, path: str, *, params: dict, timeout: float) -> StooqTransportResponse:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self._base_url}{path}?{query}" if query else f"{self._base_url}{path}"
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as raw_response:
                status_code = raw_response.status
                raw_text = raw_response.read().decode("utf-8", errors="replace")
                headers = _filter_headers(raw_response.headers)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            raw_text = exc.read().decode("utf-8", errors="replace") if exc.fp is not None else None
            headers = _filter_headers(exc.headers) if exc.headers is not None else {}
            if status_code in (401, 403, 404):
                raise PermanentProviderError(f"Stooq request to {path} failed with status {status_code}") from exc
            raise TransientProviderError(
                f"Stooq request to {path} failed with status {status_code}",
                retry_after_seconds=parse_retry_after_seconds(headers.get("retry-after")),
            ) from exc
        except TimeoutError as exc:
            raise TransientProviderError(f"Stooq request to {path} timed out after {timeout}s") from exc
        except urllib.error.URLError as exc:
            raise TransientProviderError(f"Stooq connection failure calling {path}: {exc.reason}") from exc

        return StooqTransportResponse(status_code=status_code, raw_text=raw_text, headers=headers)
