"""Category: Authentication Failure Test -- `broker.toss.auth` is the
only place in `broker.*` allowed to read `os.environ`
(`tests/broker/test_broker_boundary.py` verifies this structurally).
This file verifies its actual resolve/fetch-token behavior, always
using a stubbed `BrokerTransport` -- never the real network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from broker.config import BrokerConfig
from broker.enums import BrokerExecutionMode
from broker.errors import BrokerAuthError
from broker.toss.auth import TossAuthClient, resolve_credentials
from broker.transport import MockTransport, TransportResponse


def utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _live_config() -> BrokerConfig:
    return BrokerConfig(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)


class TestResolveCredentials:
    def test_missing_all_env_vars_raises_broker_auth_error(self, monkeypatch) -> None:
        monkeypatch.delenv("TOSS_API_KEY", raising=False)
        monkeypatch.delenv("TOSS_API_SECRET", raising=False)
        monkeypatch.delenv("TOSS_ACCOUNT_ID", raising=False)
        with pytest.raises(BrokerAuthError):
            resolve_credentials(_live_config())

    def test_partial_env_vars_still_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "client-id-value")
        monkeypatch.delenv("TOSS_API_SECRET", raising=False)
        monkeypatch.delenv("TOSS_ACCOUNT_ID", raising=False)
        with pytest.raises(BrokerAuthError):
            resolve_credentials(_live_config())

    def test_all_env_vars_present_resolves(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "client-id-value")
        monkeypatch.setenv("TOSS_API_SECRET", "client-secret-value")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "ACC-001")
        credentials = resolve_credentials(_live_config())
        assert credentials.client_id == "client-id-value"
        assert credentials.client_secret == "client-secret-value"
        assert credentials.account_id == "ACC-001"

    def test_custom_reference_names_are_respected(self, monkeypatch) -> None:
        config = BrokerConfig(
            execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True,
            api_key_reference="CUSTOM_KEY", api_secret_reference="CUSTOM_SECRET", account_reference="CUSTOM_ACCOUNT",
        )
        monkeypatch.setenv("CUSTOM_KEY", "k")
        monkeypatch.setenv("CUSTOM_SECRET", "s")
        monkeypatch.setenv("CUSTOM_ACCOUNT", "a")
        credentials = resolve_credentials(config)
        assert credentials.client_id == "k"


class TestFetchAccessToken:
    def test_successful_token_fetch(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        transport = MockTransport(response_body={"access_token": "tok-abc123"})
        client = TossAuthClient(transport, _live_config())
        token = client.fetch_access_token()
        assert token == "tok-abc123"

    def test_declares_form_urlencoded_content_type_matching_the_grant_type_body(self, monkeypatch) -> None:
        """External review finding (Session 36 continued): this call
        site's own declared Content-Type must actually match the shape
        of the body it sends -- RFC 6749 section 4.4.2 requires a
        client_credentials token request body to be form-urlencoded,
        not JSON. `MockTransport` now records the exact `headers`/
        `json_body` this call site passed (it previously recorded
        nothing, which is why this specific mismatch went undetected
        until an external review caught it in the real network-capable
        transport implementation instead)."""
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        transport = MockTransport(response_body={"access_token": "tok-abc123"})
        client = TossAuthClient(transport, _live_config())
        client.fetch_access_token()

        assert transport.last_headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert transport.last_json_body == {
            "grant_type": "client_credentials", "client_id": "k", "client_secret": "s",
        }

    def test_missing_access_token_field_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")
        transport = MockTransport(response_body={"unexpected_field": "x"})
        client = TossAuthClient(transport, _live_config())
        with pytest.raises(BrokerAuthError):
            client.fetch_access_token()

    def test_non_200_status_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("TOSS_API_KEY", "k")
        monkeypatch.setenv("TOSS_API_SECRET", "s")
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "a")

        class _RejectingTransport:
            def post(self, path, *, headers, json_body, timeout):
                return TransportResponse(401, {"code": "invalid_client"}, None, {})

            def get(self, path, *, headers, params, timeout):
                raise NotImplementedError

        client = TossAuthClient(_RejectingTransport(), _live_config())
        with pytest.raises(BrokerAuthError):
            client.fetch_access_token()

    def test_missing_credentials_raises_before_any_transport_call(self, monkeypatch) -> None:
        monkeypatch.delenv("TOSS_API_KEY", raising=False)
        monkeypatch.delenv("TOSS_API_SECRET", raising=False)
        monkeypatch.delenv("TOSS_ACCOUNT_ID", raising=False)

        class _CountingTransport:
            def __init__(self):
                self.calls = 0

            def post(self, path, *, headers, json_body, timeout):
                self.calls += 1
                return TransportResponse(200, {"access_token": "x"}, None, {})

            def get(self, path, *, headers, params, timeout):
                raise NotImplementedError

        transport = _CountingTransport()
        client = TossAuthClient(transport, _live_config())
        with pytest.raises(BrokerAuthError):
            client.fetch_access_token()
        assert transport.calls == 0  # never even attempted the network call without credentials
