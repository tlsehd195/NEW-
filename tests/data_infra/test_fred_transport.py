"""Category: Transport Failure Test -- `FredHttpTransport` is the one
real, network-capable component in `data_infra.providers.fred`. This
file is the only place in the test suite allowed to import it, and it
never reaches the network -- `urllib.request.urlopen` is monkeypatched
in every test, the same discipline `test_tiingo_transport.py` already
established for Tiingo."""

from __future__ import annotations

import json
import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.fred_transport import FredHttpTransport


class _FakeHTTPResponse:
    def __init__(self, status: int, body, headers: dict) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _call(transport: FredHttpTransport):
    return transport.get_series_observations(
        series_id="DGS3MO", api_key="x", observation_start="2024-01-01", observation_end="2024-01-31", timeout=5.0
    )


class TestSuccessfulRequest:
    def test_returns_parsed_json_body(self, monkeypatch) -> None:
        body = {"observations": [{"date": "2024-01-02", "value": "5.40"}]}

        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, body, {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        response = _call(FredHttpTransport("https://api.stlouisfed.org"))
        assert response.status_code == 200
        assert response.body == body

    def test_api_key_is_sent_as_a_query_parameter(self, monkeypatch) -> None:
        captured_urls = []

        def fake_urlopen(req, timeout):
            captured_urls.append(req.full_url)
            return _FakeHTTPResponse(200, {"observations": []}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = FredHttpTransport("https://api.stlouisfed.org")
        transport.get_series_observations(
            series_id="DGS3MO", api_key="real-key", observation_start="2024-01-01", observation_end="2024-01-31", timeout=5.0
        )
        assert "api_key=real-key" in captured_urls[0]
        assert "file_type=json" in captured_urls[0]


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(TransientProviderError):
            _call(FredHttpTransport("https://api.stlouisfed.org"))

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        with pytest.raises(TransientProviderError):
            _call(FredHttpTransport("https://api.stlouisfed.org"))


class TestHttpErrorStatusCodes:
    def _http_error(self, status: int, body: dict):
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                url="https://api.stlouisfed.org", code=status, msg="error",
                hdrs={"content-type": "application/json"},
                fp=_FakeHTTPResponse(status, body, {}),
            )

        return fake_urlopen

    def test_400_raises_permanent_provider_error_with_fred_message(self, monkeypatch) -> None:
        """FRED's own documented behavior (this transport's own docstring
        point 2): a bad request AND a bad/unregistered api_key both come
        back as HTTP 400, never 401/403 -- this must be treated as
        non-retryable, unlike a real Tiingo-style auth failure."""
        body = {"error_code": 400, "error_message": "Bad Request. The value for api_key is not registered."}
        monkeypatch.setattr("urllib.request.urlopen", self._http_error(400, body))
        with pytest.raises(PermanentProviderError, match="not registered"):
            _call(FredHttpTransport("https://api.stlouisfed.org"))

    def test_429_raises_transient_provider_error(self, monkeypatch) -> None:
        monkeypatch.setattr("urllib.request.urlopen", self._http_error(429, {"error_message": "Too Many Requests"}))
        with pytest.raises(TransientProviderError):
            _call(FredHttpTransport("https://api.stlouisfed.org"))

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        monkeypatch.setattr("urllib.request.urlopen", self._http_error(500, {"error_message": "Internal Server Error"}))
        with pytest.raises(TransientProviderError):
            _call(FredHttpTransport("https://api.stlouisfed.org"))
