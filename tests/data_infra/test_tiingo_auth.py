"""Category: Secret Isolation Test -- `data_infra.providers.tiingo_auth`/
`twelvedata_auth`/`alphavantage_auth` are the only places in
`data_infra.providers.*` allowed to touch `os.environ`/`os.getenv`,
mirroring `broker.toss.auth`'s identical Phase 13 discipline (ADR-0164
widened this from a single file to this fixed set of per-provider auth
modules, same isolation principle, one file per provider)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import data_infra.providers
from data_infra.provider import PermanentProviderError
from data_infra.providers.tiingo_auth import resolve_api_key
from data_infra.providers.tiingo_config import TiingoConfig

_ALLOWED_AUTH_FILES = {"tiingo_auth.py", "twelvedata_auth.py", "alphavantage_auth.py"}


class TestSecretsOnlyResolvedInTiingoAuth:
    def test_os_environ_appears_only_in_tiingo_auth(self) -> None:
        package_dir = Path(data_infra.providers.__file__).parent
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text())
            for node in ast.walk(tree):
                hits_environ = isinstance(node, ast.Attribute) and node.attr == "environ"
                hits_getenv = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getenv"
                if hits_environ or hits_getenv:
                    assert py_file.name in _ALLOWED_AUTH_FILES, f"{py_file.name} touches os.environ/os.getenv outside {_ALLOWED_AUTH_FILES}"


class TestResolveApiKey:
    def test_missing_key_raises_permanent_provider_error(self, monkeypatch) -> None:
        monkeypatch.delenv("MARKET_DATA_API_KEY", raising=False)
        with pytest.raises(PermanentProviderError):
            resolve_api_key(TiingoConfig())

    def test_present_key_is_returned(self, monkeypatch) -> None:
        monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key-123")
        assert resolve_api_key(TiingoConfig()) == "test-key-123"
