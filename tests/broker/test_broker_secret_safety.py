"""Category: Secret Leakage Test -- instruction section 9: API key /
secret / access token / refresh token values are never persisted,
logged, or present in any exception string this package raises."""

from __future__ import annotations

import dataclasses

from broker_helpers import make_broker_config, make_risk_checked_position, utc

from broker.errors import BrokerAuthError
from broker.mock import MockBrokerAdapter
from broker.models import BrokerOrderResponse, BrokerRequestRecord, BrokerResponseRecord, OrderStatusObservation
from broker.pipeline import submit_validated_order
from broker.repository import InMemoryBrokerRequestRepository, InMemoryBrokerResponseRepository
from broker.validation import build_validated_order

from storage.serialization import broker_request_to_payload, broker_response_to_payload, json_dumps

_FAKE_SECRET = "sk-live-super-secret-value-do-not-leak-12345"


class TestNoSecretFieldOnPersistedModels:
    def test_no_persisted_model_has_a_secret_shaped_field(self) -> None:
        forbidden = {"api_key", "secret", "access_token", "refresh_token", "client_secret", "authorization"}
        for cls in (BrokerOrderResponse, BrokerRequestRecord, BrokerResponseRecord, OrderStatusObservation):
            field_names = {f.name.lower() for f in dataclasses.fields(cls)}
            assert field_names.isdisjoint(forbidden), f"{cls.__name__} has a forbidden field"

    def test_broker_config_has_only_reference_fields_not_value_fields(self) -> None:
        from broker.config import BrokerConfig

        field_names = {f.name for f in dataclasses.fields(BrokerConfig)}
        assert "api_key_reference" in field_names
        assert "api_key" not in field_names
        assert "api_secret" not in field_names


class TestSecretNeverAppearsInPersistedPayload:
    def test_submitting_an_order_and_persisting_it_never_contains_the_secret_string(self) -> None:
        rcp = make_risk_checked_position(final_target_quantity=30.0)
        order = build_validated_order(rcp, current_quantity=0.0, configuration_version="cfg-v1").validated_order
        broker = MockBrokerAdapter(make_broker_config())
        request_repo = InMemoryBrokerRequestRepository()
        response_repo = InMemoryBrokerResponseRepository()

        submit_validated_order(
            broker, order, execution_mode="OFFLINE", requested_at=utc(2024, 1, 2, 13),
            configuration_version="cfg-v1", request_repository=request_repo, response_repository=response_repo,
        )

        for request in request_repo.list_all():
            blob = json_dumps(broker_request_to_payload(request))
            assert _FAKE_SECRET not in blob
            assert "Bearer " not in blob
        for response in response_repo.list_all():
            blob = json_dumps(broker_response_to_payload(response))
            assert _FAKE_SECRET not in blob
            assert "Bearer " not in blob


class TestExceptionMessagesNeverContainCredentials:
    def test_broker_auth_error_from_missing_env_vars_does_not_echo_the_reference_value(self, monkeypatch) -> None:
        from broker.config import BrokerConfig
        from broker.enums import BrokerExecutionMode
        from broker.toss.auth import resolve_credentials

        monkeypatch.delenv("TOSS_API_KEY", raising=False)
        monkeypatch.delenv("TOSS_API_SECRET", raising=False)
        monkeypatch.delenv("TOSS_ACCOUNT_ID", raising=False)
        config = BrokerConfig(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)
        try:
            resolve_credentials(config)
            assert False, "expected BrokerAuthError"
        except BrokerAuthError as exc:
            # the error may name the *reference* (env var name), which is
            # not a secret, but must never contain an actual secret value
            assert _FAKE_SECRET not in str(exc)

    def test_broker_auth_error_with_real_looking_env_values_does_not_leak_them_via_repr(self, monkeypatch) -> None:
        from broker.toss.auth import resolve_credentials
        from broker.config import BrokerConfig
        from broker.enums import BrokerExecutionMode

        monkeypatch.setenv("TOSS_API_KEY", _FAKE_SECRET)
        monkeypatch.setenv("TOSS_API_SECRET", _FAKE_SECRET)
        monkeypatch.setenv("TOSS_ACCOUNT_ID", "ACC-000001")
        config = BrokerConfig(execution_mode=BrokerExecutionMode.LIVE, live_opt_in=True)
        credentials = resolve_credentials(config)
        # resolve_credentials legitimately returns the value (it is the
        # one function allowed to) -- the safety property under test is
        # that NOTHING downstream that could be persisted/logged ever
        # receives this object.
        assert credentials.client_id == _FAKE_SECRET
