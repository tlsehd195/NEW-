"""Category: standalone factor score functions (strategy_research.
factor_scores) -- SYNTHETIC/PIPELINE-VALIDATION fixtures only (see
research_helpers.py's own docstring), never real strategy evidence.
Uses FLATLOW/FLATHIGH, the synthetic universe's own dedicated
low-vol/high-vol pair, built for exactly this kind of check."""

from __future__ import annotations

from datetime import date, datetime, timezone

from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from strategy_research.factor_scores import (
    leverage_score,
    low_volatility_score,
    net_margin_score,
    roa_score,
    roe_score,
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
