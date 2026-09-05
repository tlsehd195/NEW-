"""Category: standalone factor score functions (strategy_research.
factor_scores) -- SYNTHETIC/PIPELINE-VALIDATION fixtures only (see
research_helpers.py's own docstring), never real strategy evidence.
Uses FLATLOW/FLATHIGH, the synthetic universe's own dedicated
low-vol/high-vol pair, built for exactly this kind of check."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Optional

import pytest

from backtest_helpers import checkpoint, make_bars, trading_days
from research_helpers import synthetic_multi_year_repository
from storage_helpers import new_engine

from backtest.asof import AsOfDataView
from backtest.clock import BacktestClock

from data_infra.fundamentals_models import FundamentalRecord
from data_infra.models import Provenance, PriceBar
from data_infra.repository import InMemoryDataRepository
from data_infra.universe import BENCHMARK_SYMBOL

from storage.fundamentals_repository import DuckDBFundamentalsRepository

from strategy_research.factor_scores import (
    altman_z_score,
    asset_growth_score,
    book_to_market_score,
    cashflow_yield_score,
    combined_factor_score,
    dividend_growth_score,
    earnings_yield_score,
    fifty_two_week_high_score,
    gross_profitability_score,
    idiosyncratic_volatility_score,
    illiquidity_score,
    leverage_score,
    long_term_reversal_score,
    low_beta_score,
    low_volatility_score,
    max_effect_score,
    net_margin_score,
    piotroski_f_score,
    quality_minus_junk_score,
    rd_expenditure_score,
    residual_momentum_score,
    return_seasonality_score,
    roa_score,
    roe_score,
    rs_rating_score,
    sales_yield_score,
    shareholder_yield_score,
    short_term_reversal_score,
    size_score,
    sloan_accruals_score,
    sue_score,
    value_composite_score,
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


class TestLongTermReversalScore:
    """Session 36 -- ADR-0043 Decision 14: De Bondt & Thaler (1985)'s
    long-term reversal. A past LOSER should score higher (more
    attractive) than a past WINNER -- the opposite sign relationship
    from momentum, not a re-test of the already-null momentum result."""

    def test_past_loser_scores_higher_than_past_winner(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2016, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        winner_score = long_term_reversal_score("TRENDUP", as_of_time, data)
        loser_score = long_term_reversal_score("TRENDDOWN", as_of_time, data)

        assert winner_score is not None and loser_score is not None
        assert loser_score > winner_score  # worse past return -> higher (more attractive) score

    def test_score_is_the_negative_of_cumulative_return(self) -> None:
        universe = ("TRENDDOWN",)
        repo = synthetic_multi_year_repository(date(2016, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        score = long_term_reversal_score("TRENDDOWN", as_of_time, data)

        assert score is not None
        assert score > 0  # TRENDDOWN's cumulative return over the lookback is negative

    def test_insufficient_history_returns_none(self) -> None:
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2020, 1, 10), symbols=universe)
        as_of_time = _utc(2020, 1, 3)
        data = _view(repo, as_of_time)

        assert long_term_reversal_score("TRENDUP", as_of_time, data, lookback_months=36) is None

    def test_unknown_security_returns_none(self) -> None:
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2016, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        assert long_term_reversal_score("NONEXISTENT", as_of_time, data) is None


class TestRsRatingScore:
    """Session 36 continued -- O'Neil/IBD Relative Strength Rating,
    found while comparing this project against an external repository
    (dragon1086/prism-insight). `2*R63 + R126 + R189 + R252`, weighted
    toward the most recent quarter."""

    def test_past_winner_scores_higher_than_past_loser(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2016, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        winner_score = rs_rating_score("TRENDUP", as_of_time, data)
        loser_score = rs_rating_score("TRENDDOWN", as_of_time, data)

        assert winner_score is not None and loser_score is not None
        assert winner_score > loser_score  # unlike reversal, RS Rating rewards continued strength

    def test_positive_trend_scores_positive(self) -> None:
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2016, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        score = rs_rating_score("TRENDUP", as_of_time, data)

        assert score is not None and score > 0

    def test_insufficient_history_returns_none_not_a_fabricated_score(self) -> None:
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2020, 6, 1), symbols=universe)
        as_of_time = _utc(2020, 3, 2)  # well under 252 trading days of history
        data = _view(repo, as_of_time)

        assert rs_rating_score("TRENDUP", as_of_time, data) is None

    def test_unknown_security_returns_none(self) -> None:
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2016, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        assert rs_rating_score("NONEXISTENT", as_of_time, data) is None

    def test_recent_quarter_is_weighted_more_than_older_quarters(self) -> None:
        # A security flat for 3 quarters then sharply up in the most
        # recent quarter must score higher than one sharply up 3
        # quarters ago then flat since -- the "2x most recent quarter"
        # weighting is the entire point distinguishing this from a
        # plain equal-weighted trailing return.
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        recent_spike = [100.0] * (len(days) - 63) + [100.0 * (1.01**i) for i in range(63)]
        old_spike = [100.0 * (1.01**i) for i in range(63)] + [100.0 * (1.01**62)] * (len(days) - 63)
        repo = InMemoryDataRepository()
        repo.append_bars(make_bars("RECENTSPIKE", days, recent_spike))
        repo.append_bars(make_bars("OLDSPIKE", days, old_spike))
        as_of_time = checkpoint(days[-1])
        data = _view(repo, as_of_time)

        recent_score = rs_rating_score("RECENTSPIKE", as_of_time, data)
        old_score = rs_rating_score("OLDSPIKE", as_of_time, data)

        assert recent_score is not None and old_score is not None
        assert recent_score > old_score


class TestShortTermReversalScore:
    """Session 36 -- ADR-0043 Decision 14: Jegadeesh (1990)'s short-term
    (1-month) reversal -- same construction as long_term_reversal_score,
    a much shorter window."""

    def test_past_loser_scores_higher_than_past_winner(self) -> None:
        universe = ("TRENDUP", "TRENDDOWN")
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2021, 6, 1), symbols=universe)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        winner_score = short_term_reversal_score("TRENDUP", as_of_time, data)
        loser_score = short_term_reversal_score("TRENDDOWN", as_of_time, data)

        assert winner_score is not None and loser_score is not None
        assert loser_score > winner_score

    def test_insufficient_history_returns_none(self) -> None:
        universe = ("TRENDUP",)
        repo = synthetic_multi_year_repository(date(2020, 1, 2), date(2020, 1, 3), symbols=universe)
        as_of_time = _utc(2020, 1, 2)
        data = _view(repo, as_of_time)

        assert short_term_reversal_score("TRENDUP", as_of_time, data, lookback_months=1) is None


def _spy_repo(start: date, end: date, spy_closes_fn, *, extra_bars=()):
    """Builds an `InMemoryDataRepository` with a `BENCHMARK_SYMBOL`
    ("SPY") `PriceBar` series (the same regular price-bar pipeline
    real ingestion uses per `data_infra.universe`'s own module comment
    -- not the separate `BenchmarkPoint`/`get_benchmark` path
    `synthetic_multi_year_repository` populates, which `low_beta_score`
    does not read), plus any `extra_bars` for the security(ies) under
    test."""
    days = trading_days(start, end)
    spy_closes = [spy_closes_fn(i) for i in range(len(days))]
    bars = list(make_bars(BENCHMARK_SYMBOL, days, spy_closes)) + list(extra_bars)
    return InMemoryDataRepository(bars=bars)


class TestLowBetaScore:
    """Session 36 -- ADR-0043 Decision 14: Frazzini & Pedersen (2014)'s
    Betting Against Beta. A distinct construct from
    `low_volatility_score` -- market beta (covariance with SPY, divided
    by SPY's own variance), not total trailing volatility."""

    def test_low_beta_security_scores_higher_than_high_beta_security(self) -> None:
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        spy_closes = [100.0 * (1.0003**i) * (1.0 + 0.01 * math.sin(i / 10.0)) for i in range(len(days))]
        # HIGHBETA amplifies SPY's own moves (2x); LOWBETA dampens them (0.2x) -- both derived
        # directly from the same SPY path so their true betas are unambiguous by construction.
        high_beta_closes = [100.0 * (1.0 + 2.0 * (c / spy_closes[0] - 1.0)) for c in spy_closes]
        low_beta_closes = [100.0 * (1.0 + 0.2 * (c / spy_closes[0] - 1.0)) for c in spy_closes]
        extra_bars = list(make_bars("HIGHBETA", days, high_beta_closes)) + list(make_bars("LOWBETA", days, low_beta_closes))
        repo = _spy_repo(date(2019, 1, 2), date(2021, 6, 1), lambda i: spy_closes[i], extra_bars=extra_bars)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        high_score = low_beta_score("HIGHBETA", as_of_time, data)
        low_score = low_beta_score("LOWBETA", as_of_time, data)

        assert high_score is not None and low_score is not None
        assert low_score > high_score  # lower beta -> higher (more attractive) score

    def test_beta_of_the_benchmark_against_itself_is_approximately_one(self) -> None:
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        spy_closes = [100.0 * (1.0003**i) * (1.0 + 0.01 * math.sin(i / 10.0)) for i in range(len(days))]
        same_as_spy = list(make_bars("TWIN", days, spy_closes))
        repo = _spy_repo(date(2019, 1, 2), date(2021, 6, 1), lambda i: spy_closes[i], extra_bars=same_as_spy)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        score = low_beta_score("TWIN", as_of_time, data)

        assert score is not None
        assert score == pytest.approx(-1.0, abs=1e-6)  # beta of a security identical to the benchmark is 1

    def test_insufficient_paired_history_returns_none(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 1, 15))  # far fewer than the 20-observation floor
        spy_closes = [100.0 * (1.0003**i) for i in range(len(days))]
        extra_bars = list(make_bars("THIN", days, spy_closes))
        repo = _spy_repo(date(2021, 1, 2), date(2021, 1, 15), lambda i: spy_closes[i], extra_bars=extra_bars)
        as_of_time = _utc(2021, 1, 14)
        data = _view(repo, as_of_time)

        assert low_beta_score("THIN", as_of_time, data) is None

    def test_missing_benchmark_data_returns_none(self) -> None:
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        closes = [100.0 * (1.0003**i) for i in range(len(days))]
        repo = InMemoryDataRepository(bars=list(make_bars("NOBENCH", days, closes)))  # no SPY bars at all
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        assert low_beta_score("NOBENCH", as_of_time, data) is None


