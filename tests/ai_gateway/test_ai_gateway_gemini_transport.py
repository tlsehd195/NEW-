"""Category: Transport Failure Test -- `GeminiHttpTransport` is the one
real, network-capable component of the Gemini provider adapter. This
file is the only place in the test suite allowed to import it, and it
never reaches the network -- `urllib.request.urlopen` is monkeypatched in
every test, mirroring `tests/data_infra/test_tiingo_transport.py`'s
identical discipline. No automated test in this repository may ever call
the real Gemini API."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from ai_gateway.provider import ProviderAuthError, ProviderError, ProviderRateLimitError, ProviderTimeoutError
from ai_gateway.providers.gemini_transport import GeminiHttpTransport


class _FakeHTTPResponse:
    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


_SUCCESS_BODY = {
    "candidates": [{"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}],
    "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 1, "totalTokenCount": 104},
}


class TestSuccessfulRequest:
    def test_generate_content_returns_parsed_body(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, _SUCCESS_BODY)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        response = transport.generate_content(
            model="gemini-3.8-flash", api_key="fake-key", request_body={"contents": []}, timeout=5.0
        )
        assert response.status_code == 200
        assert response.body == _SUCCESS_BODY


class TestNoSecretInRequestConstruction:
    def test_api_key_sent_as_header_never_in_url(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            return _FakeHTTPResponse(200, _SUCCESS_BODY)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        transport.generate_content(
            model="gemini-3.8-flash", api_key="sk-real-secret-key", request_body={"contents": []}, timeout=5.0
        )
        assert "sk-real-secret-key" not in captured["url"]
        assert captured["headers"].get("X-goog-api-key") == "sk-real-secret-key"


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_provider_timeout_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderTimeoutError):
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)

    def test_connection_failure_raises_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderError):
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)


class TestHttpErrorMapping:
    def _raise_http_error(self, monkeypatch, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")

        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                "https://generativelanguage.googleapis.com/x", status, "err", {}, io.BytesIO(raw)
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    def test_401_raises_provider_auth_error(self, monkeypatch) -> None:
        self._raise_http_error(monkeypatch, 401, {"error": {"message": "bad key"}})
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderAuthError):
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)

    def test_403_raises_provider_auth_error(self, monkeypatch) -> None:
        self._raise_http_error(monkeypatch, 403, {"error": {"message": "forbidden"}})
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderAuthError):
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)

    def test_500_raises_provider_error(self, monkeypatch) -> None:
        self._raise_http_error(monkeypatch, 500, {"error": {"message": "boom"}})
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderError):
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)

    def test_404_raises_provider_error(self, monkeypatch) -> None:
        # Real, directly-observed response (2026-09-25): an unrecognized
        # model name returns 404, not 400 -- must still be a retryable-
        # shaped ProviderError the Gateway can surface as PROVIDER_ERROR,
        # never silently swallowed.
        self._raise_http_error(monkeypatch, 404, {"error": {"message": "model not found"}})
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderError):
            transport.generate_content(model="no-such-model", api_key="x", request_body={}, timeout=5.0)


class TestRateLimitRetryAfterFromBody:
    """Real, directly-confirmed (2026-09-25) Gemini behavior: a 429
    response carries NO `Retry-After` HTTP header -- the real retry
    signal is `error.details[]`'s `...RetryInfo` entry's `retryDelay`
    field, inside the JSON body. A transport that only checked headers
    (the Tiingo/generic HTTP convention) would always get `None` here,
    silently degrading to "no automatic recovery window" every time even
    though Gemini did supply a real, usable signal."""

    def test_429_with_real_retry_info_body_carries_it_on_the_exception(self, monkeypatch) -> None:
        body = {
            "error": {
                "code": 429,
                "message": "quota exceeded",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.Help", "links": []},
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "18s"},
                ],
            }
        }
        raw = json.dumps(body).encode("utf-8")

        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                "https://generativelanguage.googleapis.com/x", 429, "Too Many Requests", {}, io.BytesIO(raw)
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderRateLimitError) as excinfo:
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)
        assert excinfo.value.retry_after_seconds == 18.0

    def test_429_with_no_retry_info_leaves_it_none(self, monkeypatch) -> None:
        raw = json.dumps({"error": {"message": "quota exceeded", "details": []}}).encode("utf-8")

        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                "https://generativelanguage.googleapis.com/x", 429, "Too Many Requests", {}, io.BytesIO(raw)
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderRateLimitError) as excinfo:
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)
        assert excinfo.value.retry_after_seconds is None

    def test_a_retry_after_http_header_alone_is_never_used(self, monkeypatch) -> None:
        """A header-only 429 (no body RetryInfo) must not fabricate a
        value from anywhere else -- confirms the transport genuinely
        reads the body, not headers, matching what Gemini actually sends."""
        raw = json.dumps({"error": {"message": "quota exceeded", "details": []}}).encode("utf-8")

        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                "https://generativelanguage.googleapis.com/x", 429, "Too Many Requests",
                {"retry-after": "60"}, io.BytesIO(raw),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = GeminiHttpTransport()
        with pytest.raises(ProviderRateLimitError) as excinfo:
            transport.generate_content(model="gemini-3.8-flash", api_key="x", request_body={}, timeout=5.0)
        assert excinfo.value.retry_after_seconds is None
