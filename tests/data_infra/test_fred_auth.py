"""Category: Secret Isolation Test -- `data_infra.providers.fred_auth`
is one of the fixed set of per-provider auth modules allowed to touch
`os.environ`/`os.getenv` in `data_infra.providers.*`
(`test_tiingo_auth.py`'s own `_ALLOWED_AUTH_FILES` set, updated here to
add `fred_auth.py`, is the actual repo-wide-scoped enforcement; this
file additionally exercises `resolve_api_key` itself, mirroring
`test_tiingo_auth.py`'s own `TestResolveApiKey`)."""

from __future__ import annotations

import pytest

from data_infra.provider import PermanentProviderError
from data_infra.providers.fred_auth import resolve_api_key
from data_infra.providers.fred_config import FredConfig


class TestResolveApiKey:
    def test_missing_key_raises_permanent_provider_error(self, monkeypatch) -> None:
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        with pytest.raises(PermanentProviderError):
            resolve_api_key(FredConfig())

    def test_present_key_is_returned(self, monkeypatch) -> None:
        monkeypatch.setenv("FRED_API_KEY", "test-key-123")
        assert resolve_api_key(FredConfig()) == "test-key-123"