class TestIdiosyncraticVolatilityScore:
    """Session 36 -- literature search specifically for a candidate
    genuinely distinct from everything already tested (post-mortem on
    `size`/`altman_z`'s real results): Ang, Hodrick, Xing & Zhang
    (2006)'s idiosyncratic volatility anomaly. A distinct construct from
    BOTH `low_volatility_score` (total trailing volatility) AND
    `low_beta_score` (systematic co-movement alone) -- this is the
    residual, stock-specific volatility left over after a security's
    co-movement with the market is regressed out."""

    def test_a_security_perfectly_explained_by_beta_has_near_zero_idiosyncratic_volatility(self) -> None:
        # TWICEBETA is EXACTLY 2x SPY's own move every day -- no
        # idiosyncratic noise at all, so its CAPM residuals should be
        # ~0 regardless of its (nonzero) beta.
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        spy_closes = [100.0 * (1.0003**i) * (1.0 + 0.01 * math.sin(i / 10.0)) for i in range(len(days))]
        twice_beta_closes = [100.0 * (1.0 + 2.0 * (c / spy_closes[0] - 1.0)) for c in spy_closes]
        extra_bars = list(make_bars("TWICEBETA", days, twice_beta_closes))
        repo = _spy_repo(date(2019, 1, 2), date(2021, 6, 1), lambda i: spy_closes[i], extra_bars=extra_bars)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        score = idiosyncratic_volatility_score("TWICEBETA", as_of_time, data)

        assert score is not None
        assert score == pytest.approx(0.0, abs=1e-4)  # negative of ~0 residual stdev

    def test_a_security_with_real_idiosyncratic_noise_scores_lower_than_a_noise_free_one(self) -> None:
        # Both NOISY and CLEAN share the identical beta (1.0x SPY) --
        # only NOISY has stock-specific daily noise added on top, so
        # only idiosyncratic (not total or beta-driven) volatility
        # should distinguish them.
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        spy_closes = [100.0 * (1.0003**i) * (1.0 + 0.01 * math.sin(i / 10.0)) for i in range(len(days))]
        clean_closes = list(spy_closes)
        noisy_closes = [c * (1.0 + 0.03 * math.sin(i * 7.0)) for i, c in enumerate(spy_closes)]
        extra_bars = list(make_bars("CLEAN", days, clean_closes)) + list(make_bars("NOISY", days, noisy_closes))
        repo = _spy_repo(date(2019, 1, 2), date(2021, 6, 1), lambda i: spy_closes[i], extra_bars=extra_bars)
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        clean_score = idiosyncratic_volatility_score("CLEAN", as_of_time, data)
        noisy_score = idiosyncratic_volatility_score("NOISY", as_of_time, data)

        assert clean_score is not None and noisy_score is not None
        assert clean_score > noisy_score  # less idiosyncratic noise -> higher (more attractive) score

    def test_insufficient_paired_history_returns_none(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 1, 10))  # far fewer than the 15-observation floor
        spy_closes = [100.0 * (1.0003**i) for i in range(len(days))]
        extra_bars = list(make_bars("THIN", days, spy_closes))
        repo = _spy_repo(date(2021, 1, 2), date(2021, 1, 10), lambda i: spy_closes[i], extra_bars=extra_bars)
        as_of_time = _utc(2021, 1, 9)
        data = _view(repo, as_of_time)

        assert idiosyncratic_volatility_score("THIN", as_of_time, data) is None

    def test_missing_benchmark_data_returns_none(self) -> None:
        days = trading_days(date(2019, 1, 2), date(2021, 6, 1))
        closes = [100.0 * (1.0003**i) for i in range(len(days))]
        repo = InMemoryDataRepository(bars=list(make_bars("NOBENCH", days, closes)))  # no SPY bars at all
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        assert idiosyncratic_volatility_score("NOBENCH", as_of_time, data) is None


