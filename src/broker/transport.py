"""BrokerTransport Protocol + MockTransport: the network-call boundary
every domain-level adapter method (`broker.mock.MockBrokerAdapter`,
`broker.toss.adapter.TossBrokerAdapter`) sits behind, per instruction
section 8 -- Toss API call code is never mixed directly into domain
logic.

See docs/specifications/PHASE-13-toss-securities-adapter.md section 9.

`MockTransport` is deterministic and makes no network call at all --
the only transport this package's own tests ever construct
(instruction section 11: "테스트 환경에서는 실제 Toss endpoint 호출
금지"). `broker.toss.transport.TossHttpTransport` is the one real,
network-capable implementation, and it is never imported by anything in
this module or by any test in `tests/broker/` outside
`tests/broker/toss/test_toss_transport.py`, which stubs `urllib` rather
than reaching the network.
"""

from __future__ import annotations

from typing import Optional, Protocol


class TransportResponse:
    """`headers` is pre-filtered by the transport itself to a small,
    known-safe allowlist (e.g. `content-type`, `retry-after`,
    `x-request-id`) before this object is ever constructed -- there is
    no field here through which an `Authorization`/secret header value
    could reach domain code or a log line
    (`tests/broker/test_broker_secret_safety.py`)."""

    __slots__ = ("status_code", "body", "raw_text", "headers")

    def __init__(
        self, status_code: int, body: Optional[dict], raw_text: Optional[str], headers: dict[str, str]
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.raw_text = raw_text
        self.headers = headers


class BrokerTransport(Protocol):
    def post(self, path: str, *, headers: dict[str, str], json_body: dict, timeout: float) -> TransportResponse: ...
    def get(self, path: str, *, headers: dict[str, str], params: dict, timeout: float) -> TransportResponse: ...


class MockTransport:
    """`failure_mode` deterministically simulates instruction section
    11's required fail-closed scenarios -- never a real timer/socket:
    `None` (success), `"timeout"`, `"connection_failure"`,
    `"auth_failure"`, `"rate_limit"`, `"malformed"`, `"unknown_status"`.
    `response_body` (used only on the success path) lets a caller shape
    exactly what a successful call returns, without ever touching a
    network stack."""

    def __init__(self, *, failure_mode: Optional[str] = None, response_body: Optional[dict] = None) -> None:
        self._failure_mode = failure_mode
        self._response_body = response_body if response_body is not None else {"status": "PENDING"}
        self.call_count = 0
        # Session 36 continued (external review remediation): records
        # the last call's real arguments so a caller-side test (e.g.
        # `TossAuthClient.fetch_access_token`'s own declared headers/
        # body shape) can assert on what was actually sent, without
        # needing the real network-capable `TossHttpTransport` -- closes
        # the "wire format never verified" test gap the external review
        # found for `tests/broker/toss/test_toss_auth.py`.
        self.last_headers: Optional[dict[str, str]] = None
        self.last_json_body: Optional[dict] = None
        self.last_params: Optional[dict] = None

    def _respond(self) -> TransportResponse:
        self.call_count += 1
        if self._failure_mode == "timeout":
            from broker.errors import BrokerTimeoutError

            raise BrokerTimeoutError("simulated transport timeout")
        if self._failure_mode == "connection_failure":
            from broker.errors import BrokerTransportError

            raise BrokerTransportError("simulated connection failure")
        if self._failure_mode == "auth_failure":
            return TransportResponse(401, {"code": "expired-token", "message": "token expired"}, None, {})
        if self._failure_mode == "rate_limit":
            return TransportResponse(429, {"code": "rate-limited", "message": "too many requests"}, {"retry-after": "1"}, {"retry-after": "1"})
        if self._failure_mode == "malformed":
            return TransportResponse(200, None, "{not valid json", {})
        if self._failure_mode == "unknown_status":
            return TransportResponse(200, {"status": "SOME_STATUS_THIS_ADAPTER_HAS_NEVER_SEEN"}, None, {})
        return TransportResponse(200, self._response_body, None, {})

    def post(self, path: str, *, headers: dict[str, str], json_body: dict, timeout: float) -> TransportResponse:
        self.last_headers = headers
        self.last_json_body = json_body
        return self._respond()

    def get(self, path: str, *, headers: dict[str, str], params: dict, timeout: float) -> TransportResponse:
        self.last_headers = headers
        self.last_params = params
        return self._respond()
