"""TiingoHttpTransport: the one real, network-capable component in
`data_infra.providers.tiingo`. stdlib-only (`urllib.request`), no new
dependency added to `pyproject.toml` -- mirrors
`broker.toss.transport.TossHttpTransport`'s identical pattern (Phase 13).

Never constructed by anything in this repository's own tests, backtests,
or CI (no automated test in this repository may ever call the real
Tiingo API -- ADR-0025). `tests/data_infra/test_tiingo_transport.py` is
the only test file allowed to import this module, and it stubs
`urllib.request.urlopen` rather than reaching the network.

ADR-0160: owns a `TiingoRequestBudget` (one per instance, shared by
whichever caller holds this instance) and checks it before every real
call -- see that module's own docstring for why a real production run
made this necessary, and why owning it here (rather than in `Tiingo
DataProvider` or the calling script) covers every method that reaches
Tiingo for free.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from data_infra.provider import PermanentProviderError, TransientProviderError, parse_retry_after_seconds
from data_infra.providers.tiingo_budget import TiingoRequestBudget

logger = logging.getLogger(__name__)

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after", "x-request-id"}


def _filter_headers(raw_headers) -> dict[str, str]:
    result = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = raw_headers.get(key)
        if value is not None:
            result[key] = value
    return result


@dataclass(frozen=True)
class TiingoTransportResponse:
    status_code: int
    body: Optional[object]  # parsed JSON -- a list or dict, or None if unparseable
    raw_text: Optional[str]
    headers: dict[str, str]


class TiingoHttpTransport:
    def __init__(self, base_url: str, *, budget: Optional[TiingoRequestBudget] = None) -> None:
        self._base_url = base_url.rstrip("/")
        # A fresh, instance-owned budget when the caller does not
        # supply one -- constructing exactly one `TiingoHttpTransport`
        # and reusing it (as `scripts/ingest_real_market_data.py`
        # already does for both real call paths) is what makes this
        # shared without any caller having to pass one explicitly.
        self._budget = budget if budget is not None else TiingoRequestBudget()

    def get(self, path: str, *, params: dict[str, str], timeout: float) -> TiingoTransportResponse:
        if self._budget.would_exceed():
            message = (
                f"Tiingo request budget exhausted (proactive client-side cap at "
                f"{self._budget.limit_per_hour - self._budget.safety_margin} of the real "
                f"~{self._budget.limit_per_hour}/hour account limit, ADR-0160) -- refusing to "
                f"call {path}: retrying an already-exhausted hourly quota cannot refill it, "
                f"it only wastes time proving the obvious"
            )
            logger.warning(message)
            raise PermanentProviderError(message)
        # Counted against the budget before the real call, not after --
        # Tiingo's own server-side quota is consumed by the account
        # receiving the request at all, regardless of what it responds
        # (including a failure this transport goes on to raise for).
        self._budget.record_request()

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

        return TiingoTransportResponse(status_code=status_code, body=parsed_body, raw_text=raw_text, headers=response_headers)
