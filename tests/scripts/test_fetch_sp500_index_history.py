"""Real, executable tests for `scripts/fetch_sp500_index_history.py`'s
zero-row exit-code honesty (Batch J, independent audit R3 P2-7).

Never makes a real network call -- `_fetch` is monkeypatched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fetch_sp500_index_history.py"


def _load():
    spec = importlib.util.spec_from_file_location("fetch_sp500_index_history", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestZeroRowGate:
    def test_a_header_only_response_exits_nonzero(self, tmp_path, monkeypatch) -> None:
        """Batch J P2-7: a truncated proxy response (or an upstream
        format change) that still has the right header but zero data
        rows parses "successfully" as zero intervals -- before this
        fix, the script still wrote a report and returned 0."""
        module = _load()
        monkeypatch.setattr(module, "_fetch", lambda url, *, timeout: "ticker,start_date,end_date\n")

        rc = module.main([
            "--as-of", "2024-01-02",
            "--out", str(tmp_path / "report.json"),
        ])
        assert rc == 1

    def test_a_real_response_with_rows_exits_zero(self, tmp_path, monkeypatch) -> None:
        module = _load()
        csv_text = "ticker,start_date,end_date\nAAA,2000-01-01,\nBBB,2000-01-01,2020-01-01\n"
        monkeypatch.setattr(module, "_fetch", lambda url, *, timeout: csv_text)

        out_path = tmp_path / "report.json"
        rc = module.main([
            "--as-of", "2024-01-02",
            "--out", str(out_path),
        ])
        assert rc == 0
        report = json.loads(out_path.read_text())
        assert report["interval_row_count"] == 2
