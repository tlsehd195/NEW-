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
