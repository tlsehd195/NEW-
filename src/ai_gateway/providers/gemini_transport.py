"""GeminiHttpTransport: the one real, network-capable component of the
Gemini provider adapter. stdlib-only (`urllib.request`), no new
dependency added to `pyproject.toml` -- mirrors
`data_infra.providers.tiingo_transport.TiingoHttpTransport`'s identical
pattern, and raises `ai_gateway.provider`'s own existing exception
hierarchy (`ProviderTimeoutError`/`ProviderAuthError`/
`ProviderRateLimitError`/`ProviderError`) rather than inventing a second
one, since `ai_gateway.gateway.AIGateway.generate()` is written against
exactly those four types.

Never constructed by any automated test in this repository (no test in
this repository may ever call the real Gemini API, the same discipline
`tests/data_infra/test_tiingo_transport.py` already established for
Tiingo) -- `tests/ai_gateway/providers/test_gemini_transport.py` stubs
`urllib.request.urlopen` rather than reaching the network.

**Verified against a real call** (2026-09-25, account owner's own
`GEMINI_API_KEY`, `scripts/verify_gemini_adapter.py`):
`POST https://generativelanguage.googleapis.com/v1beta/models/{model}:
generateContent` with an `x-goog-api-key` header (never a `?key=` query
parameter -- a header cannot end up in a logged URL) is the real,
working request shape against model `gemini-3.8-flash`. Two real
response-shape facts this module depends on, confirmed directly (not
assumed from documentation, unlike this codebase's usual "Tier 2
evidence" market-data providers):
1. **A 429 response carries NO `Retry-After` HTTP header at all** --
   the real, usable retry signal is inside the JSON error body, at
   `error.details[]`, the entry whose `@type` ends in `...RetryInfo`,
   field `retryDelay` (a protobuf-JSON duration string, e.g. `"18s"`).
   `_parse_retry_delay_seconds` below reads the body, not headers.
2. A successful response's `usageMetadata` carries a real
   `thoughtsTokenCount` alongside `promptTokenCount`/
   `candidatesTokenCount`/`totalTokenCount` (gemini-3.8-flash is a
   "thinking" model by default) -- `total_tokens` is read from
   `totalTokenCount` directly rather than summing the other two fields,
   so this thinking-token cost is never silently dropped from
   `UsageInfo`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from ai_gateway.provider import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


def _parse_retry_delay_seconds(body: Optional[dict]) -> Optional[float]:
    """Reads the real retry signal Gemini actually supplies on a 429 --
    see this module's own docstring point 1. Returns `None` (never a
    fabricated default) when `body` is unparseable or carries no
    `RetryInfo` detail -- `ai_gateway.gateway.AIGateway` already treats
    that honestly as "no automatic recovery window" (`ai_gateway.
    provider.ProviderRateLimitError`'s own docstring)."""
    if not body:
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    for detail in error.get("details") or []:
        if not isinstance(detail, dict):
            continue
        if not str(detail.get("@type", "")).endswith("RetryInfo"):
            continue
        delay = detail.get("retryDelay")
        if not isinstance(delay, str) or not delay.endswith("s"):
            continue
        try:
            return float(delay[:-1])
        except ValueError:
            return None
    return None


def _error_message(body: Optional[dict], *, fallback: str) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return fallback


@dataclass(frozen=True)
class GeminiTransportResponse:
    status_code: int
    body: Optional[dict]  # parsed JSON, or None if the response was not valid JSON


class GeminiHttpTransport:
    def __init__(self, *, base_url: str = DEFAULT_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    def generate_content(
        self, *, model: str, api_key: str, request_body: dict, timeout: float,
    ) -> GeminiTransportResponse:
        url = f"{self._base_url}/v1beta/models/{model}:generateContent"
        data = json.dumps(request_body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            # API key sent as a header, never a `?key=` query parameter --
            # a header can never end up in a logged/persisted URL string.
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as raw_response:
                status_code = raw_response.status
                raw_text = raw_response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            raw_text = exc.read().decode("utf-8") if exc.fp is not None else None
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"Gemini request timed out after {timeout}s calling model {model!r}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"connection failure calling Gemini (model {model!r}): {exc.reason}") from exc

        body: Optional[dict] = None
        if raw_text:
            try:
                parsed = json.loads(raw_text)
                body = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                body = None

        if status_code == 429:
            raise ProviderRateLimitError(
                _error_message(body, fallback=f"rate limited calling Gemini (model {model!r})"),
                retry_after_seconds=_parse_retry_delay_seconds(body),
            )
        if status_code in (401, 403):
            raise ProviderAuthError(
                _error_message(body, fallback=f"authentication failed calling Gemini: HTTP {status_code}")
            )
        if status_code >= 500:
            raise ProviderError(_error_message(body, fallback=f"Gemini server error: HTTP {status_code}"))
        if status_code >= 400:
            raise ProviderError(_error_message(body, fallback=f"Gemini request error: HTTP {status_code}"))

        return GeminiTransportResponse(status_code=status_code, body=body)
