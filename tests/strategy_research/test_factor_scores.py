"""Category: standalone factor score functions (strategy_research.
factor_scores) -- SYNTHETIC/PIPELINE-VALIDATION fixtures only (see
research_helpers.py's own docstring), never real strategy evidence.
Uses FLATLOW/FLATHIGH, the synthetic universe's own dedicated
low-vol/high-vol pair, built for exactly this kind of check."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance, PriceBar
from data_infra.repository import InMemoryDataRepository

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from strategy_research.factor_scores import (
    asset_growth_score,
    leverage_score,
    low_volatility_score,
    net_margin_score,
    piotroski_f_score,
    roa_score,
    roe_score,
    shareholder_yield_score,
)


def _utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def _view(repo, as_of_time):
    return AsOfDataView(repo, BacktestClock(checkpoints=(as_of_time,)))


class TestLowVolatilityScore:
    def test_low_vol_security_scores_higher_than_high_vol_security(self) -> None:
        universe = ("FLATLOW", "FLATHIGH")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        low_score = low_volatility_score("FLATLOW", as_of_time, data)
        high_score = low_volatility_score("FLATHIGH", as_of_time, data)

        assert low_score is not None and high_score is not None
        assert low_score > high_score  # lower realized vol -> higher (more attractive) score

    def test_score_is_the_negative_of_annualized_volatility(self) -> None:
        universe = ("FLATLOW",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        score = low_volatility_score("FLATLOW", as_of_time, data)

        assert score is not None
        assert score < 0  # volatility is never negative, so its negation is never positive

    def test_insufficient_history_returns_none_not_a_fabricated_score(self) -> None:
        universe = ("FLATLOW",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2020, 1, 10), symbols=universe)
        as_of_time = _utc(2020, 1, 3)  # only ~1 trading day of history exists yet
        data = _view(repo, as_of_time)

        score = low_volatility_score("FLATLOW", as_of_time, data, lookback_days=126)

        assert score is None

    def test_unknown_security_returns_none(self) -> None:
        universe = ("FLATLOW",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        assert low_volatility_score("NONEXISTENT", as_of_time, data) is None

    def test_never_sees_data_past_its_own_as_of_time(self) -> None:
        # Regression guard: score at an early date must be identical
        # regardless of whether later history also exists in the repo.
        universe = ("FLATLOW",)
        early_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2020, 6, 1), symbols=universe)
        full_repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2022, 6, 1), symbols=universe)
        as_of_time = _utc(2020, 5, 1)

        score_early = low_volatility_score("FLATLOW", as_of_time, _view(early_repo, as_of_time))
        score_full = low_volatility_score("FLATLOW", as_of_time, _view(full_repo, as_of_time))

        assert score_early == score_full


def _fy_record(security_id, record_id, *, concept, value, period_end, available_time=None):
    available_time = available_time or period_end
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="FY", form_type="10-K", value=value, unit="USD",
        available_time=available_time, ingestion_time=available_time,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=available_time, data_version="v1",
        ),
    )


def _q_record(security_id, record_id, *, concept, value, period_end):
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period="Q2", form_type="10-Q", value=value, unit="USD",
        available_time=period_end, ingestion_time=period_end,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=period_end, data_version="v1",
        ),
    )


class TestRoeScore:
    """Category: Phase 33's first real fundamentals-based factor
    (ADR-0042) -- net income / stockholders' equity, restricted to
    annual (`fiscal_period == "FY"`) figures on both sides so a
    quarterly income figure is never divided by a full year's equity
    (see `factor_scores._latest_fiscal_year_value`'s own docstring for
    why that mismatch would silently understate ROE)."""

    def test_computes_net_income_over_equity(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))

        score = roe_score("AAA", _utc(2023, 6, 1), repo)
        assert score == 0.2

    def test_missing_net_income_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))

        assert roe_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_missing_equity_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))

        assert roe_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_zero_or_negative_equity_returns_none_not_a_fabricated_ratio(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=-5.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=-50.0, period_end=_utc(2022, 12, 31)))

        # -5 / -50 would compute to a spuriously positive 0.1 -- must be rejected instead.
        assert roe_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_quarterly_net_income_is_ignored_even_if_more_recent(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni_fy", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq_fy", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))
        # A more recent Q2 figure exists but must never be mixed with the FY equity.
        repo.add_fundamental(_q_record("AAA", "ni_q2", concept="NetIncomeLoss", value=6.0, period_end=_utc(2023, 6, 30)))

        score = roe_score("AAA", _utc(2023, 9, 1), repo)
        assert score == 0.2  # still the FY figure, not 6.0 / 100.0

    def test_picks_the_latest_fiscal_year_among_several(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni_2021", concept="NetIncomeLoss", value=10.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq_2021", concept="StockholdersEquity", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "ni_2022", concept="NetIncomeLoss", value=30.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq_2022", concept="StockholdersEquity", value=120.0, period_end=_utc(2022, 12, 31)))

        score = roe_score("AAA", _utc(2023, 6, 1), repo)
        assert score == 0.25  # 30 / 120, the 2022 figures, not 2021's

    def test_restated_figure_for_the_same_year_wins_by_later_filing(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(
            _fy_record("AAA", "ni_orig", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31), available_time=_utc(2023, 2, 1))
        )
        repo.add_fundamental(
            _fy_record("AAA", "ni_restated", concept="NetIncomeLoss", value=22.0, period_end=_utc(2022, 12, 31), available_time=_utc(2023, 6, 1))
        )
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))

        score = roe_score("AAA", _utc(2023, 12, 1), repo)
        assert score == 0.22  # the restated 22.0, not the original 20.0

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_later_fiscal_year(self, tmp_path) -> None:
        # Point-in-time correctness: a FY2023 figure filed in 2024 must
        # not be visible to a score computed mid-2023.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni_2022", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31), available_time=_utc(2023, 2, 1)))
        repo.add_fundamental(_fy_record("AAA", "eq_2022", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31), available_time=_utc(2023, 2, 1)))
        repo.add_fundamental(_fy_record("AAA", "ni_2023", concept="NetIncomeLoss", value=50.0, period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1)))
        repo.add_fundamental(_fy_record("AAA", "eq_2023", concept="StockholdersEquity", value=150.0, period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1)))

        score = roe_score("AAA", _utc(2023, 6, 1), repo)
        assert score == 0.2  # still the 2022 figures -- 2023's are not yet filed as of this date


class TestRoaScore:
    """`_fy_ratio`'s missing-value/zero-denominator/point-in-time
    behavior is already thoroughly covered by `TestRoeScore` above
    (shared helper) -- these tests only cover what is specific to
    `roa_score` itself: which concepts it divides."""

    def test_computes_net_income_over_assets(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=10.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets", concept="Assets", value=200.0, period_end=_utc(2022, 12, 31)))

        assert roa_score("AAA", _utc(2023, 6, 1), repo) == 0.05

    def test_zero_or_negative_assets_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=10.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets", concept="Assets", value=0.0, period_end=_utc(2022, 12, 31)))

        assert roa_score("AAA", _utc(2023, 6, 1), repo) is None


class TestNetMarginScore:
    def test_computes_net_income_over_revenues(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=15.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=100.0, period_end=_utc(2022, 12, 31)))

        assert net_margin_score("AAA", _utc(2023, 6, 1), repo) == 0.15

    def test_a_net_loss_produces_a_negative_margin_not_none(self, tmp_path) -> None:
        # Unlike a non-positive DENOMINATOR (rejected), a negative
        # NUMERATOR (a real net loss against positive revenue) is a
        # perfectly meaningful, real negative margin -- must not be
        # rejected.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=-5.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=100.0, period_end=_utc(2022, 12, 31)))

        assert net_margin_score("AAA", _utc(2023, 6, 1), repo) == -0.05

    def test_zero_or_negative_revenue_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=15.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=0.0, period_end=_utc(2022, 12, 31)))

        assert net_margin_score("AAA", _utc(2023, 6, 1), repo) is None


class TestLeverageScore:
    def test_score_is_the_negative_of_liabilities_over_equity(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "liab", concept="Liabilities", value=50.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))

        assert leverage_score("AAA", _utc(2023, 6, 1), repo) == -0.5

    def test_higher_leverage_scores_lower_matching_the_lower_is_more_attractive_convention(self, tmp_path) -> None:
        # record_id must be unique across ALL records in the repository
        # (it is the DB's own primary key, not scoped per security) --
        # prefixed with security_id here to avoid an accidental
        # cross-security collision silently dropping one security's row.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("LOW_LEVERAGE", "LOW_LEVERAGE:liab", concept="Liabilities", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("LOW_LEVERAGE", "LOW_LEVERAGE:eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("HIGH_LEVERAGE", "HIGH_LEVERAGE:liab", concept="Liabilities", value=80.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("HIGH_LEVERAGE", "HIGH_LEVERAGE:eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))

        low_score = leverage_score("LOW_LEVERAGE", _utc(2023, 6, 1), repo)
        high_score = leverage_score("HIGH_LEVERAGE", _utc(2023, 6, 1), repo)
        assert low_score > high_score  # lower leverage -> higher (more attractive) score

    def test_zero_or_negative_equity_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "liab", concept="Liabilities", value=50.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=-10.0, period_end=_utc(2022, 12, 31)))

        assert leverage_score("AAA", _utc(2023, 6, 1), repo) is None


class TestAssetGrowthScore:
    """Session 36 -- ADR-0043 Decision 8: the asset growth anomaly
    (Cooper, Gulen & Schill 2008). The only factor in this module that
    is a year-over-year CHANGE rather than a single-period ratio, so it
    needs its own dedicated point-in-time/insufficient-history coverage
    beyond what `TestRoeScore`'s shared `_fy_ratio` tests already give
    the level-based factors."""

    def test_score_is_the_negative_of_yoy_asset_growth(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "assets_2021", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        # (120/100 - 1) = 0.20 growth -> score is its negative
        assert asset_growth_score("AAA", _utc(2023, 6, 1), repo) == pytest.approx(-0.20)

    def test_shrinking_assets_produce_a_positive_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "assets_2021", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=90.0, period_end=_utc(2022, 12, 31)))

        score = asset_growth_score("AAA", _utc(2023, 6, 1), repo)
        assert score is not None and score > 0  # negative growth -> positive (more attractive) score

    def test_faster_growth_scores_lower_matching_the_lower_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("SLOW", "SLOW:assets_2021", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("SLOW", "SLOW:assets_2022", concept="Assets", value=105.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("FAST", "FAST:assets_2021", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("FAST", "FAST:assets_2022", concept="Assets", value=150.0, period_end=_utc(2022, 12, 31)))

        slow_score = asset_growth_score("SLOW", _utc(2023, 6, 1), repo)
        fast_score = asset_growth_score("FAST", _utc(2023, 6, 1), repo)
        assert slow_score > fast_score  # slower asset growth -> higher (more attractive) score

    def test_only_one_fiscal_year_known_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        assert asset_growth_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_zero_or_negative_prior_year_assets_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "assets_2021", concept="Assets", value=0.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        assert asset_growth_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_third_fiscal_year(self, tmp_path) -> None:
        # Point-in-time correctness: a FY2023 figure filed in 2024 must
        # not make this look like a 2-year-old comparison (2021 vs 2023)
        # once it exists -- as of mid-2023 only 2021/2022 are known.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "assets_2021", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31), available_time=_utc(2022, 2, 1)))
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31), available_time=_utc(2023, 2, 1)))
        repo.add_fundamental(_fy_record("AAA", "assets_2023", concept="Assets", value=300.0, period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1)))

        score = asset_growth_score("AAA", _utc(2023, 6, 1), repo)
        assert score == pytest.approx(-0.20)  # still 2021 vs 2022 -- 2023's figure is not yet filed


_PIOTROSKI_TWO_YEAR_CONCEPTS = (
    "NetIncomeLoss", "Assets", "LongTermDebtNoncurrent", "AssetsCurrent",
    "LiabilitiesCurrent", "CommonStockSharesOutstanding", "Revenues",
    "CostOfGoodsAndServicesSold",
)

_PIOTROSKI_ALL_IMPROVING = {
    "prior": {
        "NetIncomeLoss": 10.0, "Assets": 100.0, "LongTermDebtNoncurrent": 40.0,
        "AssetsCurrent": 50.0, "LiabilitiesCurrent": 40.0, "CommonStockSharesOutstanding": 100.0,
        "Revenues": 200.0, "CostOfGoodsAndServicesSold": 140.0,
    },
    "current": {
        "NetIncomeLoss": 20.0, "Assets": 120.0, "LongTermDebtNoncurrent": 20.0,
        "AssetsCurrent": 90.0, "LiabilitiesCurrent": 60.0, "CommonStockSharesOutstanding": 100.0,
        "Revenues": 300.0, "CostOfGoodsAndServicesSold": 180.0,
    },
    "cfo": 25.0,
}

_PIOTROSKI_ALL_WORSENING = {
    "prior": {
        "NetIncomeLoss": 20.0, "Assets": 100.0, "LongTermDebtNoncurrent": 20.0,
        "AssetsCurrent": 90.0, "LiabilitiesCurrent": 60.0, "CommonStockSharesOutstanding": 100.0,
        "Revenues": 300.0, "CostOfGoodsAndServicesSold": 180.0,
    },
    "current": {
        "NetIncomeLoss": -5.0, "Assets": 150.0, "LongTermDebtNoncurrent": 40.0,
        "AssetsCurrent": 50.0, "LiabilitiesCurrent": 80.0, "CommonStockSharesOutstanding": 120.0,
        "Revenues": 200.0, "CostOfGoodsAndServicesSold": 160.0,
    },
    "cfo": -10.0,
}


def _add_piotroski_fixture(
    repo, security_id, fixture, *, prior_period_end=_utc(2021, 12, 31), current_period_end=_utc(2022, 12, 31),
    include_cfo=True, omit_concepts=(), only_current_year_concepts=(),
) -> None:
    for concept in _PIOTROSKI_TWO_YEAR_CONCEPTS:
        if concept in omit_concepts:
            continue
        if concept not in only_current_year_concepts:
            repo.add_fundamental(_fy_record(
                security_id, f"{security_id}:{concept}:prior", concept=concept,
                value=fixture["prior"][concept], period_end=prior_period_end,
            ))
        repo.add_fundamental(_fy_record(
            security_id, f"{security_id}:{concept}:current", concept=concept,
            value=fixture["current"][concept], period_end=current_period_end,
        ))
    if include_cfo:
        repo.add_fundamental(_fy_record(
            security_id, f"{security_id}:cfo:current",
            concept="NetCashProvidedByUsedInOperatingActivities",
            value=fixture["cfo"], period_end=current_period_end,
        ))


class TestPiotroskiFScore:
    """Session 36 -- ADR-0043 Decision 9: Piotroski 2000's F-Score, the
    strongest-replicated candidate from the 12-strategy literature
    search. A 0-9 composite, all-or-nothing on missing data (matching
    this module's existing honesty discipline) -- these tests cover
    the full-9/full-0 extremes, the missing-data cases specific to a
    9-input composite (not covered by any single-ratio factor's own
    tests), and point-in-time correctness."""

    def test_all_nine_signals_improving_scores_nine(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(repo, "AAA", _PIOTROSKI_ALL_IMPROVING)

        assert piotroski_f_score("AAA", _utc(2023, 6, 1), repo) == 9.0

    def test_all_nine_signals_worsening_scores_zero(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(repo, "AAA", _PIOTROSKI_ALL_WORSENING)

        assert piotroski_f_score("AAA", _utc(2023, 6, 1), repo) == 0.0

    def test_higher_score_scores_higher_matching_the_higher_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(repo, "GOOD", _PIOTROSKI_ALL_IMPROVING)
        _add_piotroski_fixture(repo, "BAD", _PIOTROSKI_ALL_WORSENING)

        good_score = piotroski_f_score("GOOD", _utc(2023, 6, 1), repo)
        bad_score = piotroski_f_score("BAD", _utc(2023, 6, 1), repo)
        assert good_score > bad_score

    def test_missing_cash_flow_from_operations_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(repo, "AAA", _PIOTROSKI_ALL_IMPROVING, include_cfo=False)

        assert piotroski_f_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_missing_current_assets_returns_none(self, tmp_path) -> None:
        """The documented, foreseeable coverage gap for financial-sector
        filers (unclassified balance sheets don't report AssetsCurrent)
        -- simulated directly here rather than only asserted in prose."""
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(repo, "BANK", _PIOTROSKI_ALL_IMPROVING, omit_concepts=("AssetsCurrent",))

        assert piotroski_f_score("BANK", _utc(2023, 6, 1), repo) is None

    def test_only_one_fiscal_year_of_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(
            repo, "AAA", _PIOTROSKI_ALL_IMPROVING,
            only_current_year_concepts=("CommonStockSharesOutstanding",),
        )

        assert piotroski_f_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_zero_or_negative_current_liabilities_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        fixture = {
            "prior": dict(_PIOTROSKI_ALL_IMPROVING["prior"]),
            "current": dict(_PIOTROSKI_ALL_IMPROVING["current"]),
            "cfo": _PIOTROSKI_ALL_IMPROVING["cfo"],
        }
        fixture["current"]["LiabilitiesCurrent"] = 0.0
        _add_piotroski_fixture(repo, "AAA", fixture)

        assert piotroski_f_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_third_fiscal_year(self, tmp_path) -> None:
        # Point-in-time correctness, same discipline as roe_score/
        # asset_growth_score's own tests: a FY2023 figure filed in 2024
        # must not be visible to a score computed mid-2023.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_piotroski_fixture(
            repo, "AAA", _PIOTROSKI_ALL_IMPROVING,
            prior_period_end=_utc(2021, 12, 31), current_period_end=_utc(2022, 12, 31),
        )
        # A much stronger, not-yet-filed FY2023 that would change the
        # score if it leaked in.
        repo.add_fundamental(_fy_record(
            "AAA", "AAA:NetIncomeLoss:future", concept="NetIncomeLoss", value=-999.0,
            period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
        ))

        assert piotroski_f_score("AAA", _utc(2023, 6, 1), repo) == 9.0  # unchanged -- FY2023 not yet filed


def _price_bar(security_id, record_id, *, close, timestamp, adjusted_close=None):
    return PriceBar(
        security_id=security_id, timestamp=timestamp, open=close, high=close, low=close, close=close,
        volume=1000.0, available_time=timestamp, ingestion_time=timestamp,
        provenance=Provenance(
            source="test_provider", source_dataset=f"test_{security_id}",
            source_record_id=record_id, retrieved_at=timestamp, data_version="v1",
        ),
        adjusted_close=adjusted_close,
    )


class TestShareholderYieldScore:
    """Session 36 -- ADR-0043 Decision 10: Shareholder Yield
    (O'Shaughnessy; Boudoukh, Michaely, Richardson & Roberts 2007). The
    first factor in this module that needs price data at all (for
    market capitalization), so its signature and its tests both take a
    second, price repository beyond `fundamentals_repository` -- see
    `shareholder_yield_score`'s own docstring for why."""

    def test_computes_dividends_plus_buybacks_minus_issuance_over_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "div", concept="PaymentsOfDividends", value=200.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "buyback", concept="PaymentsForRepurchaseOfCommonStock", value=300.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "issuance", concept="ProceedsFromIssuanceOfCommonStock", value=100.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        # market_cap = 10.0 * 1000 = 10000; numerator = 200 + 300 - 100 = 400
        assert score == pytest.approx(0.04)

    def test_a_company_with_no_dividends_buybacks_or_issuance_scores_zero_not_none(self, tmp_path) -> None:
        # These three cash-flow concepts are only tagged by a filer WHEN
        # the activity happened -- their total absence is a genuine
        # zero, not missing data (see _fy_flow_or_zero's own docstring).
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == 0.0

    def test_missing_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "div", concept="PaymentsOfDividends", value=200.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_zero_or_negative_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=0.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[])

        assert shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_zero_or_negative_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=0.0, timestamp=_utc(2023, 5, 25))])

        assert shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_uses_raw_close_not_adjusted_close_for_market_cap(self, tmp_path) -> None:
        # adjusted_close is back-adjusted for corporate actions that
        # happen AFTER this bar's date (spec section 5.2) -- using it
        # here would silently pair a rescaled price with the actual
        # contemporaneous share count, producing a wrong market cap.
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "div", concept="PaymentsOfDividends", value=200.0, period_end=_utc(2022, 12, 31)))
        # A later 2:1 split has back-adjusted this bar's adjusted_close
        # to half the raw close -- market cap must still use the raw 10.0.
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, adjusted_close=5.0, timestamp=_utc(2023, 5, 25))])

        score = shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(200.0 / (10.0 * 1000.0))  # not 200.0 / (5.0 * 1000.0)

    def test_higher_shareholder_yield_scores_higher_matching_the_higher_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        for security_id, dividends in (("HIGH", 500.0), ("LOW", 50.0)):
            fundamentals_repo.add_fundamental(_fy_record(security_id, f"{security_id}:shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
            fundamentals_repo.add_fundamental(_fy_record(security_id, f"{security_id}:div", concept="PaymentsOfDividends", value=dividends, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[
            _price_bar("HIGH", "p1", close=10.0, timestamp=_utc(2023, 5, 25)),
            _price_bar("LOW", "p2", close=10.0, timestamp=_utc(2023, 5, 25)),
        ])

        high_score = shareholder_yield_score("HIGH", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        low_score = shareholder_yield_score("LOW", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert high_score > low_score

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_dividend_record(self, tmp_path) -> None:
        # Point-in-time correctness, same discipline as every other
        # factor in this module: a dividend record filed AFTER the
        # as_of_time must not affect the score.
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "div_2022", concept="PaymentsOfDividends", value=200.0, period_end=_utc(2022, 12, 31)))
        # A much larger FY2023 dividend, filed only in 2024 -- must not
        # be visible to a score computed mid-2023.
        fundamentals_repo.add_fundamental(_fy_record(
            "AAA", "div_2023", concept="PaymentsOfDividends", value=9000.0,
            period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
        ))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = shareholder_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(200.0 / 10000.0)  # still the 2022 dividend, not the future 9000.0
