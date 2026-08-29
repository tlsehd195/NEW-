"""Category: standalone factor score functions (strategy_research.
factor_scores) -- SYNTHETIC/PIPELINE-VALIDATION fixtures only (see
research_helpers.py's own docstring), never real strategy evidence.
Uses FLATLOW/FLATHIGH, the synthetic universe's own dedicated
low-vol/high-vol pair, built for exactly this kind of check."""

from __future__ import annotations

from datetime import date, datetime, timezone

from research_helpers import synthetic_multi_year_repository

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from strategy_research.factor_scores import low_volatility_score


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
