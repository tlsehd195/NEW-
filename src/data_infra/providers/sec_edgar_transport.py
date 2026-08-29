"""SecEdgarHttpTransport: the one real, network-capable component in
`data_infra.providers.sec_edgar`. stdlib-only (`urllib.request`), no
new dependency added -- mirrors `TiingoHttpTransport`'s identical
pattern (Phase 20), applied to SEC EDGAR (Phase 33).

Never constructed by anything in this repository's own tests,
backtests, or CI (no automated test in this repository may ever call
the real SEC EDGAR API). `tests/data_infra/test_sec_edgar_transport.py`
is the only test file allowed to import this module, and it stubs
`urllib.request.urlopen` rather than reaching the network -- same
discipline `test_tiingo_transport.py` already established.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from data_infra.provider import PermanentProviderError, TransientProviderError

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after", "x-request-id"}


def _filter_headers(raw_headers) -> dict[str, str]:
    result = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = raw_headers.get(key)
        if value is not None:
            result[key] = value
    return result


@dataclass(frozen=True)
class SecEdgarTransportResponse:
    status_code: int
    body: Optional[object]  # parsed JSON -- a dict for every EDGAR endpoint this project uses
    raw_text: Optional[str]
    headers: dict[str, str]


class SecEdgarHttpTransport:
    def __init__(self, base_url: str, *, user_agent: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent

    def get(self, path: str, *, timeout: float) -> SecEdgarTransportResponse:
        # SEC EDGAR's XBRL endpoints take no query parameters -- the
        # CIK/concept selection lives entirely in the path -- unlike
        # Tiingo's date-range params, so this signature is intentionally
        # narrower than TiingoHttpTransport.get's.
        url = f"{self._base_url}{path}"
        # A descriptive User-Agent is a documented SEC EDGAR requirement
        # (SecEdgarConfig's own docstring), not optional.
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent}, method="GET")
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
            raise TransientProviderError(f"provider error: HTTP {status_code} calling {path}")
        if status_code == 429:
            raise TransientProviderError(f"rate limited calling {path}")
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

        return SecEdgarTransportResponse(
            status_code=status_code, body=parsed_body, raw_text=raw_text, headers=response_headers
        )
