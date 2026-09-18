"""Category: Transport Failure Test -- `TwelveDataHttpTransport` is the
one real, network-capable component in `data_infra.providers.
twelvedata`. This file is the only place in the test suite allowed to
import it, and it never reaches the network -- `urllib.request.urlopen`
is monkeypatched in every test (no automated test in this repository
may ever call the real Twelve Data API)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.twelvedata_ratelimit import TwelveDataRateLimiter
from data_infra.providers.twelvedata_transport import TwelveDataHttpTransport


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
            return _FakeHTTPResponse(200, {"values": [{"datetime": "2024-01-02"}]}, {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        response = transport.get("/time_series", params={"apikey": "x"}, timeout=5.0)
        assert response.status_code == 200
        assert response.body == {"values": [{"datetime": "2024-01-02"}]}


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        with pytest.raises(TransientProviderError):
            transport.get("/time_series", params={}, timeout=5.0)

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        with pytest.raises(TransientProviderError):
            transport.get("/time_series", params={}, timeout=5.0)


class TestHttpErrorMapping:
    def test_401_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.twelvedata.com/x", 401, "Unauthorized", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/time_series", params={}, timeout=5.0)

    def test_404_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.twelvedata.com/x", 404, "Not Found", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/time_series", params={}, timeout=5.0)

    def test_429_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.twelvedata.com/x", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        with pytest.raises(TransientProviderError):
            transport.get("/time_series", params={}, timeout=5.0)

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.twelvedata.com/x", 500, "Internal Server Error", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        with pytest.raises(TransientProviderError):
            transport.get("/time_series", params={}, timeout=5.0)


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
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        response = transport.get("/time_series", params={}, timeout=5.0)
        assert response.body is None


class TestRateLimiting:
    """ADR-0164 follow-up correction: a real production run burst
    through Twelve Data's real 8/minute limit with no pacing at all --
    `get()` must consult a shared `TwelveDataRateLimiter` before every
    real call, mirroring `TiingoHttpTransport`'s identical
    `TestRequestBudget` discipline for its own budget."""

    def test_a_shared_rate_limiter_is_paced_across_repeated_calls(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, {"values": []}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        clock_value = {"t": 0.0}
        waits: list[float] = []

        def fake_sleep(seconds: float) -> None:
            waits.append(seconds)
            clock_value["t"] += seconds  # a real sleep_fn must advance real wall-clock time

        limiter = TwelveDataRateLimiter(
            limit_per_minute=8, safety_margin=1, clock=lambda: clock_value["t"], sleep_fn=fake_sleep,
        )
        transport = TwelveDataHttpTransport("https://api.twelvedata.com", rate_limiter=limiter)
        for _ in range(8):  # effective cap is 7 -- the 8th must wait
            transport.get("/time_series", params={}, timeout=5.0)
        assert len(waits) == 1

    def test_without_an_explicit_rate_limiter_a_default_one_is_still_enforced(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, {"values": []}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        assert transport._rate_limiter is not None


class TestNoSecretInRequestConstruction:
    def test_apikey_in_query_params_never_leaks_into_headers(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            return _FakeHTTPResponse(200, {"values": []}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TwelveDataHttpTransport("https://api.twelvedata.com")
        transport.get("/time_series", params={"apikey": "sk-real-secret-key"}, timeout=5.0)
        assert "sk-real-secret-key" in captured["url"]  # Twelve Data's own documented auth mechanism is a query param
        assert "Authorization" not in captured["headers"]
