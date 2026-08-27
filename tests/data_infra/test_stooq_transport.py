"""Category: Transport Failure Test -- `StooqHttpTransport` is the one
real, network-capable component in `data_infra.providers.stooq`. This
file is the only place in the test suite allowed to import it, and it
never reaches the network -- `urllib.request.urlopen` is monkeypatched
in every test."""

from __future__ import annotations

import urllib.error

import pytest

from data_infra.provider import PermanentProviderError, TransientProviderError
from data_infra.providers.stooq_transport import StooqHttpTransport


class _FakeHTTPResponse:
    def __init__(self, status: int, text: str, headers: dict) -> None:
        self.status = status
        self._text = text.encode("utf-8")
        self.headers = headers

    def read(self) -> bytes:
        return self._text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestSuccessfulRequest:
    def test_get_returns_raw_csv_text(self, monkeypatch) -> None:
        csv_body = "Date,Open,High,Low,Close,Volume\n2024-01-02,185.0,186.5,184.2,185.64,82488700\n"

        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, csv_body, {"content-type": "text/csv"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = StooqHttpTransport("https://stooq.com")
        response = transport.get("/q/d/l/", params={"s": "aapl.us", "i": "d"}, timeout=5.0)
        assert response.status_code == 200
        assert response.raw_text == csv_body


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = StooqHttpTransport("https://stooq.com")
        with pytest.raises(TransientProviderError):
            transport.get("/q/d/l/", params={}, timeout=5.0)

    def test_connection_failure_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = StooqHttpTransport("https://stooq.com")
        with pytest.raises(TransientProviderError):
            transport.get("/q/d/l/", params={}, timeout=5.0)


class TestHttpErrorMapping:
    def test_404_raises_permanent_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://stooq.com/x", 404, "Not Found", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = StooqHttpTransport("https://stooq.com")
        with pytest.raises(PermanentProviderError):
            transport.get("/q/d/l/", params={}, timeout=5.0)

    def test_500_raises_transient_provider_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError("https://stooq.com/x", 500, "Internal Server Error", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = StooqHttpTransport("https://stooq.com")
        with pytest.raises(TransientProviderError):
            transport.get("/q/d/l/", params={}, timeout=5.0)


class TestNoSecretInRequest:
    def test_no_credential_is_ever_sent_stooq_requires_none(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            return _FakeHTTPResponse(200, "Date,Open,High,Low,Close,Volume\n", {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = StooqHttpTransport("https://stooq.com")
        transport.get("/q/d/l/", params={"s": "aapl.us"}, timeout=5.0)
        assert "token" not in captured["url"] and "key" not in captured["url"]
