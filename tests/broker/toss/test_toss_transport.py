"""Category: Transport Failure Test -- `TossHttpTransport` is the one
real, network-capable component in this codebase. This file is the only
place in the entire test suite allowed to import it, and it never
reaches the network -- `urllib.request.urlopen` is monkeypatched in
every test (instruction section 11: "테스트 환경에서는 실제 Toss
endpoint 호출 금지")."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from broker.errors import BrokerTimeoutError, BrokerTransportError
from broker.toss.transport import TossHttpTransport


class _FakeHTTPResponse:
    def __init__(self, status: int, body: dict, headers: dict) -> None:
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
    def test_post_returns_parsed_json_body(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(200, {"status": "FILLED", "orderId": "TOSS-1"}, {"content-type": "application/json"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        response = transport.post("/api/v1/orders", headers={}, json_body={"symbol": "005930"}, timeout=5.0)
        assert response.status_code == 200
        assert response.body == {"status": "FILLED", "orderId": "TOSS-1"}
        assert response.headers.get("content-type") == "application/json"

    def test_response_headers_are_filtered_to_the_safe_allowlist(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            return _FakeHTTPResponse(
                200, {"status": "PENDING"},
                {"content-type": "application/json", "set-cookie": "session=abc", "authorization": "Bearer leaked"},
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        response = transport.post("/api/v1/orders", headers={}, json_body={}, timeout=5.0)
        assert "set-cookie" not in response.headers
        assert "authorization" not in response.headers


class TestHttpErrorResponse:
    def test_http_error_is_captured_as_a_response_not_an_exception(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            body = json.dumps({"code": "expired-token", "message": "token expired"}).encode("utf-8")
            raise urllib.error.HTTPError(
                "https://openapi.tossinvest.com/api/v1/orders", 401, "Unauthorized",
                {"content-type": "application/json"}, io.BytesIO(body),
            )

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        response = transport.post("/api/v1/orders", headers={}, json_body={}, timeout=5.0)
        assert response.status_code == 401
        assert response.body == {"code": "expired-token", "message": "token expired"}


class TestTimeoutAndConnectionFailure:
    def test_timeout_raises_broker_timeout_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        with pytest.raises(BrokerTimeoutError):
            transport.post("/api/v1/orders", headers={}, json_body={}, timeout=5.0)

    def test_connection_failure_raises_broker_transport_error(self, monkeypatch) -> None:
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        with pytest.raises(BrokerTransportError):
            transport.post("/api/v1/orders", headers={}, json_body={}, timeout=5.0)


class TestMalformedResponse:
    def test_non_json_body_yields_none_body_not_a_crash(self, monkeypatch) -> None:
        class _RawTextResponse:
            status = 200
            headers = {}

            def read(self):
                return b"{not valid json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout):
            return _RawTextResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        response = transport.post("/api/v1/orders", headers={}, json_body={}, timeout=5.0)
        assert response.body is None
        assert response.raw_text == "{not valid json"


class TestNoSecretInRequestConstruction:
    def test_request_never_puts_credentials_in_the_url(self, monkeypatch) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            return _FakeHTTPResponse(200, {"status": "PENDING"}, {})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        transport = TossHttpTransport("https://openapi.tossinvest.com")
        transport.post(
            "/api/v1/orders", headers={"Authorization": "Bearer sk-real-secret-token"},
            json_body={"symbol": "005930"}, timeout=5.0,
        )
        assert "sk-real-secret-token" not in captured["url"]
