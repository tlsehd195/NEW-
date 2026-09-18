"""Tests for the one-shot `scripts/recon_stockanalysis_delisted.py`
reconnaissance tool (docs/PROJECT_STATUS.md backlog item #1). Real
network calls are mocked at the `urllib.request.urlopen` boundary --
this script's whole purpose is to observe a real, external, unknown
response shape, so there is nothing meaningful to assert about real
content here; these tests only cover its own request/response
plumbing (status + body-prefix extraction, HTTPError/URLError
handling)."""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "recon_stockanalysis_delisted.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("recon_stockanalysis_delisted", _SCRIPT_PATH)
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
    def test_returns_status_and_body_prefix_on_success(self, monkeypatch) -> None:
        module = _load_module()
        monkeypatch.setattr(
            module.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(200, b"hello world")
        )
        status, body = module._fetch("https://example.com")
        assert status == 200
        assert body == "hello world"

    def test_truncates_body_to_the_preview_limit(self, monkeypatch) -> None:
        module = _load_module()
        monkeypatch.setattr(module, "_MAX_BODY_PREVIEW_BYTES", 5)
        monkeypatch.setattr(
            module.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(200, b"hello world")
        )
        status, body = module._fetch("https://example.com")
        assert status == 200
        assert body == "hello"

    def test_http_error_returns_its_own_status_and_body(self, monkeypatch) -> None:
        module = _load_module()

        def _raise(request, timeout):
            raise urllib.error.HTTPError(
                "https://example.com", 404, "Not Found", hdrs=None, fp=io.BytesIO(b"not found body")
            )

        monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
        status, body = module._fetch("https://example.com")
        assert status == 404
        assert body == "not found body"

    def test_url_error_returns_none_status_with_the_reason(self, monkeypatch) -> None:
        module = _load_module()

        def _raise(request, timeout):
            raise urllib.error.URLError("egress blocked")

        monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
        status, body = module._fetch("https://example.com")
        assert status is None
        assert "egress blocked" in body


class TestMain:
    def test_main_prints_a_section_per_candidate_url_and_returns_zero(self, monkeypatch, capsys) -> None:
        module = _load_module()
        monkeypatch.setattr(
            module, "_fetch", lambda url: (200, f"body for {url}")
        )
        exit_code = module.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        for url in module._CANDIDATE_URLS:
            assert url in out
