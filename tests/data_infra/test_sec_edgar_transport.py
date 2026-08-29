"""Category: Transport Failure Test -- `SecEdgarHttpTransport` is the
one real, network-capable component in `data_infra.providers.sec_edgar`.
This file is the only place in the test suite allowed to import it,
and it never reaches the network -- `urllib.request.urlopen` is
monkeypatched in every test, mirroring `test_tiingo_transport.py`'s
identical discipline (ADR-0025's "no automated test may call a real
external provider" rule, applied here to SEC EDGAR, Phase 33)."""

from __future__ import annotations

import json
import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.sec_edgar_transport import SecEdgarHttpTransport


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
            return _FakeHTTPResponse(200, {"cik": 320193, "facts": {}}, {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        response = transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)
        assert response.status_code == 200
        assert response.body == {"cik": 320193, "facts": {}}

    def test_get_sends_the_configured_user_agent(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["user_agent"] = req.get_header("User-agent")
            return _FakeHTTPResponse(200, {}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="MyProject me@example.com")
        transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)
        assert captured["user_agent"] == "MyProject me@example.com"


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        with pytest.raises(TransientProviderError):
            transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        with pytest.raises(TransientProviderError):
            transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)


class TestHttpErrorMapping:
    def test_403_raises_permanent_provider_error(self, monkeypatch) -> None:
        # The exact failure mode this project has actually observed for
        # every external market-data host from this environment
        # (ADR-0033/0034) -- worth its own explicit test since it is not
        # a hypothetical.
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://data.sec.gov/x", 403, "Forbidden", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)

    def test_404_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://data.sec.gov/x", 404, "Not Found", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)

    def test_429_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://data.sec.gov/x", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        with pytest.raises(TransientProviderError):
            transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://data.sec.gov/x", 500, "Server Error", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        with pytest.raises(TransientProviderError):
            transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)


class TestUnparseableBody:
    def test_non_json_body_yields_none_body_not_an_exception(self, monkeypatch) -> None:
        class _RawResponse:
            status = 200
            headers = {}

            def read(self):
                return b"not json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _RawResponse())
        transport = SecEdgarHttpTransport("https://data.sec.gov", user_agent="test test@example.com")
        response = transport.get("/api/xbrl/companyfacts/CIK0000320193.json", timeout=5.0)
        assert response.status_code == 200
        assert response.body is None
