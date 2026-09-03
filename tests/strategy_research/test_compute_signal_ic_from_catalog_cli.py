"""Real, executable tests for
`scripts/compute_signal_ic_from_catalog.py` -- the TEST-1 refusal
logic is the safety-critical part (no override flag exists, so this
must be verified directly rather than trusted from the docstring),
plus a real end-to-end run against a small synthetic DuckDB catalog
proving the script actually computes something when given a safe
(pre-TEST-1) date range.

Uses real `PILOT_UNIVERSE_V1` symbol IDs (AAPL, MSFT, ...) with
SYNTHETIC price data ingested locally -- proves the CLI mechanism and
the TEST-1 guard work correctly, not a claim about any real strategy
result."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

from backtest_helpers import make_bars, trading_days
from storage_helpers import new_engine

from data_infra.calendar import US_EQUITY
from data_infra.universe import BENCHMARK_SYMBOL, PILOT_UNIVERSE_V1
from storage.data_repository import DuckDBDataRepository
from strategy_research.locked_windows import TEST_1

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compute_signal_ic_from_catalog.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("compute_signal_ic_from_catalog", _SCRIPT_PATH)
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

    def test_never_includes_a_date_at_or_past_end(self) -> None:
        module = _load_script()
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = datetime(2020, 2, 1, tzinfo=timezone.utc)
        dates = module._rebalance_dates(start, end, step_months=1)
        assert all(d < end for d in dates)


class TestTest1Refusal:
    """The safety-critical path -- no override flag exists, so this
    must be verified directly, not merely trusted from the module
    docstring."""

    def test_refuses_a_range_identical_to_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "nonexistent"),
            "--strategy", "long_term_momentum",
            "--start", TEST_1.start.date().isoformat(),
            "--end", TEST_1.end.date().isoformat(),
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_refuses_a_range_partially_overlapping_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "nonexistent"),
            "--strategy", "long_term_momentum",
            "--start", "2022-01-01",
            "--end", "2024-01-01",
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_default_end_is_test_1_start_and_is_therefore_safe(self, tmp_path) -> None:
        # No --end passed: the default must NOT itself trigger a refusal.
        # StorageEngine self-initializes an empty catalog on first open
        # (config.ensure_dirs() + idempotent init_schema()), so no
        # separate setup is needed -- an empty catalog just yields N/A IC.
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--strategy", "long_term_momentum",
            "--start", "2010-01-01",
        ])
        assert exit_code == 0  # ran (against an empty catalog -- N/A IC, not a refusal)

    def test_a_range_entirely_before_test_1_is_not_refused(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--strategy", "long_term_momentum",
            "--start", "2010-01-01",
            "--end", "2015-01-01",
        ])
        assert exit_code == 0


class TestEndToEndAgainstSyntheticCatalog:
    def test_computes_an_ic_summary_against_real_universe_symbols(self, tmp_path, capsys) -> None:
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        trendup_closes = [100.0 * (1.0008**i) for i in range(len(days))]
        trenddown_closes = [100.0 * (0.9995**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]  # real universe IDs, e.g. AAPL/MSFT

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(symbols[0], days, trendup_closes))
        repo.append_bars(make_bars(symbols[1], days, trenddown_closes))
        engine.close()

        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--universe", "PILOT_UNIVERSE",
            "--strategy", "long_term_momentum",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Signal IC: long_term_momentum" in out
        assert "mean_ic=" in out

    def test_low_volatility_factor_option_also_runs_end_to_end(self, tmp_path, capsys) -> None:
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
        ])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Signal IC: low_volatility" in out

    def test_long_term_and_short_term_reversal_options_run_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 14. Both are price-only
        ScoreFn-shaped like low_volatility, so share one fixture (a
        3.5-year history so long_term_reversal's default 36-month
        lookback has enough trailing data)."""
        days = trading_days(date(2015, 1, 2), date(2019, 6, 1))
        trendup_closes = [100.0 * (1.0003**i) for i in range(len(days))]
        trenddown_closes = [100.0 * (0.9998**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(symbols[0], days, trendup_closes))
        repo.append_bars(make_bars(symbols[1], days, trenddown_closes))
        engine.close()

        module = _load_script()
        for strategy in ("long_term_reversal", "short_term_reversal"):
            exit_code = module.main([
                "--db-path", str(tmp_path / "store"),
                "--universe", "PILOT_UNIVERSE",
                "--strategy", strategy,
                "--start", "2018-06-01",
                "--end", "2019-01-01",
                "--step-months", "1",
                "--horizon-days", "20",
            ])
            assert exit_code == 0
            assert f"Signal IC: {strategy}" in capsys.readouterr().out

    def test_low_beta_option_runs_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 14. The one price-only score
        that also needs BENCHMARK_SYMBOL ("SPY") bars in the same
        catalog -- regression guard that the CLI's real DuckDB catalog
        (not just the in-memory unit fixtures in test_factor_scores.py)
        actually has SPY reachable via the same repository/get_bars
        path low_beta_score reads."""
        days = trading_days(date(2015, 1, 2), date(2019, 6, 1))
        spy_closes = [100.0 * (1.0003**i) for i in range(len(days))]
        security_closes = [100.0 * (1.0006**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(BENCHMARK_SYMBOL, days, spy_closes))
        repo.append_bars(make_bars(symbols[0], days, security_closes))
        engine.close()

        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--universe", "PILOT_UNIVERSE",
            "--strategy", "low_beta",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 0
        assert "Signal IC: low_beta" in capsys.readouterr().out

    def test_illiquidity_option_runs_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 15. Volume-based, not just
        price-based -- the CLI's real DuckDB catalog carries `volume`
        on every bar (`make_bars`'s own default), so this is also a
        regression guard that volume survives the catalog round-trip
        `illiquidity_score` now depends on for the first time in this
        module."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0 + 0.01 * ((-1) ** i)) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]

        engine = new_engine(tmp_path)
        repo = DuckDBDataRepository(engine, calendars={"US_EQUITY": US_EQUITY})
        repo.append_bars(make_bars(symbols[0], days, closes))
        engine.close()

        module = _load_script()
        exit_code = module.main([
            "--db-path", str(tmp_path / "store"),
            "--universe", "PILOT_UNIVERSE",
            "--strategy", "illiquidity",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 0
        assert "Signal IC: illiquidity" in capsys.readouterr().out
