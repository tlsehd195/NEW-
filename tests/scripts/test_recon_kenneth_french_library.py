"""Tests for the one-shot `scripts/recon_kenneth_french_library.py`
reconnaissance tool (docs/PROJECT_STATUS.md backlog item #7). Real
network calls are mocked at the `urllib.request.urlopen` boundary --
same "nothing meaningful to assert about real, unknown external
content" discipline as `test_recon_stockanalysis_delisted.py`; these
tests only cover its own request/response plumbing."""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "recon_kenneth_french_library.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("recon_kenneth_french_library", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self, n: int) -> bytes:
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFetch:
    def test_returns_status_content_type_and_byte_count_on_success(self, monkeypatch) -> None:
        module = _load_module()
        monkeypatch.setattr(
            module.urllib.request, "urlopen",
            lambda request, timeout: _FakeResponse(200, b"PK\x03\x04zip bytes", "application/zip"),
        )
        status, content_type, body_len = module._fetch("https://example.com")
        assert status == 200
        assert content_type == "application/zip"
        assert body_len == len(b"PK\x03\x04zip bytes")

    def test_http_error_returns_its_own_status(self, monkeypatch) -> None:
        module = _load_module()

        def _raise(request, timeout):
            raise urllib.error.HTTPError(
                "https://example.com", 404, "Not Found", hdrs=None, fp=io.BytesIO(b"not found")
            )

        monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
        status, content_type, body_len = module._fetch("https://example.com")
        assert status == 404
        assert body_len == len(b"not found")

    def test_url_error_returns_none_status_with_the_reason(self, monkeypatch) -> None:
        module = _load_module()

        def _raise(request, timeout):
            raise urllib.error.URLError("egress blocked")

        monkeypatch.setattr(module.urllib.request, "urlopen", _raise)
        status, content_type, body_len = module._fetch("https://example.com")
        assert status is None
        assert "egress blocked" in content_type
        assert body_len == 0


class TestMain:
    def test_main_prints_a_section_per_candidate_url_and_returns_zero(self, monkeypatch, capsys) -> None:
        module = _load_module()
        monkeypatch.setattr(module, "_fetch", lambda url: (200, "text/html", 100))
        exit_code = module.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        for url in module._CANDIDATE_URLS:
            assert url in out
