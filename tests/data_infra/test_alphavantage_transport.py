"""Category: Transport Failure Test -- `AlphaVantageHttpTransport` is
the one real, network-capable component in `data_infra.providers.
alphavantage`. This file is the only place in the test suite allowed to
import it, and it never reaches the network -- `urllib.request.urlopen`
is monkeypatched in every test (no automated test in this repository
may ever call the real Alpha Vantage API)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.alphavantage_ratelimit import AlphaVantageRateLimiter
from data_infra.providers.alphavantage_transport import AlphaVantageHttpTransport


class _FakeHTTPResponse:
    def __init__(self, status: int, body, headers: dict) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestSuccessfulRequest:
    def test_get_returns_parsed_json_object(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, {"Time Series (Daily)": {}}, {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        response = transport.get("/query", params={"apikey": "x"}, timeout=5.0)
        assert response.status_code == 200
        assert response.body == {"Time Series (Daily)": {}}


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        with pytest.raises(TransientProviderError):
            transport.get("/query", params={}, timeout=5.0)

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        with pytest.raises(TransientProviderError):
            transport.get("/query", params={}, timeout=5.0)


class TestHttpErrorMapping:
    def test_401_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://www.alphavantage.co/x", 401, "Unauthorized", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        with pytest.raises(PermanentProviderError):
            transport.get("/query", params={}, timeout=5.0)

    def test_404_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://www.alphavantage.co/x", 404, "Not Found", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        with pytest.raises(PermanentProviderError):
            transport.get("/query", params={}, timeout=5.0)

    def test_429_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://www.alphavantage.co/x", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        with pytest.raises(TransientProviderError):
            transport.get("/query", params={}, timeout=5.0)

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://www.alphavantage.co/x", 500, "Internal Server Error", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        with pytest.raises(TransientProviderError):
            transport.get("/query", params={}, timeout=5.0)


class TestMalformedResponse:
    def test_non_json_body_yields_none_body_not_a_crash(self, monkeypatch) -> None:
        class _RawTextResponse:
            status = 200
            headers = {}

            def read(self):
                return b"not valid json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout):
            return _RawTextResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        response = transport.get("/query", params={}, timeout=5.0)
        assert response.body is None


class TestRateLimiting:
    """2026-09-25: a real recon run fired two Alpha Vantage calls 4ms
    apart and the second came back with Alpha Vantage's own throttle
    notice instead of real data -- `get()` must consult a shared
    `AlphaVantageRateLimiter` before every real call, mirroring
    `TwelveDataHttpTransport`'s identical `TestRateLimiting`
    discipline."""

    def test_a_shared_rate_limiter_is_paced_across_repeated_calls(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, {"data": []}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        clock_value = {"t": 0.0}
        waits: list[float] = []

        def fake_sleep(seconds: float) -> None:
            waits.append(seconds)
            clock_value["t"] += seconds  # a real sleep_fn must advance real wall-clock time

        limiter = AlphaVantageRateLimiter(limit_per_second=1, clock=lambda: clock_value["t"], sleep_fn=fake_sleep)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co", rate_limiter=limiter)
        for _ in range(2):  # effective cap is 1 -- the 2nd must wait
            transport.get("/query", params={}, timeout=5.0)
        assert len(waits) == 1

    def test_without_an_explicit_rate_limiter_a_default_one_is_still_enforced(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, {"data": []}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        assert transport._rate_limiter is not None


class TestNoSecretInRequestConstruction:
    def test_apikey_in_query_params_never_leaks_into_headers(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            return _FakeHTTPResponse(200, {"Time Series (Daily)": {}}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = AlphaVantageHttpTransport("https://www.alphavantage.co")
        transport.get("/query", params={"apikey": "sk-real-secret-key"}, timeout=5.0)
        assert "sk-real-secret-key" in captured["url"]  # Alpha Vantage's own documented auth mechanism is a query param
        assert "Authorization" not in captured["headers"]
