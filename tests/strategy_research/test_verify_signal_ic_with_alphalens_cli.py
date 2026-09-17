"""Real, executable tests for `scripts/verify_signal_ic_with_alphalens.py`
(Session 38, ADR-0139). Mirrors `tests/strategy_research/test_compute_
signal_ic_from_catalog_cli.py`'s own fixture shapes exactly (same
synthetic low/high-volatility catalog) since this script computes the
identical Signal IC, just cross-verified against `alphalens-reloaded`'s
own independent implementation too.

`--quantiles 2` throughout (not the CLI's own default of 5) -- both
fixtures here use exactly 2 securities, matching `alphalens.utils.
quantize_factor`'s own real requirement that quantile count not exceed
the number of distinct factor values available per rebalance date."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("alphalens", reason="optional [research] extra not installed")

from backtest_helpers import make_bars, trading_days
from storage_helpers import new_engine

from data_infra.calendar import US_EQUITY
from data_infra.universe import PILOT_UNIVERSE_V1
from storage.data_repository import DuckDBDataRepository
from strategy_research.locked_windows import TEST_1

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_signal_ic_with_alphalens.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_signal_ic_with_alphalens", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRebalanceDates:
    def test_steps_by_the_requested_month_interval(self) -> None:
        module = _load_script()
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = datetime(2020, 7, 1, tzinfo=timezone.utc)
        dates = module._rebalance_dates(start, end, step_months=2)
        assert [d.month for d in dates] == [1, 3, 5]


class TestTest1Refusal:
    """No override flag exists -- verified directly, not merely trusted
    from the module docstring, matching the sibling script's own
    precedent."""

    def test_refuses_a_range_identical_to_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "nonexistent"),
            "--strategy", "low_volatility",
            "--start", TEST_1.start.date().isoformat(),
            "--end", TEST_1.end.date().isoformat(),
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_default_end_is_test_1_start_and_is_therefore_safe(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--strategy", "low_volatility",
            "--start", "2010-01-01",
        ])
        # Empty catalog -> no rebalance-date data -> FATAL (exit 1),
        # but NOT because of the TEST_1 guard specifically.
        assert exit_code == 1
        assert "LOCKED" not in capsys.readouterr().err


class TestEndToEndAgainstSyntheticCatalog:
    def test_cross_verifies_low_volatility_against_a_real_synthetic_catalog(self, tmp_path, capsys) -> None:
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        low_vol_closes = [100.0 + 0.5 * ((-1) ** i) for i in range(len(days))]
        high_vol_closes = [100.0 * (1.0 + 0.06 * ((-1) ** i)) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(symbols[0], days, low_vol_closes))
        repo.append_bars(make_bars(symbols[1], days, high_vol_closes))
        engine.close()

        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--universe", "PILOT_UNIVERSE",
            "--strategy", "low_volatility",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
            "--quantiles", "2",
        ])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Signal IC cross-verification: low_volatility" in out
        assert "this project's own compute_ic_series" in out
        assert "alphalens-reloaded, independent implementation" in out

    def test_build_factor_and_prices_shapes_match_alphalens_expectations(self, tmp_path) -> None:
        """Direct check of the pure adapter function, isolated from the
        CLI -- `factor` must be a MultiIndex (date, asset) Series,
        `prices` a wide date x asset DataFrame, both real, non-empty."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(symbols[0], days, [100.0 + 0.5 * ((-1) ** i) for i in range(len(days))]))
        repo.append_bars(make_bars(symbols[1], days, [100.0 * (1.0 + 0.06 * ((-1) ** i)) for i in range(len(days))]))

        module = _load_script()
        score_fn = module._PRICE_ONLY_SCORES["low_volatility"]
        factor, prices = module.build_factor_and_prices(
            symbols, datetime(2018, 6, 1, tzinfo=timezone.utc), datetime(2019, 1, 1, tzinfo=timezone.utc),
            score_fn, repo, horizon_days=20,
        )
        engine.close()

        assert factor.index.names == ["date", "asset"]
        assert not factor.empty
        assert set(prices.columns) == set(symbols)
        assert not prices.empty


class TestInsufficientData:
    def test_empty_catalog_fails_cleanly_not_with_a_traceback(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--universe", "PILOT_UNIVERSE",
            "--strategy", "low_volatility",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 1
        assert "FATAL" in capsys.readouterr().err
