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
    compute_max_drawdown,
    compute_returns,
    sharpe_ratio,
    sortino_ratio,
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
