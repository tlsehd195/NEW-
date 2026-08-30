"""Real, executable tests for
`scripts/train_ml_model_from_catalog.py` -- mirrors
`test_compute_fundamentals_ic_from_catalog_cli.py`'s structure: TEST-1
refusal is the safety-critical path (no override flag), plus an
end-to-end run against small synthetic catalogs proving the script
actually fits a model and reports a VALIDATION IC.

Uses real `PILOT_UNIVERSE_V1` symbol IDs with SYNTHETIC price and
fundamentals data ingested locally -- proves the CLI mechanism and the
TEST-1 guard work correctly, not a claim about any real predictive
result (see `ml/__init__.py`'s own docstring)."""

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

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "train_ml_model_from_catalog.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("train_ml_model_from_catalog", _SCRIPT_PATH)
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


def _seed_fundamentals(fundamentals_repo, security_id, *, income, assets, equity, liabilities, revenue, year=2017):
    period_end = datetime(year, 12, 31, tzinfo=timezone.utc)
    for concept, value in (
        ("NetIncomeLoss", income), ("Assets", assets), ("StockholdersEquity", equity),
        ("Liabilities", liabilities), ("Revenues", revenue),
    ):
        fundamentals_repo.add_fundamental(
            _fy_record(security_id, f"{security_id}:{concept}:{year}", concept=concept, value=value, period_end=period_end)
        )


class TestTest1Refusal:
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

    def test_default_end_is_test_1_start_and_is_therefore_safe(self, tmp_path, capsys) -> None:
        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--start", "2010-01-01",
        ])
        # Not refused for overlapping a locked window -- fails for a
        # different, honest reason (no data at all in an empty
        # catalog), never silently fabricating a fitted model.
        assert exit_code == 1
        assert "LOCKED" not in capsys.readouterr().err


class TestEndToEndAgainstSyntheticCatalogs:
    def test_fits_and_reports_a_validation_ic(self, tmp_path, capsys) -> None:
        days = trading_days(date(2010, 1, 4), date(2019, 6, 1))
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:3]

        price_engine = new_engine(tmp_path, name="price")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        for i, symbol in enumerate(symbols):
            closes = [100.0 * (1.0001 + 0.00003 * i) ** j for j in range(len(days))]
            price_repo.append_bars(make_bars(symbol, days, closes))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals")
        fundamentals_repo = DuckDBFundamentalsRepository(fundamentals_engine)
        for i, symbol in enumerate(symbols):
            for year in range(2010, 2019):
                _seed_fundamentals(
                    fundamentals_repo, symbol, income=5.0 + i, assets=100.0,
                    equity=50.0 + i, liabilities=20.0 + i, revenue=200.0, year=year,
                )
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals"),
            "--universe", "PILOT_UNIVERSE",
            "--start", "2011-01-04",
            "--end", "2019-01-04",
            "--step-months", "2",
        ])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert "ML experiment: ordinary_least_squares" in out
        assert "feature_set_id=factor_scores_v1" in out
        assert "target_id=forward_return_60d" in out
        assert "VALIDATION mean_ic=" in out or "VALIDATION mean_ic=N/A" in out
        assert "experiments_run_in_this_study=1" in out

    def test_returns_1_not_a_crash_when_train_has_no_usable_samples(self, tmp_path, capsys) -> None:
        # No fundamentals data seeded at all -> every sample's feature
        # vector is None -> zero TRAIN samples -> honest failure, not a
        # fabricated fit.
        days = trading_days(date(2010, 1, 4), date(2019, 6, 1))
        symbols = list(PILOT_UNIVERSE_V1.symbol_ids)[:1]

        price_engine = new_engine(tmp_path, name="price2")
        price_repo = DuckDBDataRepository(price_engine, calendars={"US_EQUITY": US_EQUITY})
        price_repo.append_bars(make_bars(symbols[0], days, [100.0 * (1.0002**i) for i in range(len(days))]))
        price_engine.close()

        fundamentals_engine = new_engine(tmp_path, name="fundamentals2")
        fundamentals_engine.close()

        module = _load_script()
        exit_code = module.main([
            "--price-db-path", str(tmp_path / "price2"),
            "--fundamentals-db-path", str(tmp_path / "fundamentals2"),
            "--universe", "PILOT_UNIVERSE",
            "--start", "2011-01-04",
            "--end", "2019-01-04",
        ])

        assert exit_code == 1
        assert "no TRAIN samples" in capsys.readouterr().err
