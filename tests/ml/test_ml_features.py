"""Category: feature-vector assembly correctness + no-imputation
honesty. SYNTHETIC fixtures only (see research_helpers.py's own
docstring) -- pipeline-validation, never real-signal evidence."""

from __future__ import annotations

from datetime import date

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock
from helpers import utc
from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from ml.features import (
    FEATURE_IDS,
    build_price_feature_fns,
    compute_feature_vector,
)
from strategy_research.factor_scores import leverage_score, roa_score, roe_score, net_margin_score


def _fy_record(security_id, record_id, *, concept, value, period_end=utc(2019, 12, 31)):
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=period_end, ingestion_time=period_end,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=period_end, data_version="v1",
        ),
    )


def _fundamentals_repo(tmp_path, security_id):
    engine = new_engine(tmp_path)
    repo = DuckDBFundamentalsRepository(engine)
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=10.0))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets", concept="Assets", value=100.0))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:eq", concept="StockholdersEquity", value=50.0))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:liab", concept="Liabilities", value=20.0))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:rev", concept="Revenues", value=200.0))
    return repo


class TestFeatureVectorAssembly:
    def test_all_feature_ids_present_when_data_is_complete(self, tmp_path) -> None:
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, "TRENDUP")
        as_of_time = utc(2020, 6, 1)
        data_view = AsOfDataView(price_repo, BacktestClock(checkpoints=(as_of_time,)))

        price_fns = build_price_feature_fns(universe)
        fundamentals_fns = {"roe": roe_score, "roa": roa_score, "net_margin": net_margin_score, "leverage": leverage_score}

        vector = compute_feature_vector("TRENDUP", as_of_time, price_fns, data_view, fundamentals_fns, fundamentals_repo)

        assert vector is not None
        assert set(vector) == {"momentum", "low_volatility", "roe", "roa", "net_margin", "leverage"}
        assert set(vector) == set(FEATURE_IDS)

    def test_none_when_a_fundamentals_feature_is_missing(self, tmp_path) -> None:
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        empty_fundamentals_repo = DuckDBFundamentalsRepository(new_engine(tmp_path))
        as_of_time = utc(2020, 6, 1)
        data_view = AsOfDataView(price_repo, BacktestClock(checkpoints=(as_of_time,)))

        price_fns = build_price_feature_fns(universe)
        fundamentals_fns = {"roe": roe_score, "roa": roa_score, "net_margin": net_margin_score, "leverage": leverage_score}

        vector = compute_feature_vector("TRENDUP", as_of_time, price_fns, data_view, fundamentals_fns, empty_fundamentals_repo)
        assert vector is None

    def test_none_when_a_price_feature_is_missing(self, tmp_path) -> None:
        # Too early in history for a 12-month momentum lookback to have
        # enough bars -- momentum_score must return None, and the whole
        # vector must be None, not partially filled.
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, "TRENDUP")
        as_of_time = utc(2020, 1, 3)
        data_view = AsOfDataView(price_repo, BacktestClock(checkpoints=(as_of_time,)))

        price_fns = build_price_feature_fns(universe)
        fundamentals_fns = {"roe": roe_score, "roa": roa_score, "net_margin": net_margin_score, "leverage": leverage_score}

        vector = compute_feature_vector("TRENDUP", as_of_time, price_fns, data_view, fundamentals_fns, fundamentals_repo)
        assert vector is None