class TestResidualMomentumScore:
    """Session 36 continued -- Blitz, Huij & Martens 2011 Residual
    Momentum, found via a GitHub/web search for borrowable strategies
    (paperswithbacktest/awesome-systematic-trading). Beta/alpha are
    estimated on an EARLIER window and applied out-of-sample to a LATER
    formation window -- fitting and scoring on the identical window would
    make the residual mean exactly zero by construction (an OLS identity,
    not a data issue), so every fixture here gives WINNER/LOSER an
    IDENTICAL price path to SPY during the estimation portion (beta=1,
    alpha=0 by construction) and only diverges during the tail formation
    portion."""

    _FORMATION_TAIL_BARS = 64  # 63 formation returns, matching _RESIDUAL_MOMENTUM_FORMATION_DAYS

    def _build_closes(self, days, spy_closes, *, formation_epsilon_fn):
        """`formation_epsilon_fn(t)` (t = 0..62) gives the extra daily
        return WINNER/LOSER earns on top of SPY's own daily return during
        the last `_FORMATION_TAIL_BARS - 1` return steps; `None` closes
        (before the boundary) exactly mirror `spy_closes`."""
        boundary = len(days) - self._FORMATION_TAIL_BARS
        closes = list(spy_closes[:boundary])
        for i in range(boundary, len(days)):
            spy_return = spy_closes[i] / spy_closes[i - 1] - 1.0
            epsilon = formation_epsilon_fn(i - boundary - 1) if i > boundary else 0.0
            closes.append(closes[-1] * (1.0 + spy_return + epsilon))
        return closes

    def test_a_recent_out_of_sample_winner_scores_higher_than_a_recent_out_of_sample_loser(self) -> None:
        days = trading_days(date(2018, 1, 2), date(2021, 6, 1))
        spy_closes = [100.0 * (1.0003**i) * (1.0 + 0.01 * math.sin(i / 10.0)) for i in range(len(days))]
        winner_closes = self._build_closes(
            days, spy_closes, formation_epsilon_fn=lambda t: 0.01 + 0.005 * math.sin(t * 5.0),
        )
        loser_closes = self._build_closes(
            days, spy_closes, formation_epsilon_fn=lambda t: -0.01 + 0.005 * math.sin(t * 5.0),
        )
        repo = InMemoryDataRepository()
        repo.append_bars(make_bars(BENCHMARK_SYMBOL, days, spy_closes))
        repo.append_bars(make_bars("WINNER", days, winner_closes))
        repo.append_bars(make_bars("LOSER", days, loser_closes))
        as_of_time = checkpoint(days[-1])
        data = _view(repo, as_of_time)

        winner_score = residual_momentum_score("WINNER", as_of_time, data)
        loser_score = residual_momentum_score("LOSER", as_of_time, data)

        assert winner_score is not None and loser_score is not None
        assert winner_score > 0 > loser_score
        assert winner_score > loser_score

    def test_insufficient_paired_history_returns_none(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 3, 1))  # far fewer than the combined 240-observation floor
        spy_closes = [100.0 * (1.0003**i) for i in range(len(days))]
        extra_bars = list(make_bars("THIN", days, spy_closes))
        repo = _spy_repo(date(2021, 1, 2), date(2021, 3, 1), lambda i: spy_closes[i], extra_bars=extra_bars)
        as_of_time = _utc(2021, 2, 26)
        data = _view(repo, as_of_time)

        assert residual_momentum_score("THIN", as_of_time, data) is None

    def test_missing_benchmark_data_returns_none(self) -> None:
        days = trading_days(date(2018, 1, 2), date(2021, 6, 1))
        closes = [100.0 * (1.0003**i) for i in range(len(days))]
        repo = InMemoryDataRepository(bars=list(make_bars("NOBENCH", days, closes)))  # no SPY bars at all
        as_of_time = _utc(2021, 1, 4)
        data = _view(repo, as_of_time)

        assert residual_momentum_score("NOBENCH", as_of_time, data) is None


class TestIlliquidityScore:
    """Session 36 -- ADR-0043 Decision 15: Amihud (2002)'s illiquidity
    premium, |return|/dollar_volume averaged over the lookback. Higher
    illiquidity -> higher (more attractive) score, the one place in
    this module a "bad"-sounding quantity is NOT negated."""

    def test_low_volume_security_scores_higher_than_high_volume_security(self) -> None:
        days = trading_days(date(2019, 1, 2), date(2020, 6, 1))
        closes = [100.0 * (1.0 + 0.02 * math.sin(i / 5.0)) for i in range(len(days))]
        # Identical price/return series for both -- only volume differs, so
        # any score difference isolates illiquidity's dependence on volume.
        low_volume_bars = make_bars("THIN", days, closes, volume=1_000.0)
        high_volume_bars = make_bars("DEEP", days, closes, volume=10_000_000.0)
        repo = InMemoryDataRepository(bars=list(low_volume_bars) + list(high_volume_bars))
        as_of_time = _utc(2020, 1, 4)
        data = _view(repo, as_of_time)

        thin_score = illiquidity_score("THIN", as_of_time, data)
        deep_score = illiquidity_score("DEEP", as_of_time, data)

        assert thin_score is not None and deep_score is not None
        assert thin_score > deep_score  # lower dollar volume -> higher illiquidity -> higher (more attractive) score

    def test_insufficient_observations_returns_none(self) -> None:
        days = trading_days(date(2020, 1, 2), date(2020, 1, 20))  # far fewer than the 20-observation floor
        closes = [100.0 + i for i in range(len(days))]
        repo = InMemoryDataRepository(bars=list(make_bars("THIN", days, closes, volume=1_000.0)))
        as_of_time = _utc(2020, 1, 19)
        data = _view(repo, as_of_time)

        assert illiquidity_score("THIN", as_of_time, data, lookback_days=252) is None

    def test_unknown_security_returns_none(self) -> None:
        days = trading_days(date(2019, 1, 2), date(2020, 6, 1))
        closes = [100.0 + i * 0.01 for i in range(len(days))]
        repo = InMemoryDataRepository(bars=list(make_bars("THIN", days, closes, volume=1_000.0)))
        as_of_time = _utc(2020, 1, 4)
        data = _view(repo, as_of_time)

        assert illiquidity_score("NONEXISTENT", as_of_time, data) is None


class TestFiftyTwoWeekHighScore:
    """Session 36 -- ADR-0043 Decision 16: George & Hwang (2004)'s
    52-week-high anomaly. Score = close/trailing_high, never negated --
    closer to the high is more attractive."""

    def test_a_security_at_its_high_scores_higher_than_one_far_below_its_high(self) -> None:
        days = trading_days(date(2020, 1, 2), date(2021, 6, 1))
        # AT_HIGH: rises steadily to today's close, so today IS the 52-week high (ratio 1.0).
        at_high_closes = [50.0 + i * 0.1 for i in range(len(days))]
        # FAR_BELOW: rises then falls sharply, so today's close is well below the peak.
        far_below_closes = [50.0 + i * 0.1 for i in range(len(days) - 20)] + [30.0] * 20
        repo = InMemoryDataRepository(bars=list(make_bars("AT_HIGH", days, at_high_closes)) + list(make_bars("FAR_BELOW", days, far_below_closes)))
        as_of_time = _utc(2021, 5, 28)
        data = _view(repo, as_of_time)

        at_high_score = fifty_two_week_high_score("AT_HIGH", as_of_time, data)
        far_below_score = fifty_two_week_high_score("FAR_BELOW", as_of_time, data)

        assert at_high_score is not None and far_below_score is not None
        assert at_high_score == pytest.approx(1.0)
        assert at_high_score > far_below_score

    def test_insufficient_history_returns_none(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 1, 4))
        repo = InMemoryDataRepository(bars=list(make_bars("AAA", days, [100.0] * len(days))))
        as_of_time = _utc(2021, 1, 3)
        data = _view(repo, as_of_time)

        assert fifty_two_week_high_score("AAA", as_of_time, data) is None

    def test_unknown_security_returns_none(self) -> None:
        days = trading_days(date(2020, 1, 2), date(2021, 6, 1))
        repo = InMemoryDataRepository(bars=list(make_bars("AAA", days, [100.0 + i * 0.05 for i in range(len(days))])))
        as_of_time = _utc(2021, 5, 28)
        data = _view(repo, as_of_time)

        assert fifty_two_week_high_score("NONEXISTENT", as_of_time, data) is None


class TestMaxEffectScore:
    """Session 36 -- ADR-0043 Decision 16: Bali, Cakici & Whitelaw
    (2011)'s MAX effect. Score is the negative of the trailing month's
    single largest daily return -- a lottery-like spike lowers the
    score, matching this module's convention (see leverage_score)."""

    def test_a_security_with_no_spike_scores_higher_than_one_with_a_spike(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 2, 1))
        steady_closes = [100.0 * (1.001**i) for i in range(len(days))]
        spike_closes = list(steady_closes)
        spike_closes[-3] = spike_closes[-4] * 1.25  # one large single-day jump near the end
        repo = InMemoryDataRepository(bars=list(make_bars("STEADY", days, steady_closes)) + list(make_bars("SPIKE", days, spike_closes)))
        as_of_time = _utc(days[-1].year, days[-1].month, days[-1].day)
        data = _view(repo, as_of_time)

        steady_score = max_effect_score("STEADY", as_of_time, data)
        spike_score = max_effect_score("SPIKE", as_of_time, data)

        assert steady_score is not None and spike_score is not None
        assert steady_score > spike_score  # no lottery-like spike -> higher (more attractive) score

    def test_insufficient_history_returns_none(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 1, 4))
        repo = InMemoryDataRepository(bars=list(make_bars("AAA", days, [100.0] * len(days))))
        as_of_time = _utc(2021, 1, 3)
        data = _view(repo, as_of_time)

        assert max_effect_score("AAA", as_of_time, data, lookback_days=21) is None

    def test_unknown_security_returns_none(self) -> None:
        days = trading_days(date(2021, 1, 2), date(2021, 2, 1))
        repo = InMemoryDataRepository(bars=list(make_bars("AAA", days, [100.0 * (1.001**i) for i in range(len(days))])))
        as_of_time = _utc(days[-1].year, days[-1].month, days[-1].day)
        data = _view(repo, as_of_time)

        assert max_effect_score("NONEXISTENT", as_of_time, data) is None


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


