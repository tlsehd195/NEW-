"""FredHttpTransport: the one real, network-capable component in
`data_infra.providers.fred`. stdlib-only (`urllib.request`), no new
dependency added to `pyproject.toml` -- mirrors
`data_infra.providers.tiingo_transport.TiingoHttpTransport`'s identical
pattern.

Never constructed by anything in this repository's own tests, backtests,
or CI (no automated test in this repository may ever call the real FRED
API, the same discipline ADR-0025 established for Tiingo).
`tests/data_infra/test_fred_transport.py` is the only test file allowed
to import this module, and it stubs `urllib.request.urlopen` rather than
reaching the network.

**Verified against a real call** (2026-09-26, account owner's own
`FRED_API_KEY`, `scripts/verify_fred_adapter.py`,
https://github.com/tlsehd195/NEW-/actions/runs/36227829988): a real
`GET .../fred/series/observations?series_id=DGS3MO&api_key=...&
file_type=json&observation_start=...&observation_end=...` call against
the real FRED API returned a real HTTP 200 with the exact documented
success shape (`{"observations": [{"date": "2026-09-14", "value":
"4.11"}, ...]}`, 9 real observations over a 14-day window) -- the
request construction, auth-via-query-parameter, and success-path
parsing (`fred.py`'s `_parse_observation_date`/`_parse_value`) are
confirmed real, working code, not just documentation-derived guesses.

**Two facts below remain Tier 2 (FRED's own published documentation
only) -- that one real call's window happened to contain no missing
day and no error response, so neither was actually exercised.** Update
this docstring the same way if a future real call reveals either to be
wrong:

1. **A missing/unavailable observation's `"value"` field is the literal
   string `"."`**, never absent, `null`, or an empty string -- FRED's
   own documented convention for every series.
2. **An invalid or unregistered `api_key` fails with HTTP 400** (not
   401/403) and a JSON body `{"error_code": 400, "error_message": "..."}`
   -- confirmed via FRED's own errors documentation. This transport
   therefore treats every 400 as a `PermanentProviderError` (bad
   request AND bad credentials both use this one status code upstream,
   so there is no reliable way to tell them apart from the status code
   alone; the real `error_message` is preserved in the raised error for
   a human to read).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from data_infra.provider import PermanentProviderError, TransientProviderError, parse_retry_after_seconds

_SAFE_RESPONSE_HEADERS = {"content-type", "retry-after"}


def _filter_headers(raw_headers) -> dict[str, str]:
    result = {}
    for key in _SAFE_RESPONSE_HEADERS:
        value = raw_headers.get(key)
        if value is not None:
            result[key] = value
    return result


def _error_message(body: Optional[dict], *, fallback: str) -> str:
    if isinstance(body, dict) and isinstance(body.get("error_message"), str):
        return body["error_message"]
    return fallback


@dataclass(frozen=True)
class FredTransportResponse:
    status_code: int
    body: Optional[dict]  # parsed JSON, or None if the response was not valid JSON


class FredHttpTransport:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def get_series_observations(
        self, *, series_id: str, api_key: str, observation_start: str, observation_end: str, timeout: float,
    ) -> FredTransportResponse:
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": observation_start,
            "observation_end": observation_end,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self._base_url}/fred/series/observations?{query}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
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
            raise TransientProviderError(f"FRED request for series {series_id!r} timed out after {timeout}s") from exc
        except urllib.error.URLError as exc:
            raise TransientProviderError(f"connection failure calling FRED for series {series_id!r}: {exc.reason}") from exc

        body: Optional[dict] = None
        if raw_text:
            try:
                parsed = json.loads(raw_text)
                body = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                body = None

        if status_code == 429:
            raise TransientProviderError(
                _error_message(body, fallback=f"rate limited calling FRED for series {series_id!r}"),
                retry_after_seconds=parse_retry_after_seconds(response_headers.get("retry-after")),
            )
        if status_code >= 500:
            raise TransientProviderError(
                _error_message(body, fallback=f"FRED server error: HTTP {status_code} for series {series_id!r}"),
                retry_after_seconds=parse_retry_after_seconds(response_headers.get("retry-after")),
            )
        if status_code == 400:
            # See this module's own docstring point 2: FRED conflates
            # "bad request" and "bad/unregistered api_key" into this one
            # status code -- both are non-retryable.
            raise PermanentProviderError(
                _error_message(body, fallback=f"FRED rejected the request for series {series_id!r}: HTTP 400")
            )
        if status_code >= 400:
            raise PermanentProviderError(
                _error_message(body, fallback=f"FRED request error: HTTP {status_code} for series {series_id!r}")
            )

        return FredTransportResponse(status_code=status_code, body=body)
