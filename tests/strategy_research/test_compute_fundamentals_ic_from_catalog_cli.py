"""Real, executable tests for
`scripts/compute_fundamentals_ic_from_catalog.py` -- mirrors
`test_compute_signal_ic_from_catalog_cli.py`'s structure exactly,
adapted for two separate DuckDB catalogs (price + fundamentals) instead
of one. TEST-1 refusal is the safety-critical path (no override flag),
plus an end-to-end run against small synthetic catalogs proving the
script actually computes something for a safe (pre-TEST-1) range.

Uses real `PILOT_UNIVERSE_V1` symbol IDs with SYNTHETIC price and
fundamentals data ingested locally -- proves the CLI mechanism and the
TEST-1 guard work correctly, not a claim about any real ROE result."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

from backtest_helpers import make_bars, trading_days
from storage_helpers import new_engine

from data_infra.calendar import US_EQUITY
from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance
from data_infra.universe import PILOT_UNIVERSE_V1

from storage.data_repository import DuckDBDataRepository
from storage.fundamentals_repository import DuckDBFundamentalsRepository

from strategy_research.locked_windows import TEST_1

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "compute_fundamentals_ic_from_catalog.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("compute_fundamentals_ic_from_catalog", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fy_record(security_id, record_id, *, concept, value, period_end):
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=period_end, ingestion_time=period_end,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=period_end, data_version="v1",
        ),
    )


class TestTest1Refusal:
    """The safety-critical path -- no override flag exists, so this
    must be verified directly, not merely trusted from the module
    docstring."""

    def test_refuses_a_range_identical_to_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--start", TEST_1.start.date().isoformat(),
            "--end", TEST_1.end.date().isoformat(),
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_refuses_a_range_partially_overlapping_test_1(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--start", "2022-01-01",
            "--end", "2024-01-01",
        ])
        assert exit_code == 1
        assert "LOCKED" in capsys.readouterr().err

    def test_default_end_is_test_1_start_and_is_therefore_safe(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--start", "2010-01-01",
        ])
        assert exit_code == 0  # ran (against empty catalogs -- N/A IC, not a refusal)

    def test_a_range_entirely_before_test_1_is_not_refused(self, tmp_path) -> None:
        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--start", "2010-01-01",
            "--end", "2015-01-01",
        ])
        assert exit_code == 0


class TestEndToEndAgainstSyntheticCatalogs:
    def test_computes_an_ic_summary_against_real_universe_symbols(self, tmp_path, capsys) -> None:
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        strong_closes = [100.0 * (1.0008**i) for i in range(len(days))]
        weak_closes = [100.0 * (0.9995**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]

        price_engine = new_engine(tmp_path, name="price")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbols[0], days, strong_closes))
        price_repo.append_bars(make_bars(symbols[1], days, weak_closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        for security_id, (income, equity) in {symbols[0]: (30.0, 100.0), symbols[1]: (3.0, 100.0)}.items():
            fundamentals_repo.add_fundamental(
                _fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=income, period_end=datetime(2017, 12, 31, tzinfo=timezone.utc))
            )
            fundamentals_repo.add_fundamental(
                _fy_record(security_id, f"{security_id}:eq", concept="StockholdersEquity", value=equity, period_end=datetime(2017, 12, 31, tzinfo=timezone.utc))
            )
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--universe", "PILOT_UNIVERSE",
            "--score", "roe",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "Fundamentals Signal IC: roe" in out

    def test_the_other_three_score_options_also_run_end_to_end(self, tmp_path, capsys) -> None:
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]

        price_engine = new_engine(tmp_path, name="price2")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbols[0], days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals2")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        period_end = datetime(2017, 12, 31, tzinfo=timezone.utc)
        for concept, value in (
            ("NetIncomeLoss", 15.0), ("StockholdersEquity", 100.0),
            ("Assets", 200.0), ("Liabilities", 100.0), ("Revenues", 150.0),
        ):
            fundamentals_repo.add_fundamental(
                _fy_record(symbols[0], f"{symbols[0]}:{concept}", concept=concept, value=value, period_end=period_end)
            )
        fundamentals_engine.close()

        module = _load_script()
        for score in ("roa", "net_margin", "leverage"):
            exit_code = module.main([
                "--price-db-path", str(tmp_path / "price2"),
                "--fundamentals-db-path", str(tmp_path / "fundamentals2"),
                "--universe", "PILOT_UNIVERSE",
                "--score", score,
                "--start", "2018-06-01",
                "--end", "2019-01-01",
                "--step-months", "1",
                "--horizon-days", "20",
            ])
            assert exit_code == 0
            assert f"Fundamentals Signal IC: {score}" in capsys.readouterr().out

    def test_asset_growth_score_option_runs_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 8. Needs its own fixture
        (unlike the loop above): `asset_growth_score` is a YoY change,
        so it needs two distinct fiscal years of `Assets`, not the one
        period the other three scores' shared fixture supplies."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]

        price_engine = new_engine(tmp_path, name="price3")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbols[0], days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals3")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        fundamentals_repo.add_fundamental(
            _fy_record(symbols[0], f"{symbols[0]}:assets_2016", concept="Assets", value=180.0, period_end=datetime(2016, 12, 31, tzinfo=timezone.utc))
        )
        fundamentals_repo.add_fundamental(
            _fy_record(symbols[0], f"{symbols[0]}:assets_2017", concept="Assets", value=200.0, period_end=datetime(2017, 12, 31, tzinfo=timezone.utc))
        )
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price3"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals3"),
            "--universe", "PILOT_UNIVERSE",
            "--score", "asset_growth",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 0
        assert "Fundamentals Signal IC: asset_growth" in capsys.readouterr().out

    def test_piotroski_score_option_runs_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 9. Needs its own fixture:
        9 concepts (8 of them across 2 fiscal years) rather than the
        single-period fixture the other scores share."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]
        symbol = symbols[0]

        price_engine = new_engine(tmp_path, name="price4")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbol, days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals4")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        prior_end = datetime(2016, 12, 31, tzinfo=timezone.utc)
        current_end = datetime(2017, 12, 31, tzinfo=timezone.utc)
        two_year_values = {
            "NetIncomeLoss": (10.0, 20.0), "Assets": (100.0, 120.0), "LongTermDebtNoncurrent": (40.0, 20.0),
            "AssetsCurrent": (50.0, 90.0), "LiabilitiesCurrent": (40.0, 60.0), "CommonStockSharesOutstanding": (100.0, 100.0),
            "Revenues": (200.0, 300.0), "CostOfGoodsAndServicesSold": (140.0, 180.0),
        }
        for concept, (prior_value, current_value) in two_year_values.items():
            fundamentals_repo.add_fundamental(
                _fy_record(symbol, f"{symbol}:{concept}:prior", concept=concept, value=prior_value, period_end=prior_end)
            )
            fundamentals_repo.add_fundamental(
                _fy_record(symbol, f"{symbol}:{concept}:current", concept=concept, value=current_value, period_end=current_end)
            )
        fundamentals_repo.add_fundamental(
            _fy_record(
                symbol, f"{symbol}:cfo:current", concept="NetCashProvidedByUsedInOperatingActivities",
                value=25.0, period_end=current_end,
            )
        )
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price4"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals4"),
            "--universe", "PILOT_UNIVERSE",
            "--score", "piotroski",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 0
        assert "Fundamentals Signal IC: piotroski" in capsys.readouterr().out

    def test_shareholder_yield_score_option_runs_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 10. The first score routed
        through `compute_hybrid_ic_series` instead of `compute_
        fundamentals_ic_series` (main()'s `_HYBRID_SCORES` branch) --
        this is the regression guard that the CLI's branching actually
        wires that path correctly end to end, not just that the two
        functions are individually correct in isolation."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]
        symbol = symbols[0]

        price_engine = new_engine(tmp_path, name="price5")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbol, days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals5")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        period_end = datetime(2017, 12, 31, tzinfo=timezone.utc)
        fundamentals_repo.add_fundamental(
            _fy_record(symbol, f"{symbol}:shares", concept="CommonStockSharesOutstanding", value=1_000_000.0, period_end=period_end)
        )
        fundamentals_repo.add_fundamental(
            _fy_record(symbol, f"{symbol}:div", concept="PaymentsOfDividends", value=500_000.0, period_end=period_end)
        )
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price5"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals5"),
            "--universe", "PILOT_UNIVERSE",
            "--score", "shareholder_yield",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 0
        assert "Fundamentals Signal IC: shareholder_yield" in capsys.readouterr().out

    def test_sloan_accruals_and_dividend_growth_options_run_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 11. Both share the shared
        two-fiscal-year-fixture shape asset_growth_score's own CLI test
        uses (they need zero new XBRL concepts beyond what earlier
        scores already ingest), so one fixture serves both."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]
        symbol = symbols[0]

        price_engine = new_engine(tmp_path, name="price6")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbol, days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals6")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        prior_end = datetime(2016, 12, 31, tzinfo=timezone.utc)
        current_end = datetime(2017, 12, 31, tzinfo=timezone.utc)
        for concept, (prior_value, current_value) in {
            "NetIncomeLoss": (10.0, 20.0), "Assets": (180.0, 200.0), "PaymentsOfDividends": (30.0, 40.0),
        }.items():
            fundamentals_repo.add_fundamental(
                _fy_record(symbol, f"{symbol}:{concept}:prior", concept=concept, value=prior_value, period_end=prior_end)
            )
            fundamentals_repo.add_fundamental(
                _fy_record(symbol, f"{symbol}:{concept}:current", concept=concept, value=current_value, period_end=current_end)
            )
        fundamentals_repo.add_fundamental(
            _fy_record(symbol, f"{symbol}:cfo:current", concept="NetCashProvidedByUsedInOperatingActivities", value=25.0, period_end=current_end)
        )
        fundamentals_engine.close()

        module = _load_script()
        for score in ("sloan_accruals", "dividend_growth"):
            exit_code = module.main([
                "--price-db-path", str(tmp_path / "price6"),
                "--fundamentals-db-path", str(tmp_path / "fundamentals6"),
                "--universe", "PILOT_UNIVERSE",
                "--score", score,
                "--start", "2018-06-01",
                "--end", "2019-01-01",
                "--step-months", "1",
                "--horizon-days", "20",
            ])
            assert exit_code == 0
            assert f"Fundamentals Signal IC: {score}" in capsys.readouterr().out

    def test_earnings_yield_score_option_runs_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 11. The second score routed
        through compute_hybrid_ic_series (after shareholder_yield) --
        regression guard that the CLI actually wires this path for
        earnings_yield too, not just shareholder_yield."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]
        symbol = symbols[0]

        price_engine = new_engine(tmp_path, name="price7")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbol, days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals7")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        period_end = datetime(2017, 12, 31, tzinfo=timezone.utc)
        fundamentals_repo.add_fundamental(
            _fy_record(symbol, f"{symbol}:ni", concept="NetIncomeLoss", value=5_000_000.0, period_end=period_end)
        )
        fundamentals_repo.add_fundamental(
            _fy_record(symbol, f"{symbol}:shares", concept="CommonStockSharesOutstanding", value=1_000_000.0, period_end=period_end)
        )
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price7"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals7"),
            "--universe", "PILOT_UNIVERSE",
            "--score", "earnings_yield",
            "--start", "2018-06-01",
            "--end", "2019-01-01",
            "--step-months", "1",
            "--horizon-days", "20",
        ])
        assert exit_code == 0
        assert "Fundamentals Signal IC: earnings_yield" in capsys.readouterr().out

    def test_quality_minus_junk_and_value_composite_options_run_end_to_end(self, tmp_path, capsys) -> None:
        """Session 36 -- ADR-0043 Decision 12. The first two scores
        routed through compute_universe_ic_series (main()'s
        _UNIVERSE_SCORES branch) -- needs >= 2 symbols with real data
        (unlike every earlier single-symbol CLI fixture), since both
        composites need a cross-section of at least 2 scorable
        securities to produce anything."""
        days = trading_days(date(2018, 1, 2), date(2019, 6, 1))
        closes = [100.0 * (1.0005**i) for i in range(len(days))]
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:2]

        price_engine = new_engine(tmp_path, name="price8")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        for symbol in symbols:
            price_repo.append_bars(make_bars(symbol, days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals8")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        period_end = datetime(2017, 12, 31, tzinfo=timezone.utc)
        prior_end = datetime(2016, 12, 31, tzinfo=timezone.utc)
        for symbol in symbols:
            for concept, value in (
                ("NetIncomeLoss", 50.0), ("StockholdersEquity", 500.0), ("Liabilities", 100.0),
                ("Revenues", 200.0), ("NetCashProvidedByUsedInOperatingActivities", 60.0),
                ("PaymentsOfDividends", 30.0), ("CommonStockSharesOutstanding", 1_000_000.0),
            ):
                fundamentals_repo.add_fundamental(
                    _fy_record(symbol, f"{symbol}:{concept}", concept=concept, value=value, period_end=period_end)
                )
            fundamentals_repo.add_fundamental(
                _fy_record(symbol, f"{symbol}:Assets:prior", concept="Assets", value=300.0, period_end=prior_end)
            )
            fundamentals_repo.add_fundamental(
                _fy_record(symbol, f"{symbol}:Assets:current", concept="Assets", value=300.0, period_end=period_end)
            )
        fundamentals_engine.close()

        module = _load_script()
        for score in ("quality_minus_junk", "value_composite"):
            exit_code = module.main([
                "--price-db-path", str(tmp_path / "price8"),
                "--fundamentals-db-path", str(tmp_path / "fundamentals8"),
                "--universe", "PILOT_UNIVERSE",
                "--score", score,
                "--start", "2018-06-01",
                "--end", "2019-01-01",
                "--step-months", "1",
                "--horizon-days", "20",
            ])
            assert exit_code == 0
            assert f"Fundamentals Signal IC: {score}" in capsys.readouterr().out
