"""Category: Secret Isolation Test -- `ai_gateway.providers.gemini_auth`
is the only file in `ai_gateway.providers.*` allowed to touch
`os.environ`/`os.getenv`, mirroring `data_infra.providers.tiingo_auth`'s
identical discipline (see `tests/data_infra/test_tiingo_auth.py`)."""

from __future__ import annotations

import pytest
from ai_gateway_helpers import make_provider_config

from ai_gateway.provider import ProviderAuthError
from ai_gateway.providers.gemini_auth import resolve_api_key


class TestResolveApiKey:
    def test_missing_key_raises_provider_auth_error(self, monkeypatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        config = make_provider_config("gemini", api_key_reference="GEMINI_API_KEY")
        with pytest.raises(ProviderAuthError):
            resolve_api_key(config)

    def test_empty_string_key_raises_provider_auth_error(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        config = make_provider_config("gemini", api_key_reference="GEMINI_API_KEY")
        with pytest.raises(ProviderAuthError):
            resolve_api_key(config)

    def test_present_key_is_returned(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
        config = make_provider_config("gemini", api_key_reference="GEMINI_API_KEY")
        assert resolve_api_key(config) == "test-key-123"

    def test_resolves_by_the_configured_reference_name_not_a_hardcoded_one(self, monkeypatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("SOME_OTHER_NAME", "test-key-456")
        config = make_provider_config("gemini", api_key_reference="SOME_OTHER_NAME")
        assert resolve_api_key(config) == "test-key-456"
