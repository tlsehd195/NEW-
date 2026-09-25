"""Tests for the one-shot `scripts/recon_corporate_action_providers.py`
reconnaissance tool (2026-09-25, run #44 corporate-action collection
failure). Real network calls are mocked at the `urllib.request.urlopen`
boundary -- same "nothing meaningful to assert about real, unknown
external content" discipline as `test_recon_kenneth_french_library.py`;
these tests only cover its own request/response plumbing and its
API-key-presence gating."""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "recon_corporate_action_providers.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("recon_corporate_action_providers", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, n: int) -> bytes:
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFetch:
    def test_returns_status_and_body_preview_on_success(self, monkeypatch) -> None:
        module = _load_module()
        monkeypatch.setattr(
            module.urllib.request, "urlopen",
            lambda request, timeout: _FakeResponse(200, b'{"meta": {}, "dividends": []}'),
        )
        status, body = module._fetch("https://example.com")
        assert status == 200
        assert "dividends" in body

    def test_http_error_returns_its_own_status_and_body(self, monkeypatch) -> None:
        module = _load_module()

        def _raise(request, timeout):
            raise urllib.error.HTTPError(
                "https://example.com", 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"premium endpoint")
            )

        monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
        status, body = module._fetch("https://example.com")
        assert status == 403
        assert "premium endpoint" in body

    def test_url_error_returns_none_status_with_the_reason(self, monkeypatch) -> None:
        module = _load_module()

        def _raise(request, timeout):
            raise urllib.error.URLError("egress blocked")

        monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
        status, body = module._fetch("https://example.com")
        assert status is None
        assert "egress blocked" in body


class TestMain:
    def test_main_never_calls_the_network_when_no_api_keys_are_set(self, monkeypatch, capsys) -> None:
        module = _load_module()
        monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
        monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
        called = []
        monkeypatch.setattr(module, "_fetch", lambda url: called.append(url) or (200, ""))

        exit_code = module.main()

        assert exit_code == 0
        assert called == []
        out = capsys.readouterr().out
        assert "TWELVEDATA_API_KEY not set" in out
        assert "ALPHAVANTAGE_API_KEY not set" in out

    def test_main_calls_each_candidate_once_per_configured_key_and_never_logs_the_key(self, monkeypatch, capsys) -> None:
        module = _load_module()
        monkeypatch.setenv("TWELVEDATA_API_KEY", "secret-twelvedata-key")
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "secret-alphavantage-key")
        monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
        called_urls = []

        def _fake_fetch(url):
            called_urls.append(url)
            return (200, "ok")

        monkeypatch.setattr(module, "_fetch", _fake_fetch)

        exit_code = module.main()

        assert exit_code == 0
        assert len(called_urls) == len(module._TWELVEDATA_CANDIDATES) + len(module._ALPHAVANTAGE_CANDIDATES)
        assert any("secret-twelvedata-key" in u for u in called_urls)
        assert any("secret-alphavantage-key" in u for u in called_urls)
        out = capsys.readouterr().out
        assert "secret-twelvedata-key" not in out
        assert "secret-alphavantage-key" not in out

    def test_sleeps_over_one_second_between_calls_within_the_same_provider(self, monkeypatch) -> None:
        """2026-09-25 follow-up: the first real run fired both Alpha
        Vantage candidates 4ms apart, and its SPLITS call came back
        with Alpha Vantage's own throttle notice instead of real data
        -- this pacing is what makes a re-run's answer trustworthy."""
        module = _load_module()
        monkeypatch.setenv("TWELVEDATA_API_KEY", "k1")
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "k2")
        monkeypatch.setattr(module, "_fetch", lambda url: (200, "ok"))
        sleep_calls = []
        monkeypatch.setattr(module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

        module.main()

        assert len(sleep_calls) == (len(module._TWELVEDATA_CANDIDATES) - 1) + (len(module._ALPHAVANTAGE_CANDIDATES) - 1)
        assert all(s > 1.0 for s in sleep_calls)
