"""Category: model evaluation reuses the exact spearman_ic/
summarize_ic_observations machinery strategy_research.signal_ic already
uses for rule-based scores -- this is the only fair apples-to-apples
comparison against this project's existing factor-IC results.
SYNTHETIC fixtures only."""

from __future__ import annotations

from datetime import date

from helpers import utc
from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from ml.evaluate import evaluate_model_ic
from ml.features import build_price_feature_fns
from ml.linear_model import LinearRegressionModel
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


class _MomentumOnlyModel:
    """A hand-built stand-in for a fitted LinearRegressionModel: ranks
    purely by the momentum feature, positively weighted. Used instead
    of an actually-fit model so this test is about evaluate_model_ic's
    OWN correctness, not about whether OLS happens to fit well on this
    particular synthetic fixture."""

    def predict(self, features: dict) -> float:
        return features["momentum"]


class TestEvaluateModelIc:
    def test_perfectly_rank_predictive_model_scores_ic_plus_one(self, tmp_path) -> None:
        # TRENDUP always has higher momentum AND higher forward return
        # than TRENDDOWN by construction (research_helpers.py) -- with
        # exactly 2 securities per date, Spearman rank correlation is
        # always exactly +1 or -1, so a momentum-ranking model must
        # score +1 at every date.
        universe = ("TRENDUP", "TRENDDOWN")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        rebalance_dates = [utc(2021, 1, 4), utc(2021, 4, 5), utc(2021, 7, 5)]

        summary = evaluate_model_ic(
            _MomentumOnlyModel(), universe, rebalance_dates,
            build_price_feature_fns(universe), _FUNDAMENTALS_FNS, price_repo, fundamentals_repo,
        )

        assert summary.mean_ic == 1.0
        assert summary.positive_ic_ratio == 1.0
        assert len(summary.observations) == len(rebalance_dates)

    def test_fitted_model_produces_a_usable_summary(self, tmp_path) -> None:
        universe = ("TRENDUP", "TRENDDOWN", "CYCLICAL")
        price_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2023, 1, 3), symbols=universe)
        fundamentals_repo = _fundamentals_repo(tmp_path, universe)
        from ml.dataset import build_ml_dataset

        train_dates = [utc(2020, 6, 1), utc(2020, 9, 1)]
        val_dates = [utc(2021, 1, 4), utc(2021, 4, 5)]
        price_fns = build_price_feature_fns(universe)

        train_samples = build_ml_dataset(universe, train_dates, price_fns, _FUNDAMENTALS_FNS, price_repo, fundamentals_repo)
        model = LinearRegressionModel(feature_ids=["momentum", "low_volatility", "roe", "roa", "net_margin", "leverage"])
        model.fit(train_samples)

        summary = evaluate_model_ic(model, universe, val_dates, price_fns, _FUNDAMENTALS_FNS, price_repo, fundamentals_repo)

        assert summary.mean_ic is not None
        assert -1.0 <= summary.mean_ic <= 1.0
