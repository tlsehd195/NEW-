"""Category: Transport Failure Test -- `TiingoHttpTransport` is the one
real, network-capable component in `data_infra.providers.tiingo`. This
file is the only place in the test suite allowed to import it, and it
never reaches the network -- `urllib.request.urlopen` is monkeypatched
in every test (ADR-0025: no automated test in this repository may ever
call the real Tiingo API)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.tiingo_transport import TiingoHttpTransport


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
    def test_get_returns_parsed_json_array(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, [{"date": "2024-01-02", "close": "100.0"}], {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        response = transport.get("/tiingo/daily/AAPL/prices", params={"token": "x"}, timeout=5.0)
        assert response.status_code == 200
        assert response.body == [{"date": "2024-01-02", "close": "100.0"}]


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)


class TestHttpErrorMapping:
    def test_401_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 401, "Unauthorized", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_404_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 404, "Not Found", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_429_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://api.tiingo.com/x", 500, "Internal Server Error", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        with pytest.raises(TransientProviderError):
            transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)


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
        transport = TiingoHttpTransport("https://api.tiingo.com")
        response = transport.get("/tiingo/daily/AAPL/prices", params={}, timeout=5.0)
        assert response.body is None
        assert response.raw_text == "not valid json"


class TestNoSecretInRequestConstruction:
    def test_token_in_query_params_never_leaks_into_headers(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            return _FakeHTTPResponse(200, [], {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TiingoHttpTransport("https://api.tiingo.com")
        transport.get("/tiingo/daily/AAPL/prices", params={"token": "sk-real-secret-token"}, timeout=5.0)
        assert "sk-real-secret-token" in captured["url"]  # Tiingo's own documented auth mechanism is a query param
        assert "Authorization" not in captured["headers"]