def _q_record(security_id, record_id, *, concept, value, period_end, available_time=None, fiscal_period="Q2"):
    available_time = available_time or period_end
    return FundamentalRecord(
        security_id=security_id, concept=concept, period_end=period_end, fiscal_year=period_end.year,
        fiscal_period=fiscal_period, form_type="10-Q", value=value, unit="USD",
        available_time=available_time, ingestion_time=available_time,
        provenance=Provenance(
            source="sec_edgar", source_dataset=f"sec_edgar_companyfacts_{security_id}",
            source_record_id=record_id, retrieved_at=available_time, data_version="v1",
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


class TestGrossProfitabilityScore:
    """Session 36 -- ADR-0043 Decision 15: Novy-Marx (2013)'s gross
    profitability premium, (Revenues - CostOfGoodsAndServicesSold) /
    Assets."""

    def test_computes_gross_profit_over_assets(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=100.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cogs", concept="CostOfGoodsAndServicesSold", value=60.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets", concept="Assets", value=200.0, period_end=_utc(2022, 12, 31)))

        assert gross_profitability_score("AAA", _utc(2023, 6, 1), repo) == pytest.approx(0.2)  # (100-60)/200

    def test_cogs_exceeding_revenue_produces_a_negative_score_not_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=100.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cogs", concept="CostOfGoodsAndServicesSold", value=150.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets", concept="Assets", value=200.0, period_end=_utc(2022, 12, 31)))

        score = gross_profitability_score("AAA", _utc(2023, 6, 1), repo)
        assert score is not None and score < 0

    def test_zero_or_negative_assets_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=100.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cogs", concept="CostOfGoodsAndServicesSold", value=60.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets", concept="Assets", value=0.0, period_end=_utc(2022, 12, 31)))

        assert gross_profitability_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_missing_cogs_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=100.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets", concept="Assets", value=200.0, period_end=_utc(2022, 12, 31)))

        assert gross_profitability_score("AAA", _utc(2023, 6, 1), repo) is None


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


