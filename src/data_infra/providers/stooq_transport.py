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
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional

from data_infra.provider import PermanentProviderError, TransientProviderError

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after", "x-request-id"}


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
        req = urllib.request.Request(url, method="GET")
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
            raise TransientProviderError(f"Stooq request to {path} failed with status {status_code}") from exc
        except TimeoutError as exc:
            raise TransientProviderError(f"Stooq request to {path} timed out after {timeout}s") from exc
        except urllib.error.URLError as exc:
            raise TransientProviderError(f"Stooq connection failure calling {path}: {exc.reason}") from exc

        return StooqTransportResponse(status_code=status_code, raw_text=raw_text, headers=headers)
