"""Real, executable tests for
`scripts/compute_filter_bucket_returns_from_catalog.py` -- mirrors
`test_compute_signal_ic_from_catalog_cli.py`'s structure: the TEST-1
refusal path is safety-critical and verified directly, plus a real
end-to-end run against a small synthetic DuckDB catalog.

Uses real `PILOT_UNIVERSE_V1` symbol IDs with SYNTHETIC price data --
proves the CLI mechanism and TEST-1 guard work correctly, not a claim
about `trend_volatility`'s real filter quality."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

from backtest_helpers import make_bars, trading_days
from storage_helpers import new_engine

from data_infra.calendar import US_EQUITY
from data_infra.universe import PILOT_UNIVERSE_V1
from storage.data_repository import DuckDBDataRepository
from strategy_research.locked_windows import TEST_1

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compute_filter_bucket_returns_from_catalog.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("compute_filter_bucket_returns_from_catalog", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTest1Refusal:
    def test_refuses_a_range_identical_to_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "nonexistent"),
            "--start", TEST_1.start.date().isoformat(),
            "--end", TEST_1.end.date().isoformat(),
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_refuses_a_range_partially_overlapping_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "nonexistent"),
            "--start", "2022-01-01",
            "--end", "2024-01-01",
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_default_end_is_test_1_start_and_is_therefore_safe(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--start", "2010-01-01",
        ])
        assert exit_code == 0

    def test_a_range_entirely_before_test_1_is_not_refused(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--start", "2010-01-01",
            "--end", "2015-01-01",
        ])
        assert exit_code == 0


class TestEndToEndAgainstSyntheticCatalog:
    def test_computes_bucket_returns_against_real_universe_symbols(self, tmp_path, capsys) -> None:
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        trendup_closes = [100.0 * (1.0008**i) for i in range(len(days))]
        trenddown_closes = [100.0 * (0.9995**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(symbols[0], days, trendup_closes))
        repo.append_bars(make_bars(symbols[1], days, trenddown_closes))
        engine.close()

        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--universe", "PILOT_UNIVERSE",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Filter bucket returns: trend_volatility" in out
