"""Category: Drawdown test.

Also exercises the other Performance Metrics (Phase 2 spec section 11)
with hand-computable values.
"""

from __future__ import annotations

import pytest
from backtest_helpers import utc

from backtest.metrics import (
    annualized_volatility,
    cagr,
    calmar_ratio,
    compute_drawdown_episodes,
    compute_max_drawdown,
    compute_returns,
    sharpe_ratio,
    sortino_ratio,
    worst_drawdown_episode,
)


class TestMaxDrawdown:
    def test_known_peak_to_trough_drawdown(self) -> None:
        # Peak 120 -> trough 90 -> (90-120)/120 = -0.25
        values = [100, 110, 120, 90, 95, 130]
        assert compute_max_drawdown(values) == pytest.approx(-0.25)

    def test_monotonically_increasing_series_has_zero_drawdown(self) -> None:
        values = [100, 105, 110, 120]
        assert compute_max_drawdown(values) == 0.0

    def test_single_value_has_zero_drawdown(self) -> None:
        assert compute_max_drawdown([100.0]) == 0.0

    def test_empty_series_has_zero_drawdown(self) -> None:
        assert compute_max_drawdown([]) == 0.0

    def test_drawdown_from_multiple_peaks_picks_the_worst(self) -> None:
        # First drawdown: 100->80 = -20%; second: 150->100 = -33.3%
        values = [100, 80, 150, 100]
        assert compute_max_drawdown(values) == pytest.approx((100 - 150) / 150)


class TestOtherMetrics:
    def test_compute_returns_matches_hand_computation(self) -> None:
        values = [100.0, 110.0, 99.0]
        returns = compute_returns(values)
        assert returns == pytest.approx([0.10, -0.10])

    def test_cagr_over_one_year_doubling(self) -> None:
        start = utc(2020, 1, 1)
        end = utc(2021, 1, 1)
        result = cagr(100.0, 200.0, start, end)
        assert result == pytest.approx(1.0, rel=0.02)

    def test_cagr_zero_years_returns_zero(self) -> None:
        t = utc(2020, 1, 1)
        assert cagr(100.0, 200.0, t, t) == 0.0

    def test_calmar_ratio_divides_cagr_by_abs_drawdown(self) -> None:
        assert calmar_ratio(0.20, -0.10) == pytest.approx(2.0)

    def test_calmar_ratio_zero_drawdown_is_zero(self) -> None:
        assert calmar_ratio(0.20, 0.0) == 0.0

    def test_sharpe_ratio_zero_volatility_is_zero_not_error(self) -> None:
        returns = [0.01, 0.01, 0.01, 0.01]
        assert sharpe_ratio(returns) == 0.0

    def test_sharpe_ratio_positive_for_consistently_positive_excess_returns(self) -> None:
        returns = [0.01, 0.02, 0.015, 0.005, 0.012]
        assert sharpe_ratio(returns, risk_free_rate=0.0) > 0

    def test_sortino_only_penalizes_downside(self) -> None:
        # Same mean, but one has a bigger downside deviation
        low_downside = [0.01, 0.01, -0.001, 0.01]
        high_downside = [0.01, 0.01, -0.05, 0.045]
        s_low = sortino_ratio(low_downside)
        s_high = sortino_ratio(high_downside)
        assert s_low > s_high

    def test_annualized_volatility_scales_with_sqrt_periods(self) -> None:
        returns = [0.01, -0.01, 0.02, -0.02, 0.01]
        vol_daily = annualized_volatility(returns, periods_per_year=252)
        vol_weekly = annualized_volatility(returns, periods_per_year=52)
        assert vol_daily > vol_weekly


class TestDrawdownEpisodes:
    """Added following a comparison against `quantopian/pyfolio`'s
    drawdown table -- depth alone (`compute_max_drawdown`) doesn't say
    how long capital stayed underwater."""

    def test_no_drawdown_produces_no_episodes(self) -> None:
        values = [100, 105, 110, 120]
        timestamps = [utc(2020, 1, d) for d in (1, 2, 3, 4)]
        assert compute_drawdown_episodes(values, timestamps) == ()

    def test_recovered_drawdown_has_recovery_time_and_matches_max_drawdown_depth(self) -> None:
        # Peak 120 (day 3) -> trough 90 (day 4) -> recovers at 130 (day 6)
        values = [100, 110, 120, 90, 95, 130]
        timestamps = [utc(2020, 1, d) for d in (1, 2, 3, 4, 5, 6)]
        episodes = compute_drawdown_episodes(values, timestamps)
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.peak_time == utc(2020, 1, 3)
        assert ep.trough_time == utc(2020, 1, 4)
        assert ep.recovery_time == utc(2020, 1, 6)
        assert ep.depth == pytest.approx(-0.25)  # matches compute_max_drawdown's known value
        assert ep.duration_to_trough_days == 1
        assert ep.recovery_days == 2

    def test_unrecovered_drawdown_has_none_recovery_fields(self) -> None:
        # Series ends still underwater -- must never report recovery_days=0
        # (which would falsely read as "recovered instantly").
        values = [100, 120, 90, 95]
        timestamps = [utc(2020, 1, d) for d in (1, 2, 3, 4)]
        episodes = compute_drawdown_episodes(values, timestamps)
        assert len(episodes) == 1
        ep = episodes[0]
        assert ep.recovery_time is None
        assert ep.recovery_days is None

    def test_multiple_distinct_episodes_are_all_reported(self) -> None:
        # Two separate peak-trough-recovery cycles.
        values = [100, 120, 90, 130, 100, 140]
        timestamps = [utc(2020, 1, d) for d in (1, 2, 3, 4, 5, 6)]
        episodes = compute_drawdown_episodes(values, timestamps)
        assert len(episodes) == 2
        assert episodes[0].recovery_time == utc(2020, 1, 4)
        assert episodes[1].recovery_time == utc(2020, 1, 6)

    def test_worst_drawdown_episode_picks_deepest(self) -> None:
        values = [100, 120, 90, 130, 100, 105]  # first dip is deeper (-0.25 vs second dip's ~-0.19)
        timestamps = [utc(2020, 1, d) for d in (1, 2, 3, 4, 5, 6)]
        episodes = compute_drawdown_episodes(values, timestamps)
        worst = worst_drawdown_episode(episodes)
        assert worst is not None
        assert worst.trough_time == utc(2020, 1, 3)

    def test_worst_drawdown_episode_of_empty_sequence_is_none(self) -> None:
        assert worst_drawdown_episode(()) is None

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError):
            compute_drawdown_episodes([100, 90], [utc(2020, 1, 1)])
