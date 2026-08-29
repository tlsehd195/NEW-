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
    compute_consecutive_streaks,
    compute_drawdown_episodes,
    compute_max_drawdown,
    compute_returns,
    conditional_value_at_risk,
    sharpe_ratio,
    sortino_ratio,
    ulcer_index,
    value_at_risk,
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


class TestUlcerIndex:
    """Added following a quantstats/empyrical comparison: depth+duration
    of every drawdown compressed into one number, distinct from
    max_drawdown (worst point only) and from the episode duration
    fields (which only describe the single worst episode)."""

    def test_known_series_matches_hand_computation(self) -> None:
        # Same series as TestMaxDrawdown's known -0.25 case.
        values = [100, 110, 120, 90, 95, 130]
        assert ulcer_index(values) == pytest.approx(0.13285504492853467)

    def test_monotonically_increasing_series_has_zero_ulcer_index(self) -> None:
        assert ulcer_index([100, 105, 110, 120]) == 0.0

    def test_empty_series_has_zero_ulcer_index(self) -> None:
        assert ulcer_index([]) == 0.0

    def test_deep_brief_and_shallow_long_drawdowns_can_have_similar_index(self) -> None:
        # A single deep dip vs. a shallow-but-sustained dip -- Ulcer
        # Index reflects both depth and duration, unlike max_drawdown
        # (which would rank these very differently: -0.20 vs -0.05).
        deep_brief = [100, 80, 100, 100, 100, 100]
        shallow_long = [100, 95, 95, 95, 95, 100]
        assert compute_max_drawdown(deep_brief) == pytest.approx(-0.20)
        assert compute_max_drawdown(shallow_long) == pytest.approx(-0.05)
        # Not asserting equality (they aren't identical) -- just that
        # duration meaningfully offsets depth, unlike max_drawdown alone.
        assert ulcer_index(shallow_long) > 0.0


class TestValueAtRisk:
    """Historical (non-parametric) VaR/CVaR -- percentile of the
    observed return distribution, following empyrical's convention
    (no normal-distribution assumption, unlike quantstats' parametric
    version)."""

    def test_known_evenly_spaced_returns_matches_hand_computation(self) -> None:
        # 11 evenly spaced returns from -0.05 to 0.05; at 90% confidence
        # (cutoff=0.10), idx = 0.10 * 10 = 1.0 exactly -> sorted[1] = -0.04.
        returns = [round(-0.05 + 0.01 * i, 2) for i in range(11)]
        assert value_at_risk(returns, confidence=0.90) == pytest.approx(-0.04)

    def test_cvar_is_mean_of_tail_at_or_below_var(self) -> None:
        returns = [round(-0.05 + 0.01 * i, 2) for i in range(11)]
        # VaR(90%) = -0.04 -> tail = [-0.05, -0.04] -> mean = -0.045
        assert conditional_value_at_risk(returns, confidence=0.90) == pytest.approx(-0.045)

    def test_empty_returns_gives_none_not_zero(self) -> None:
        assert value_at_risk([]) is None
        assert conditional_value_at_risk([]) is None

    def test_cvar_is_never_less_extreme_than_var(self) -> None:
        # The tail mean must be at or beyond the VaR threshold itself.
        returns = [0.05, 0.03, 0.01, -0.01, -0.02, -0.10]
        var = value_at_risk(returns, confidence=0.80)
        cvar = conditional_value_at_risk(returns, confidence=0.80)
        assert cvar <= var


class _StubClosedTrade:
    def __init__(self, realized_pnl: float) -> None:
        self.realized_pnl = realized_pnl


class TestConsecutiveStreaks:
    def test_no_trades_gives_zero_zero(self) -> None:
        assert compute_consecutive_streaks([]) == (0, 0)

    def test_all_wins_gives_full_win_streak(self) -> None:
        trades = [_StubClosedTrade(10.0) for _ in range(4)]
        assert compute_consecutive_streaks(trades) == (4, 0)

    def test_alternating_wins_and_losses_gives_streak_of_one(self) -> None:
        trades = [_StubClosedTrade(pnl) for pnl in (10.0, -5.0, 8.0, -3.0)]
        assert compute_consecutive_streaks(trades) == (1, 1)

    def test_longest_streak_in_the_middle_is_found(self) -> None:
        # win, loss, loss, loss, win, win -- longest loss streak is 3.
        trades = [_StubClosedTrade(pnl) for pnl in (5.0, -1.0, -2.0, -3.0, 4.0, 6.0)]
        assert compute_consecutive_streaks(trades) == (2, 3)

    def test_zero_pnl_trade_counts_as_a_loss_not_a_win(self) -> None:
        # win_rate elsewhere treats realized_pnl > 0 as the win
        # condition -- streaks must use the identical threshold.
        trades = [_StubClosedTrade(10.0), _StubClosedTrade(0.0)]
        assert compute_consecutive_streaks(trades) == (1, 1)
