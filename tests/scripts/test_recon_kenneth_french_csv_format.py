"""Tests for the one-shot `scripts/recon_kenneth_french_csv_format.py`
follow-up recon tool. Same "mock at the urllib.request.urlopen
boundary, assert only own plumbing" discipline as
`test_recon_kenneth_french_library.py` -- the REAL CSV's exact layout
is unknown until this script is actually run against the real zip
(that is the whole point of this script), so these tests only prove it
correctly unzips, decodes, and prints whatever it is given."""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "recon_kenneth_french_csv_format.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("recon_kenneth_french_csv_format", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_zip(csv_name: str, csv_text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(csv_name, csv_text)
    return buffer.getvalue()


class TestMain:
    def test_prints_zip_contents_and_first_last_lines(self, monkeypatch, capsys) -> None:
        module = _load_module()
        csv_text = "\n".join([f"header line {i}" for i in range(20)] + [f"tail line {i}" for i in range(15)])
        zip_bytes = _fake_zip("F-F_Research_Data_Factors.CSV", csv_text)
        monkeypatch.setattr(
            module.urllib.request, "urlopen",
            lambda request, timeout: _FakeResponse(zip_bytes),
        )
        exit_code = module.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "F-F_Research_Data_Factors.CSV" in out
        assert "'header line 0'" in out
        assert "'tail line 14'" in out

    def test_finds_and_shows_context_around_the_first_blank_line(self, monkeypatch, capsys) -> None:
        module = _load_module()
        csv_text = "monthly line 1\nmonthly line 2\n\nannual line 1\nannual line 2"
        zip_bytes = _fake_zip("data.CSV", csv_text)
        monkeypatch.setattr(
            module.urllib.request, "urlopen",
            lambda request, timeout: _FakeResponse(zip_bytes),
        )
        exit_code = module.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "blank line indices (first 5): [2]" in out
        assert "'annual line 1'" in out

    def test_handles_no_blank_lines_at_all(self, monkeypatch, capsys) -> None:
        module = _load_module()
        csv_text = "line 1\nline 2\nline 3"
        zip_bytes = _fake_zip("data.CSV", csv_text)
        monkeypatch.setattr(
            module.urllib.request, "urlopen",
            lambda request, timeout: _FakeResponse(zip_bytes),
        )
        exit_code = module.main()
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "blank line indices (first 5): []" in out
