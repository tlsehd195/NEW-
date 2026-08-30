"""Category: dataset assembly correctness + leakage-field bookkeeping.
SYNTHETIC fixtures only."""

from __future__ import annotations

from datetime import date, timedelta

from helpers import utc
from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from ml.dataset import build_ml_dataset
from ml.features import build_price_feature_fns
from ml.target import HORIZON_DAYS
from strategy_research.factor_scores import leverage_score, net_margin_score, roa_score, roe_score


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


def _fundamentals_repo(tmp_path, security_ids):
    engine = new_engine(tmp_path)
    repo = DuckDBFundamentalsRepository(engine)
    for security_id in security_ids:
        repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=10.0))
        repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets", concept="Assets", value=100.0))
        repo.add_fundamental(_fy_record(security_id, f"{security_id}:eq", concept="StockholdersEquity", value=50.0))
        repo.add_fundamental(_fy_record(security_id, f"{security_id}:liab", concept="Liabilities", value=20.0))
        repo.add_fundamental(_fy_record(security_id, f"{security_id}:rev", concept="Revenues", value=200.0))
    return repo


_FUNDAMENTALS_FNS = {"roe": roe_score, "roa": roa_score, "net_margin": net_margin_score, "leverage": leverage_score}


class TestDatasetAssembly:
    def test_one_sample_per_security_per_valid_rebalance_date(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        rebalance_dates = [utc(2021, 1, 4), utc(2021, 4, 5)]

        samples = build_ml_dataset(
            universe, rebalance_dates, build_price_feature_fns(universe), _FUNDAMENTALS_FNS,
            price_repo, fundamentals_repo,
        )

        assert len(samples) == len(universe) * len(rebalance_dates)
        assert {s.security_id for s in samples} == set(universe)
        assert {s.as_of_time for s in samples} == set(rebalance_dates)

    def test_leakage_fields_are_consistent(self, tmp_path) -> None:
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        as_of_time = utc(2021, 1, 4)

        samples = build_ml_dataset(
            universe, [as_of_time], build_price_feature_fns(universe), _FUNDAMENTALS_FNS,
            price_repo, fundamentals_repo,
        )

        assert len(samples) == 1
        sample = samples[0]
        assert sample.feature_available_at == as_of_time
        assert sample.target_period_start == as_of_time
        assert sample.target_period_end == as_of_time + timedelta(days=HORIZON_DAYS)

    def test_excludes_security_with_no_fundamentals_data(self, tmp_path) -> None:
        universe = ("TRENDUP", "CYCLICAL")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, ["TRENDUP"])  # CYCLICAL gets no fundamentals
        as_of_time = utc(2021, 1, 4)

        samples = build_ml_dataset(
            universe, [as_of_time], build_price_feature_fns(universe), _FUNDAMENTALS_FNS,
            price_repo, fundamentals_repo,
        )

        assert {s.security_id for s in samples} == {"TRENDUP"}

    def test_excludes_dates_too_early_for_price_features_or_target(self, tmp_path) -> None:
        universe = ("TRENDUP",)
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        # 2020-01-03 is far too early for a 12-month momentum lookback.
        samples = build_ml_dataset(
            universe, [utc(2020, 1, 3)], build_price_feature_fns(universe), _FUNDAMENTALS_FNS,
            price_repo, fundamentals_repo,
        )
        assert samples == []
