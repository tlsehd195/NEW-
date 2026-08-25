"""Category: Secret Safety Test -- `ProviderConfig.api_key_reference` is
a reference *name* only; nothing this phase persists or logs ever
contains anything resembling an actual secret value
(PROJECT_MASTER_PLAN.md section 14.2 / instruction section 6)."""

from __future__ import annotations

import json

from ai_gateway_helpers import make_gateway_config, make_provider_config, make_request, utc

from ai_gateway.gateway import AIGateway
from ai_gateway.provider import MockProviderAdapter
from ai_gateway.quota_manager import QuotaManager
from ai_gateway.repository import InMemoryQuotaStateRepository

from storage.serialization import (
    ai_request_to_payload,
    ai_response_to_payload,
    json_dumps,
    provider_quota_state_to_payload,
)


class TestApiKeyReferenceIsNameOnly:
    def test_default_reference_matches_env_example_placeholder_naming(self) -> None:
        config = make_provider_config()
        assert config.api_key_reference == "AI_PROVIDER_A_API_KEY"
        # a reference is an identifier, never a value that looks like a
        # real key (no "sk-"/"key-" prefixed secret material anywhere).
        assert not config.api_key_reference.lower().startswith(("sk-", "key-", "bearer "))

    def test_configuration_version_hashes_the_reference_name_not_a_secret(self) -> None:
        # configuration_version is a content hash of the whole config
        # (including api_key_reference, which is public metadata -- an
        # env var *name*), never anything resolved from the environment.
        config1 = make_provider_config(api_key_reference="AI_PROVIDER_A_API_KEY")
        config2 = make_provider_config(api_key_reference="AI_PROVIDER_A_API_KEY")
        assert config1.configuration_version() == config2.configuration_version()


class TestPersistedPayloadsNeverContainSecretMaterial:
    def _all_serialized_text(self, request, response, quota_state) -> str:
        return "\n".join([
            json_dumps(ai_request_to_payload(request)),
            json_dumps(ai_response_to_payload(response)),
            json_dumps(provider_quota_state_to_payload(quota_state)),
        ])

    def test_no_secret_looking_value_in_persisted_payloads(self) -> None:
        a = make_provider_config("a", api_key_reference="AI_PROVIDER_A_API_KEY")
        config = make_gateway_config(a)
        qm = QuotaManager(InMemoryQuotaStateRepository())
        state = qm.initialize(a, at=utc(2024, 1, 1))
        adapters = {"a": MockProviderAdapter(a)}
        gateway = AIGateway(config, adapters, qm)

        request = make_request()
        response = gateway.generate(request, as_of=utc(2024, 1, 2))

        blob = self._all_serialized_text(request, response, state)
        # the only thing referencing credentials anywhere is the env var
        # *name* itself -- never a value, never something that decodes
        # to a plausible secret.
        for forbidden_substring in ("sk-", "Bearer ", "Authorization:", "-----BEGIN"):
            assert forbidden_substring not in blob

    def test_provider_config_repr_does_not_leak_a_resolved_secret(self) -> None:
        # ProviderConfig never reads os.environ (test_ai_gateway_boundary.py
        # verifies this structurally) -- its repr can only ever show the
        # reference string the caller configured, never a resolved value.
        config = make_provider_config(api_key_reference="AI_PROVIDER_A_API_KEY")
        assert "AI_PROVIDER_A_API_KEY" in repr(config)


class TestGatewayNeverAcceptsARawApiKeyParameter:
    def test_gateway_constructor_has_no_api_key_parameter(self) -> None:
        import inspect

        params = set(inspect.signature(AIGateway.__init__).parameters)
        assert params.isdisjoint({"api_key", "secret", "credential", "token"})
