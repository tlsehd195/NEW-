"""Real, executable tests for `scripts/select_delisted_candidates_since.py`.
No network call (reads a local CSV, same real schema
`parse_ticker_intervals` already validates elsewhere in this
repository's test suite)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "select_delisted_candidates_since.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("select_delisted_candidates_since", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CSV_TEXT = """ticker,start_date,end_date
AAA,2000-01-01,2010-05-01
BBB,2005-01-01,2021-03-15
CCC,2010-01-01,
DDD,2015-01-01,2023-07-01
"""


def _write_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "sp500_ticker_start_end.csv"
    csv_path.write_text(_CSV_TEXT)
    return csv_path


class TestSelectCandidates:
    def test_only_tickers_removed_on_or_after_since_are_selected(self, tmp_path) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        result = module.select_candidates(csv_path, date(2020, 1, 1))
        assert result == ["BBB", "DDD"]

    def test_still_listed_tickers_are_never_included(self, tmp_path) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        result = module.select_candidates(csv_path, date(2000, 1, 1))
        assert "CCC" not in result

    def test_earlier_since_includes_more_tickers(self, tmp_path) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        result = module.select_candidates(csv_path, date(2000, 1, 1))
        assert result == ["AAA", "BBB", "DDD"]


class TestMain:
    def test_prints_space_separated_sorted_tickers(self, tmp_path, capsys) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        exit_code = module.main(["--sp500-intervals-csv", str(csv_path), "--since", "2020-01-01"])
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == "BBB DDD"

    def test_default_since_is_2020_01_01(self, tmp_path, capsys) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        exit_code = module.main(["--sp500-intervals-csv", str(csv_path)])
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == "BBB DDD"

    def test_no_candidates_is_fatal_not_a_silent_empty_success(self, tmp_path, capsys) -> None:
        module = _load_module()
        csv_path = _write_csv(tmp_path)
        exit_code = module.main(["--sp500-intervals-csv", str(csv_path), "--since", "2099-01-01"])
        assert exit_code == 1
        assert "FATAL" in capsys.readouterr().err
