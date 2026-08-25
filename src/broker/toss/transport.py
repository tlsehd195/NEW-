"""TossHttpTransport: the one real, network-capable `BrokerTransport`
implementation in this codebase -- stdlib-only (`urllib.request`), no
new dependency added to `pyproject.toml`.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 9.

Never constructed by anything in `broker.*` other than a caller that
explicitly imports it (there is no default factory anywhere that
returns one) -- `broker.mock.MockBrokerAdapter` is what every internal
pipeline, backtest, and test in this repository actually uses.
`tests/broker/toss/test_toss_transport.py` is the only test file in
this repository allowed to import this module, and it stubs
`urllib.request.urlopen` rather than reaching the network
(instruction section 11: "테스트 환경에서는 실제 Toss endpoint 호출
금지").
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from broker.errors import BrokerTimeoutError, BrokerTransportError
from broker.transport import TransportResponse

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after", "x-request-id"}


def _filter_headers(raw_headers) -> dict[str, str]:
    result = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = raw_headers.get(key)
        if value is not None:
            result[key] = value
    return result


class TossHttpTransport:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def _request(
        self, method: str, path: str, *, headers: dict[str, str], body: Optional[dict], timeout: float
    ) -> TransportResponse:
        url = f"{self._base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = dict(headers)
        request_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
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
            raise BrokerTimeoutError(f"request to {path} timed out after {timeout}s") from exc
        except urllib.error.URLError as exc:
            raise BrokerTransportError(f"connection failure calling {path}: {exc.reason}") from exc

        parsed_body: Optional[dict] = None
        if raw_text:
            try:
                candidate = json.loads(raw_text)
                if isinstance(candidate, dict):
                    parsed_body = candidate
            except json.JSONDecodeError:
                parsed_body = None

        return TransportResponse(status_code=status_code, body=parsed_body, raw_text=raw_text, headers=response_headers)

    def post(self, path: str, *, headers: dict[str, str], json_body: dict, timeout: float) -> TransportResponse:
        return self._request("POST", path, headers=headers, body=json_body, timeout=timeout)

    def get(self, path: str, *, headers: dict[str, str], params: dict, timeout: float) -> TransportResponse:
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            path = f"{path}?{query}"
        return self._request("GET", path, headers=headers, body=None, timeout=timeout)