class TestSloanAccrualsScore:
    """Session 36 -- ADR-0043 Decision 11: Sloan (1996)'s accruals
    anomaly. Uses the Hribar & Collins (2002) cash-flow-statement
    definition (NetIncomeLoss - CFO, scaled by average total assets),
    needing zero new data beyond what roa_score/piotroski_f_score
    already ingest."""

    def test_computes_negative_of_accruals_over_average_assets(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=30.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_prior", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_current", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        score = sloan_accruals_score("AAA", _utc(2023, 6, 1), repo)
        # accruals = (20 - 30) / avg(100, 120) = -10 / 110; score = +10/110
        assert score == pytest.approx(10.0 / 110.0)

    def test_missing_net_income_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=30.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_prior", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_current", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        assert sloan_accruals_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_missing_cfo_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_prior", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_current", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        assert sloan_accruals_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_only_one_fiscal_year_of_assets_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=30.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_current", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))

        assert sloan_accruals_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_zero_or_negative_average_assets_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=30.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_prior", concept="Assets", value=-10.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_current", concept="Assets", value=10.0, period_end=_utc(2022, 12, 31)))

        assert sloan_accruals_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_lower_accruals_scores_higher_matching_the_higher_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        for security_id, cfo in (("LOW_ACCRUAL", 90.0), ("HIGH_ACCRUAL", 20.0)):
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=100.0, period_end=_utc(2022, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=cfo, period_end=_utc(2022, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets_prior", concept="Assets", value=500.0, period_end=_utc(2021, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets_current", concept="Assets", value=500.0, period_end=_utc(2022, 12, 31)))

        low_score = sloan_accruals_score("LOW_ACCRUAL", _utc(2023, 6, 1), repo)
        high_score = sloan_accruals_score("HIGH_ACCRUAL", _utc(2023, 6, 1), repo)
        assert low_score > high_score

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_later_fiscal_year(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "ni_2022", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "cfo_2022", concept="NetCashProvidedByUsedInOperatingActivities", value=30.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_2021", concept="Assets", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "assets_2022", concept="Assets", value=120.0, period_end=_utc(2022, 12, 31)))
        # A much larger, not-yet-filed FY2023 net income that would
        # change the score if it leaked in.
        repo.add_fundamental(_fy_record(
            "AAA", "ni_2023_future", concept="NetIncomeLoss", value=-999.0,
            period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
        ))

        score = sloan_accruals_score("AAA", _utc(2023, 6, 1), repo)
        assert score == pytest.approx(10.0 / 110.0)  # unchanged -- FY2023 not yet filed


class TestDividendGrowthScore:
    """Session 36 -- ADR-0043 Decision 11: a dividend-growth factor,
    structurally the mirror image of asset_growth_score (same
    _fy_records-based YoY-change shape) but NOT negated, since dividend
    growth is hypothesized positively related to forward returns."""

    def test_computes_yoy_dividend_growth_rate(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "div_prior", concept="PaymentsOfDividends", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "div_current", concept="PaymentsOfDividends", value=150.0, period_end=_utc(2022, 12, 31)))

        score = dividend_growth_score("AAA", _utc(2023, 6, 1), repo)
        assert score == pytest.approx(0.5)

    def test_only_one_fiscal_year_of_dividends_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "div_current", concept="PaymentsOfDividends", value=150.0, period_end=_utc(2022, 12, 31)))

        assert dividend_growth_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_no_dividend_at_all_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        # A company with no PaymentsOfDividends concept filed at all --
        # unlike shareholder_yield_score, this has no "genuine zero"
        # reading here: a growth RATE from a zero/absent base is
        # structurally undefined, not a payout level.
        repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=20.0, period_end=_utc(2022, 12, 31)))

        assert dividend_growth_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_zero_or_negative_prior_dividend_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "div_prior", concept="PaymentsOfDividends", value=0.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "div_current", concept="PaymentsOfDividends", value=50.0, period_end=_utc(2022, 12, 31)))

        # A newly-initiated dividend has no computable growth RATE from
        # a zero base -- would compute to a spurious infinite/undefined
        # growth if divided through.
        assert dividend_growth_score("AAA", _utc(2023, 6, 1), repo) is None

    def test_higher_growth_scores_higher_matching_the_higher_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        for security_id, current in (("FAST_GROWER", 200.0), ("SLOW_GROWER", 105.0)):
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:prior", concept="PaymentsOfDividends", value=100.0, period_end=_utc(2021, 12, 31)))
            repo.add_fundamental(_fy_record(security_id, f"{security_id}:current", concept="PaymentsOfDividends", value=current, period_end=_utc(2022, 12, 31)))

        fast_score = dividend_growth_score("FAST_GROWER", _utc(2023, 6, 1), repo)
        slow_score = dividend_growth_score("SLOW_GROWER", _utc(2023, 6, 1), repo)
        assert fast_score > slow_score

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_third_fiscal_year(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        repo.add_fundamental(_fy_record("AAA", "div_2021", concept="PaymentsOfDividends", value=100.0, period_end=_utc(2021, 12, 31)))
        repo.add_fundamental(_fy_record("AAA", "div_2022", concept="PaymentsOfDividends", value=150.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record(
            "AAA", "div_2023_future", concept="PaymentsOfDividends", value=9000.0,
            period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
        ))

        score = dividend_growth_score("AAA", _utc(2023, 6, 1), repo)
        assert score == pytest.approx(0.5)  # unchanged -- FY2023 not yet filed


class TestEarningsYieldScore:
    """Session 36 -- ADR-0043 Decision 11: Basu (1977)'s earnings-yield
    value anomaly (NetIncomeLoss / market cap), the value leg of
    Decision 8's "Value+Momentum combination" candidate -- see
    factor_scores.py's module-level note (above this function) for why
    the momentum leg was not rebuilt (already has a real, null IC
    result on this project's own data)."""

    def test_computes_net_income_over_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        # market_cap = 10.0 * 1000 = 10000; score = 50 / 10000
        assert score == pytest.approx(0.005)

    def test_missing_net_income_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_zero_or_negative_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=0.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[])

        assert earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_uses_raw_close_not_adjusted_close_for_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, adjusted_close=5.0, timestamp=_utc(2023, 5, 25))])

        score = earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(50.0 / (10.0 * 1000.0))  # not 50.0 / (5.0 * 1000.0)

    def test_higher_earnings_yield_scores_higher_matching_the_higher_is_more_attractive_convention(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        for security_id, ni in (("CHEAP", 500.0), ("EXPENSIVE", 50.0)):
            fundamentals_repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=ni, period_end=_utc(2022, 12, 31)))
            fundamentals_repo.add_fundamental(_fy_record(security_id, f"{security_id}:shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[
            _price_bar("CHEAP", "p1", close=10.0, timestamp=_utc(2023, 5, 25)),
            _price_bar("EXPENSIVE", "p2", close=10.0, timestamp=_utc(2023, 5, 25)),
        ])

        cheap_score = earnings_yield_score("CHEAP", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        expensive_score = earnings_yield_score("EXPENSIVE", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert cheap_score > expensive_score

    def test_a_score_at_an_early_date_ignores_a_not_yet_filed_net_income_record(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "ni_2022", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record(
            "AAA", "ni_2023_future", concept="NetIncomeLoss", value=9000.0,
            period_end=_utc(2023, 12, 31), available_time=_utc(2024, 2, 1),
        ))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = earnings_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(0.005)  # still the 2022 net income, not the future 9000.0


class TestBookToMarketScore:
    """Session 36 -- ADR-0043 Decision 12: Fama & French (1992)'s
    book-to-market, computed identically to earnings_yield_score with
    StockholdersEquity in place of NetIncomeLoss."""

    def test_computes_stockholders_equity_over_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=500.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = book_to_market_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(0.05)  # 500 / (10*1000)

    def test_negative_equity_produces_a_negative_directionally_correct_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=-50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = book_to_market_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score is not None and score < 0  # not rejected as None -- negative is meaningful here

    def test_missing_equity_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert book_to_market_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "eq", concept="StockholdersEquity", value=500.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[])

        assert book_to_market_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None


class TestSalesYieldScore:
    """Session 36 -- ADR-0043 Decision 12: O'Shaughnessy's price-to-sales
    leg, inverted to a "yield". Unlike book value, non-positive revenue
    is rejected (None), not left to produce a meaningful negative score."""

    def test_computes_revenues_over_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=200.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = sales_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(0.02)  # 200 / (10*1000)

    def test_zero_or_negative_revenue_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "rev", concept="Revenues", value=0.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert sales_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_revenue_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert sales_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None


class TestRdExpenditureScore:
    """Session 36 continued -- Chan, Lakonishok & Sougiannis 2001 R&D
    expenditure anomaly, found via a GitHub/web search for borrowable
    strategies (paperswithbacktest/awesome-systematic-trading).
    `ResearchAndDevelopmentExpense / market_cap`, same market-cap
    construction as `sales_yield_score`. A genuinely absent tag reads as
    0.0 (real zero R&D spending), never `None` -- the same
    `_fy_flow_or_zero` reasoning `shareholder_yield_score` already uses
    for its own dividend/buyback/issuance concepts."""

    def test_computes_rd_expense_over_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "rd", concept="ResearchAndDevelopmentExpense", value=150.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = rd_expenditure_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(0.015)  # 150 / (10*1000)

    def test_a_genuinely_absent_concept_reads_as_zero_not_a_missing_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        # No ResearchAndDevelopmentExpense tag at all -- a real company
        # (e.g. a bank or retailer) that genuinely did no R&D, per
        # `_fy_flow_or_zero`'s own SEC EDGAR omission-convention docstring.
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = rd_expenditure_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(0.0)

    def test_higher_rd_intensity_scores_higher(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        # Distinct record_ids across both securities -- `provenance_
        # source_record_id` is this table's natural key (`ON CONFLICT
        # DO NOTHING`), not scoped by security_id, so a repeated id
        # across two securities silently drops the second insert.
        fundamentals_repo.add_fundamental(_fy_record("HIGH", "rd_high", concept="ResearchAndDevelopmentExpense", value=400.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("HIGH", "shares_high", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("LOW", "rd_low", concept="ResearchAndDevelopmentExpense", value=20.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("LOW", "shares_low", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[
            _price_bar("HIGH", "p1", close=10.0, timestamp=_utc(2023, 5, 25)),
            _price_bar("LOW", "p2", close=10.0, timestamp=_utc(2023, 5, 25)),
        ])

        high_score = rd_expenditure_score("HIGH", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        low_score = rd_expenditure_score("LOW", _utc(2023, 6, 1), fundamentals_repo, price_repo)

        assert high_score is not None and low_score is not None
        assert high_score > low_score

    def test_missing_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "rd", concept="ResearchAndDevelopmentExpense", value=150.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert rd_expenditure_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "rd", concept="ResearchAndDevelopmentExpense", value=150.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[])

        assert rd_expenditure_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None


class TestReturnSeasonalityScore:
    """Session 36 continued -- Heston & Sadka 2008 Return Seasonality,
    found via a GitHub/web search for borrowable strategies
    (paperswithbacktest/awesome-systematic-trading, independently
    confirmed by that repo's own `12-month-cycle-in-cross-section-of-
    stocks-returns.py`, the k=1 special case of this factor's more
    general same-calendar-month averaging). A genuinely different
    computational shape from every other factor here -- groups price
    history by CALENDAR MONTH across non-contiguous prior years, rather
    than reading one contiguous trailing window."""

    def _seasonal_closes(self, days, *, seasonal_month: int, seasonal_return: float, base: float = 100.0):
        price = base
        seen_years: set[int] = set()
        closes = []
        for d in days:
            if d.month == seasonal_month and d.year not in seen_years:
                price *= 1.0 + seasonal_return
                seen_years.add(d.year)
            closes.append(price)
        return closes

    def test_a_security_with_a_real_march_seasonal_pattern_scores_higher_than_a_flat_one(self) -> None:
        days = trading_days(date(2015, 6, 1), date(2021, 3, 20))
        seasonal_closes = self._seasonal_closes(days, seasonal_month=3, seasonal_return=0.05)
        flat_closes = [100.0] * len(days)
        repo = InMemoryDataRepository()
        repo.append_bars(make_bars("MARCHJUMPER", days, seasonal_closes))
        repo.append_bars(make_bars("FLAT", days, flat_closes))
        as_of_time = checkpoint(days[-1])  # a day in March 2021
        data = _view(repo, as_of_time)

        seasonal_score = return_seasonality_score("MARCHJUMPER", as_of_time, data)
        flat_score = return_seasonality_score("FLAT", as_of_time, data)

        assert seasonal_score is not None and flat_score is not None
        assert seasonal_score == pytest.approx(0.05, abs=1e-9)  # exact same-ratio every year, by construction
        assert flat_score == pytest.approx(0.0, abs=1e-9)
        assert seasonal_score > flat_score

    def test_fewer_than_min_years_of_same_month_history_returns_none(self) -> None:
        # Only one prior March exists (2020) before as_of_time in March
        # 2021 -- below the default min_years=2 floor.
        days = trading_days(date(2019, 6, 1), date(2021, 3, 20))
        closes = self._seasonal_closes(days, seasonal_month=3, seasonal_return=0.05)
        repo = InMemoryDataRepository(bars=list(make_bars("THIN", days, closes)))
        as_of_time = checkpoint(days[-1])
        data = _view(repo, as_of_time)

        assert return_seasonality_score("THIN", as_of_time, data) is None

    def test_unknown_security_returns_none(self) -> None:
        days = trading_days(date(2015, 6, 1), date(2021, 3, 20))
        closes = self._seasonal_closes(days, seasonal_month=3, seasonal_return=0.05)
        repo = InMemoryDataRepository(bars=list(make_bars("MARCHJUMPER", days, closes)))
        as_of_time = checkpoint(days[-1])
        data = _view(repo, as_of_time)

        assert return_seasonality_score("NONEXISTENT", as_of_time, data) is None


class TestCashflowYieldScore:
    """Session 36 -- ADR-0043 Decision 12: O'Shaughnessy's price-to-
    cash-flow leg, inverted to a "yield". Negative CFO is directionally
    meaningful (not rejected), same as book_to_market_score's negative
    equity."""

    def test_computes_cfo_over_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=300.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = cashflow_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(0.03)  # 300 / (10*1000)

    def test_negative_cfo_produces_a_negative_directionally_correct_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=-50.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = cashflow_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score is not None and score < 0

    def test_missing_cfo_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert cashflow_yield_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None


class TestSizeScore:
    """Session 36 -- ADR-0043 Decision 13: Banz (1981)'s size effect.
    Score is the negative of raw market_cap, so a smaller company scores
    higher (more attractive), matching this module's convention."""

    def test_computes_negative_market_cap(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        score = size_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        assert score == pytest.approx(-10000.0)  # -(10 * 1000)

    def test_smaller_company_scores_higher_than_larger_company(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("SMALL", "small_shares", concept="CommonStockSharesOutstanding", value=100.0, period_end=_utc(2022, 12, 31)))
        fundamentals_repo.add_fundamental(_fy_record("BIG", "big_shares", concept="CommonStockSharesOutstanding", value=1_000_000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[
            _price_bar("SMALL", "p1", close=10.0, timestamp=_utc(2023, 5, 25)),
            _price_bar("BIG", "p2", close=10.0, timestamp=_utc(2023, 5, 25)),
        ])

        small_score = size_score("SMALL", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        big_score = size_score("BIG", _utc(2023, 6, 1), fundamentals_repo, price_repo)

        assert small_score is not None and big_score is not None
        assert small_score > big_score  # smaller market cap -> higher (more attractive) score

    def test_missing_shares_outstanding_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        assert size_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        fundamentals_repo.add_fundamental(_fy_record("AAA", "shares", concept="CommonStockSharesOutstanding", value=1000.0, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[])

        assert size_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None


def _altman_fixture(repo, security_id, *, assets=1000.0, current_assets=400.0, current_liabilities=200.0,
                     retained_earnings=300.0, ebit=150.0, liabilities=500.0, revenue=800.0, shares=100.0) -> None:
    for concept, value in (
        ("Assets", assets), ("AssetsCurrent", current_assets), ("LiabilitiesCurrent", current_liabilities),
        ("RetainedEarningsAccumulatedDeficit", retained_earnings), ("OperatingIncomeLoss", ebit),
        ("Liabilities", liabilities), ("Revenues", revenue), ("CommonStockSharesOutstanding", shares),
    ):
        repo.add_fundamental(_fy_record(security_id, f"{security_id}:{concept}", concept=concept, value=value, period_end=_utc(2022, 12, 31)))


class TestAltmanZScore:
    """Session 36 -- ADR-0043 Decision 16: Altman (1968)'s Z-Score
    distress-risk formula, applied here as a stock-selection signal per
    the Dichev (1998)/Campbell-Hilscher-Szilagyi (2008) distress
    anomaly (higher Z = healthier = more attractive, matching this
    module's convention with no negation needed)."""

    def test_computes_the_five_ratio_discriminant_formula(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        _altman_fixture(fundamentals_repo, "AAA")
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=20.0, timestamp=_utc(2023, 5, 25))])

        score = altman_z_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        # X1=(400-200)/1000=0.2 X2=300/1000=0.3 X3=150/1000=0.15 X4=(20*100)/500=4.0 X5=800/1000=0.8
        # Z = 1.2*0.2 + 1.4*0.3 + 3.3*0.15 + 0.6*4.0 + 1.0*0.8 = 4.355
        assert score == pytest.approx(4.355)

    def test_healthier_company_scores_higher_than_distressed_one(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        _altman_fixture(fundamentals_repo, "HEALTHY")
        _altman_fixture(
            fundamentals_repo, "DISTRESSED", current_assets=150.0, current_liabilities=400.0,
            retained_earnings=-200.0, ebit=-50.0, revenue=300.0,
        )
        price_repo = InMemoryDataRepository(bars=[
            _price_bar("HEALTHY", "p1", close=20.0, timestamp=_utc(2023, 5, 25)),
            _price_bar("DISTRESSED", "p2", close=20.0, timestamp=_utc(2023, 5, 25)),
        ])

        healthy_score = altman_z_score("HEALTHY", _utc(2023, 6, 1), fundamentals_repo, price_repo)
        distressed_score = altman_z_score("DISTRESSED", _utc(2023, 6, 1), fundamentals_repo, price_repo)

        assert healthy_score is not None and distressed_score is not None
        assert healthy_score > distressed_score

    def test_missing_retained_earnings_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        for concept, value in (
            ("Assets", 1000.0), ("AssetsCurrent", 400.0), ("LiabilitiesCurrent", 200.0),
            ("OperatingIncomeLoss", 150.0), ("Liabilities", 500.0), ("Revenues", 800.0),
            ("CommonStockSharesOutstanding", 100.0),
        ):
            fundamentals_repo.add_fundamental(_fy_record("AAA", f"AAA:{concept}", concept=concept, value=value, period_end=_utc(2022, 12, 31)))
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=20.0, timestamp=_utc(2023, 5, 25))])

        assert altman_z_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_zero_liabilities_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        _altman_fixture(fundamentals_repo, "AAA", liabilities=0.0)
        price_repo = InMemoryDataRepository(bars=[_price_bar("AAA", "p1", close=20.0, timestamp=_utc(2023, 5, 25))])

        assert altman_z_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None

    def test_missing_price_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        fundamentals_repo = DuckDBFundamentalsRepository(engine)
        _altman_fixture(fundamentals_repo, "AAA")
        price_repo = InMemoryDataRepository(bars=[])

        assert altman_z_score("AAA", _utc(2023, 6, 1), fundamentals_repo, price_repo) is None


def _add_quality_fixture(repo, security_id, *, roe_income=50.0, roe_equity=100.0, leverage_liabilities=100.0, accruals_cfo=60.0, accruals_ni=None) -> None:
    """Populates every concept quality_minus_junk_score's 3 components
    (roe_score/leverage_score/sloan_accruals_score) need for one
    security at a single fiscal year-end, defaulting to "high quality"
    values (high ROE, low leverage, low accruals) unless overridden."""
    ni = accruals_ni if accruals_ni is not None else roe_income
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=ni, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:eq", concept="StockholdersEquity", value=roe_equity, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:liab", concept="Liabilities", value=leverage_liabilities, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=accruals_cfo, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets_prior", concept="Assets", value=500.0, period_end=_utc(2021, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:assets_current", concept="Assets", value=500.0, period_end=_utc(2022, 12, 31)))


class TestQualityMinusJunkScore:
    """Session 36 -- ADR-0043 Decision 12: Asness, Frazzini & Pedersen's
    quality composite, deferred at ADR-0043 Decision 8 as "too complex"
    -- the real reason was the cross-sectional combination step, now
    unblocked by `compute_universe_ic_series`. A deliberate 3-component
    simplification (profitability/safety/quality only, no growth pillar)
    reusing roe_score/leverage_score/sloan_accruals_score directly."""

    def test_higher_quality_security_scores_higher(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quality_fixture(repo, "GOOD")  # high ROE, low leverage, low accruals (defaults)
        _add_quality_fixture(repo, "JUNK", roe_income=5.0, leverage_liabilities=800.0, accruals_ni=5.0, accruals_cfo=0.0)

        scores = quality_minus_junk_score(["GOOD", "JUNK"], _utc(2023, 6, 1), repo, price_repository=None)

        assert scores["GOOD"] > scores["JUNK"]

    def test_a_security_missing_any_component_is_excluded_from_the_cross_section(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quality_fixture(repo, "COMPLETE_A")
        _add_quality_fixture(repo, "COMPLETE_B")
        # "INCOMPLETE" has ROE inputs but no Liabilities at all -> leverage_score is None.
        repo.add_fundamental(_fy_record("INCOMPLETE", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        repo.add_fundamental(_fy_record("INCOMPLETE", "eq", concept="StockholdersEquity", value=100.0, period_end=_utc(2022, 12, 31)))

        scores = quality_minus_junk_score(
            ["COMPLETE_A", "COMPLETE_B", "INCOMPLETE"], _utc(2023, 6, 1), repo, price_repository=None,
        )

        assert "COMPLETE_A" in scores and "COMPLETE_B" in scores
        assert "INCOMPLETE" not in scores

    def test_fewer_than_two_scorable_securities_returns_an_empty_dict_not_a_fabricated_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quality_fixture(repo, "ONLY_ONE")

        scores = quality_minus_junk_score(["ONLY_ONE"], _utc(2023, 6, 1), repo, price_repository=None)

        assert scores == {}


def _add_value_fixture(repo, security_id, price_repo, *, ni=50.0, equity=500.0, revenue=200.0, cfo=300.0, dividends=100.0, price=10.0, shares=1000.0) -> None:
    """Populates every concept value_composite_score's 5 legs need for
    one security, plus a matching price bar."""
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:ni", concept="NetIncomeLoss", value=ni, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:eq", concept="StockholdersEquity", value=equity, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:rev", concept="Revenues", value=revenue, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:cfo", concept="NetCashProvidedByUsedInOperatingActivities", value=cfo, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:div", concept="PaymentsOfDividends", value=dividends, period_end=_utc(2022, 12, 31)))
    repo.add_fundamental(_fy_record(security_id, f"{security_id}:shares", concept="CommonStockSharesOutstanding", value=shares, period_end=_utc(2022, 12, 31)))
    price_repo.append_bars([_price_bar(security_id, f"{security_id}:p1", close=price, timestamp=_utc(2023, 5, 25))])


class TestValueCompositeScore:
    """Session 36 -- ADR-0043 Decision 12: O'Shaughnessy's Value
    Composite -- 5 of the original 6 legs (EV/EBITDA excluded, a real
    missing-data gap), no "Trending" momentum overlay (deliberately not
    rebuilt, ADR-0043 Decision 11's same reasoning)."""

    def test_cheaper_security_scores_higher_on_every_leg(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        price_repo = InMemoryDataRepository(bars=[])
        _add_value_fixture(repo, "CHEAP", price_repo, ni=500.0, equity=5000.0, revenue=2000.0, cfo=3000.0, dividends=1000.0)
        _add_value_fixture(repo, "EXPENSIVE", price_repo, ni=5.0, equity=50.0, revenue=20.0, cfo=30.0, dividends=0.0)

        scores = value_composite_score(["CHEAP", "EXPENSIVE"], _utc(2023, 6, 1), repo, price_repo)

        assert scores["CHEAP"] > scores["EXPENSIVE"]

    def test_a_security_missing_any_leg_is_excluded_from_the_cross_section(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        price_repo = InMemoryDataRepository(bars=[])
        _add_value_fixture(repo, "COMPLETE_A", price_repo)
        _add_value_fixture(repo, "COMPLETE_B", price_repo)
        # "PARTIAL" has a price and net income but is missing every
        # other leg's inputs (including CommonStockSharesOutstanding,
        # which every leg needs for market cap).
        repo.add_fundamental(_fy_record("PARTIAL", "ni", concept="NetIncomeLoss", value=50.0, period_end=_utc(2022, 12, 31)))
        price_repo.append_bars([_price_bar("PARTIAL", "p1", close=10.0, timestamp=_utc(2023, 5, 25))])

        scores = value_composite_score(["COMPLETE_A", "COMPLETE_B", "PARTIAL"], _utc(2023, 6, 1), repo, price_repo)

        assert "COMPLETE_A" in scores and "COMPLETE_B" in scores
        assert "PARTIAL" not in scores

    def test_fewer_than_two_scorable_securities_returns_an_empty_dict_not_a_fabricated_score(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        price_repo = InMemoryDataRepository(bars=[])
        _add_value_fixture(repo, "ONLY_ONE", price_repo)

        scores = value_composite_score(["ONLY_ONE"], _utc(2023, 6, 1), repo, price_repo)

        assert scores == {}


# Fixed per-security fake values for the 9 legs `combined_factor_score`
# combines. "GOOD" scores higher on every leg, "BAD" lower on every
# leg -- isolates the aggregation logic itself (rank-averaging,
# all-or-nothing missing-data exclusion) from any single underlying
# factor's own real construction/fixture complexity, the same
# monkeypatched-fake-score_fn isolation `test_factor_strategy.py`
# already uses for the generic Strategy wrappers.
_COMBINED_FAKE_PRICE_LEGS = {"GOOD": 10.0, "BAD": 1.0, "MISSING_PRICE_LEG": 5.0}
_COMBINED_FAKE_FUNDAMENTALS_LEGS = {"GOOD": 9.0, "BAD": 0.0, "MISSING_PRICE_LEG": 5.0}
_COMBINED_FAKE_QMJ = {"GOOD": 1.0, "BAD": -1.0, "MISSING_PRICE_LEG": 0.0}


def _fake_short_term_reversal(security_id, as_of_time, data) -> Optional[float]:
    assert isinstance(data, AsOfDataView)  # proves the fresh AsOfDataView wiring
    return _COMBINED_FAKE_PRICE_LEGS.get(security_id)


def _fake_illiquidity(security_id, as_of_time, data) -> Optional[float]:
    assert isinstance(data, AsOfDataView)
    return _COMBINED_FAKE_PRICE_LEGS.get(security_id)


def _fake_fundamentals_leg(security_id, as_of_time, repository) -> Optional[float]:
    return _COMBINED_FAKE_FUNDAMENTALS_LEGS.get(security_id)


def _fake_hybrid_leg(security_id, as_of_time, fundamentals_repository, price_repository) -> Optional[float]:
    return _COMBINED_FAKE_FUNDAMENTALS_LEGS.get(security_id)


def _fake_quality_minus_junk(security_ids, as_of_time, fundamentals_repository, price_repository) -> dict:
    return {sid: _COMBINED_FAKE_QMJ[sid] for sid in security_ids if sid in _COMBINED_FAKE_QMJ}


def _patch_combined_factor_legs(monkeypatch, *, omit=()) -> None:
    """Patches every one of `combined_factor_score`'s 9 underlying legs
    with a fake, unless named in `omit` (left as the real function, so
    a test can exercise a real missing-data path on exactly one leg)."""
    fakes = {
        "short_term_reversal_score": _fake_short_term_reversal,
        "illiquidity_score": _fake_illiquidity,
        "piotroski_f_score": _fake_fundamentals_leg,
        "dividend_growth_score": _fake_fundamentals_leg,
        "sloan_accruals_score": _fake_fundamentals_leg,
        "size_score": _fake_hybrid_leg,
        "altman_z_score": _fake_hybrid_leg,
        "shareholder_yield_score": _fake_hybrid_leg,
        "quality_minus_junk_score": _fake_quality_minus_junk,
    }
    for name, fake in fakes.items():
        if name not in omit:
            monkeypatch.setattr(f"strategy_research.factor_scores.{name}", fake)


class TestCombinedFactorScore:
    """Session 36 -- the "combine several independently-motivated weak
    signals" expansion (see this function's own HYPOTHESIS docstring
    for the RULE-0.8-compliant, sign-based-only leg selection). Uses
    monkeypatched fakes for all 9 underlying legs (matching
    `test_factor_strategy.py`'s isolation approach) rather than
    real per-factor fixtures -- these tests are about the aggregation
    logic (rank-averaging, all-or-nothing exclusion, the fresh
    `AsOfDataView` construction for the 2 price-only legs) itself, not
    about re-testing any individual factor's own already-tested
    construction."""

    def test_a_security_scoring_higher_on_every_leg_scores_higher(self, monkeypatch) -> None:
        _patch_combined_factor_legs(monkeypatch)

        scores = combined_factor_score(["GOOD", "BAD"], _utc(2023, 6, 1), fundamentals_repository=None, price_repository=None)

        assert scores["GOOD"] > scores["BAD"]

    def test_a_security_missing_any_leg_is_excluded_from_the_cross_section(self, monkeypatch) -> None:
        # "MISSING_PRICE_LEG" has every leg except short_term_reversal,
        # forced to None here specifically for this one security.
        _patch_combined_factor_legs(monkeypatch)
        monkeypatch.setattr(
            "strategy_research.factor_scores.short_term_reversal_score",
            lambda security_id, as_of_time, data: None if security_id == "MISSING_PRICE_LEG" else _COMBINED_FAKE_PRICE_LEGS.get(security_id),
        )

        scores = combined_factor_score(
            ["GOOD", "BAD", "MISSING_PRICE_LEG"], _utc(2023, 6, 1), fundamentals_repository=None, price_repository=None,
        )

        assert "GOOD" in scores and "BAD" in scores
        assert "MISSING_PRICE_LEG" not in scores

    def test_a_security_missing_from_quality_minus_junk_is_excluded_before_the_per_security_loop(self, monkeypatch) -> None:
        _patch_combined_factor_legs(monkeypatch)

        scores = combined_factor_score(
            ["GOOD", "BAD", "NOT_IN_QMJ"], _utc(2023, 6, 1), fundamentals_repository=None, price_repository=None,
        )

        assert "GOOD" in scores and "BAD" in scores
        assert "NOT_IN_QMJ" not in scores

    def test_fewer_than_two_scorable_securities_returns_an_empty_dict_not_a_fabricated_score(self, monkeypatch) -> None:
        _patch_combined_factor_legs(monkeypatch)

        scores = combined_factor_score(["GOOD"], _utc(2023, 6, 1), fundamentals_repository=None, price_repository=None)

        assert scores == {}


def _add_quarterly_eps(repo, security_id, values, *, start=_utc(2020, 3, 31), available_times=None) -> None:
    """Adds one `EarningsPerShareDiluted` record per element of `values`,
    spaced exactly 3 months apart starting at `start` -- the spacing
    `sue_score`'s positional "4 quarters ago" indexing assumes.
    `available_times`, if given, overrides the default (filed the same
    day as `period_end`) per index, for point-in-time tests."""
    for i, value in enumerate(values):
        period_end = _utc(start.year + (start.month - 1 + 3 * i) // 12, (start.month - 1 + 3 * i) % 12 + 1, 28)
        available_time = available_times[i] if available_times and available_times[i] is not None else None
        repo.add_fundamental(_q_record(
            security_id, f"{security_id}:eps:{i}", concept="EarningsPerShareDiluted",
            value=value, period_end=period_end, available_time=available_time,
        ))


class TestSueScore:
    """Session 36 continued -- ADR-0084: Foster, Olsen & Shevlin 1984
    Standardized Unexpected Earnings. The first score in this module
    needing QUARTERLY (not fiscal-year) fundamentals data."""

    _STEADY_THEN_POSITIVE_SURPRISE = [
        1.00, 1.05, 1.10, 1.15, 1.10, 1.15, 1.20, 1.25, 1.20, 1.25, 1.30, 2.00,
    ]
    _STEADY_THEN_NEGATIVE_SURPRISE = [
        1.00, 1.05, 1.10, 1.15, 1.10, 1.15, 1.20, 1.25, 1.20, 1.25, 1.30, 0.50,
    ]

    def test_a_large_positive_yoy_surprise_scores_clearly_positive(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quarterly_eps(repo, "AAA", self._STEADY_THEN_POSITIVE_SURPRISE)

        score = sue_score("AAA", _utc(2023, 2, 1), repo)
        assert score is not None and score > 2.0

    def test_a_large_negative_yoy_surprise_scores_clearly_negative(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quarterly_eps(repo, "AAA", self._STEADY_THEN_NEGATIVE_SURPRISE)

        score = sue_score("AAA", _utc(2023, 2, 1), repo)
        assert score is not None and score < -1.0

    def test_perfectly_flat_yoy_earnings_returns_none_not_a_fabricated_zscore(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quarterly_eps(repo, "AAA", [1.00] * 12)

        assert sue_score("AAA", _utc(2023, 2, 1), repo) is None

    def test_fewer_than_twelve_quarters_returns_none(self, tmp_path) -> None:
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        _add_quarterly_eps(repo, "AAA", self._STEADY_THEN_POSITIVE_SURPRISE[:11])

        assert sue_score("AAA", _utc(2023, 2, 1), repo) is None

    def test_a_not_yet_filed_latest_quarter_is_excluded_point_in_time(self, tmp_path) -> None:
        # The 12th quarter is real data but filed AFTER as_of_time --
        # as of that moment only 11 quarters are actually knowable, so
        # this must behave exactly like the 11-quarter case (None), not
        # leak the future quarter's value.
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        available_times = [None] * 11 + [_utc(2023, 6, 1)]
        _add_quarterly_eps(repo, "AAA", self._STEADY_THEN_POSITIVE_SURPRISE, available_times=available_times)

        assert sue_score("AAA", _utc(2023, 2, 1), repo) is None

    def test_a_superseded_earlier_filing_for_the_same_period_is_ignored(self, tmp_path) -> None:
        # _quarterly_records must keep only the LATEST-available_time
        # record per period_end -- an earlier, since-superseded filing
        # sharing a period_end with the "official" one already in the
        # sequence must not be kept as a second, separate entry (which
        # would shift every later quarter's positional "4 quarters ago"
        # lookup off by one).
        engine = new_engine(tmp_path)
        repo = DuckDBFundamentalsRepository(engine)
        # Index 8's period_end is 2022-03-28 -- filed with a realistic
        # ~2-week lag (2022-04-15) instead of the default same-day
        # available_time, to leave room for a bogus preliminary filing
        # dated in between the two.
        available_times = [None] * 8 + [_utc(2022, 4, 15)] + [None] * 3
        _add_quarterly_eps(repo, "AAA", self._STEADY_THEN_POSITIVE_SURPRISE, available_times=available_times)
        clean_score = sue_score("AAA", _utc(2023, 2, 1), repo)

        # A bogus, earlier-filed (but still >= period_end) preliminary
        # value for that same period_end -- superseded by the official
        # 2022-04-15 filing above.
        repo.add_fundamental(_q_record(
            "AAA", "AAA:eps:8:superseded", concept="EarningsPerShareDiluted",
            value=999.0, period_end=_utc(2022, 3, 28), available_time=_utc(2022, 3, 30),
        ))

        score_with_superseded_entry = sue_score("AAA", _utc(2023, 2, 1), repo)
        assert score_with_superseded_entry == clean_score
