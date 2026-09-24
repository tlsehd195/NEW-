"""Real, executable tests for `scripts/fetch_fmp_delisted_prices.py`'s
exit-code honesty (Batch J, independent audit R3 P2-6).

Never makes a real network call -- `_fetch` is monkeypatched.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fetch_fmp_delisted_prices.py"


def _load():
    spec = importlib.util.spec_from_file_location("fetch_fmp_delisted_prices", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_intervals_csv(path: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = ["ticker,start_date,end_date"] + [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")


class TestExitCodeReflectsRealCoverage:
    def test_every_candidate_failing_to_fetch_exits_nonzero(self, tmp_path, monkeypatch) -> None:
        """Batch J P2-6: an invalid API key makes every real candidate
        raise inside `_fetch` -- before this fix, the script still
        printed a report and returned 0, an operational lie."""
        module = _load()
        csv_path = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(csv_path, [("ZZZZ", "2015-01-01", "2020-06-30")])

        def _always_fails(symbol, api_key, *, from_date, to_date, timeout):
            raise RuntimeError("HTTP 401")

        monkeypatch.setattr(module, "_fetch", _always_fails)

        rc = module.main([
            "--sp500-intervals-csv", str(csv_path),
            "--since", "2015-01-01",
            "--out-dir", str(tmp_path / "out"),
            "--report-out", str(tmp_path / "report.json"),
            "--api-key", "bad-key",
            "--sleep-seconds", "0",
        ])
        assert rc == 1

    def test_at_least_one_covered_candidate_exits_zero_even_if_not_a_genuine_delisting(self, tmp_path, monkeypatch) -> None:
        module = _load()
        csv_path = tmp_path / "sp500_ticker_start_end.csv"
        _write_intervals_csv(csv_path, [("AAA", "2015-01-01", "2020-06-30")])

        def _real_data(symbol, api_key, *, from_date, to_date, timeout):
            return [
                {"date": "2020-06-25", "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "volume": 1000, "adjOpen": 10.0, "adjHigh": 10.5, "adjLow": 9.5, "adjClose": 10.0},
                {"date": "2020-06-26", "open": 10.1, "high": 10.6, "low": 9.6, "close": 10.1, "volume": 1000, "adjOpen": 10.1, "adjHigh": 10.6, "adjLow": 9.6, "adjClose": 10.1},
            ]

        monkeypatch.setattr(module, "_fetch", _real_data)

        rc = module.main([
            "--sp500-intervals-csv", str(csv_path),
            "--since", "2015-01-01",
            "--out-dir", str(tmp_path / "out"),
            "--report-out", str(tmp_path / "report.json"),
            "--api-key", "real-key",
            "--sleep-seconds", "0",
        ])
        assert rc == 0
