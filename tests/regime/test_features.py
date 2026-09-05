"""Category: deterministic regime calculation, parameter boundary,
insufficient history, missing data (Phase 5 spec section 13).

Tests the pure feature math (regime/features.py) directly against
hand-constructed `PricePoint` series, independent of any repository or
AsOfDataView plumbing -- these are exactly what needs to be exact and
easy to hand-verify (mirrors Phase 2's own "hand-computed expected
values" discipline for transaction cost/slippage, ADR-0007).
"""

from __future__ import annotations

from datetime import datetime, timezone

from regime.config import RegimeConfig
from regime.enums import CorrelationState, DistributionState, LiquidityState, StressState, TrendState, VolatilityState
from regime.features import (
    compute_correlation,
    compute_distribution_days,
    compute_liquidity,
    compute_stress,
    compute_trend,
    compute_volatility,
)
from regime.points import PricePoint


def _points(prices, *, volumes=None, start=datetime(2024, 1, 1, tzinfo=timezone.utc)) -> list[PricePoint]:
    from datetime import timedelta

    volumes = volumes or [1_000.0] * len(prices)
    return [
        PricePoint(timestamp=start + timedelta(days=i), price=p, volume=v, data_version=f"v{i}")
        for i, (p, v) in enumerate(zip(prices, volumes))
    ]


class TestTrend:
    def test_rising_prices_classified_bull(self) -> None:
        config = RegimeConfig(trend_short_window=5, trend_long_window=20)
        prices = [100.0 * (1.01**i) for i in range(25)]
        state, value, reliability = compute_trend(_points(prices), config)
        assert state == TrendState.BULL
        assert value is not None and value > 0
        assert reliability == 1.0

    def test_falling_prices_classified_bear(self) -> None:
        config = RegimeConfig(trend_short_window=5, trend_long_window=20)
        prices = [100.0 * (0.99**i) for i in range(25)]
        state, value, _ = compute_trend(_points(prices), config)
        assert state == TrendState.BEAR
        assert value is not None and value < 0

    def test_flat_prices_classified_neutral(self) -> None:
        config = RegimeConfig(trend_short_window=5, trend_long_window=20, trend_neutral_band=0.01)
        prices = [100.0] * 25
        state, value, _ = compute_trend(_points(prices), config)
        assert state == TrendState.NEUTRAL
        assert value == 0.0

    def test_insufficient_history_is_unknown_not_guessed(self) -> None:
        config = RegimeConfig(trend_short_window=5, trend_long_window=20)
        prices = [100.0] * 10  # fewer than trend_long_window
        state, value, reliability = compute_trend(_points(prices), config)
        assert state == TrendState.UNKNOWN
        assert value is None
        assert reliability < 1.0

    def test_neutral_band_is_a_parameter_boundary(self) -> None:
        """A signal exactly at the neutral-band edge is NEUTRAL (strict
        `>`/`<` comparison, not `>=`/`<=`); a band set just below the
        computed signal flips the same series to BULL -- verifies the
        boundary is a strict inequality, not silently off by a rounding
        step, without hand-computing the MA arithmetic (fragile)."""
        prices = [100.0, 100.0, 120.0, 100.0]
        probe_config = RegimeConfig(trend_short_window=2, trend_long_window=4, trend_neutral_band=0.0)
        _, signal, _ = compute_trend(_points(prices), probe_config)
        assert signal is not None and signal > 0

        at_boundary = RegimeConfig(trend_short_window=2, trend_long_window=4, trend_neutral_band=signal)
        state_at, value_at, _ = compute_trend(_points(prices), at_boundary)
        assert value_at == signal
        assert state_at == TrendState.NEUTRAL  # `signal > band` is False at equality

        just_inside = RegimeConfig(trend_short_window=2, trend_long_window=4, trend_neutral_band=signal - 1e-9)
        state_inside, _, _ = compute_trend(_points(prices), just_inside)
        assert state_inside == TrendState.BULL

    def test_reliability_scales_with_available_history(self) -> None:
        config = RegimeConfig(trend_short_window=5, trend_long_window=20)
        prices = [100.0] * 10
        _, _, reliability = compute_trend(_points(prices), config)
        assert reliability == 0.5  # 10 / 20


class TestVolatility:
    def test_low_variance_series_classified_low_or_normal(self) -> None:
        config = RegimeConfig(volatility_window=10, volatility_percentile_window=30, min_data_completeness=0.5)
        prices = [100.0 + 0.001 * i for i in range(60)]  # near-deterministic drift, ~zero variance
        state, value, reliability = compute_volatility(_points(prices), config)
        assert state in (VolatilityState.LOW, VolatilityState.NORMAL)
        assert value is not None
        assert reliability == 1.0

    def test_insufficient_history_is_unknown(self) -> None:
        config = RegimeConfig(volatility_window=20, volatility_percentile_window=100)
        prices = [100.0, 101.0, 99.0]
        state, value, _ = compute_volatility(_points(prices), config)
        assert state == VolatilityState.UNKNOWN
        assert value is None

    def test_extreme_move_ranks_above_a_calm_history(self) -> None:
        config = RegimeConfig(
            volatility_window=5, volatility_percentile_window=20,
            volatility_high_percentile=0.75, volatility_extreme_percentile=0.95,
            min_data_completeness=0.5,
        )
        calm = [100.0 * (1 + 0.0005 * ((-1) ** i)) for i in range(40)]
        spike = calm + [100.0, 130.0, 90.0, 140.0, 80.0, 150.0]  # a sudden large-swing tail
        state, value, _ = compute_volatility(_points(spike), config)
        assert state in (VolatilityState.HIGH, VolatilityState.EXTREME)


class TestLiquidity:
    def test_volume_spike_classified_high(self) -> None:
        config = RegimeConfig(liquidity_recent_window=3, liquidity_baseline_window=20)
        baseline_volumes = [1_000.0] * 20
        spike_volumes = baseline_volumes + [5_000.0, 5_000.0, 5_000.0]
        prices = [100.0] * len(spike_volumes)
        state, value, reliability = compute_liquidity(_points(prices, volumes=spike_volumes), config)
        assert state == LiquidityState.HIGH
        assert value is not None and value > config.liquidity_high_ratio
        assert reliability == 1.0

    def test_no_volume_data_is_unknown_not_guessed(self) -> None:
        """A benchmark-derived series has no volume at all (Phase 1's
        BenchmarkPoint has no volume field) -- must be honestly UNKNOWN."""
        config = RegimeConfig()
        prices = [100.0] * 30
        points = [PricePoint(p.timestamp, p.price, None, p.data_version) for p in _points(prices)]
        state, value, reliability = compute_liquidity(points, config)
        assert state == LiquidityState.UNKNOWN
        assert value is None
        assert reliability == 0.0


class TestCorrelation:
    def test_perfectly_correlated_series_classified_high(self) -> None:
        config = RegimeConfig(correlation_window=20, correlation_high_threshold=0.7)
        subject_prices = [100.0 * (1.002**i) for i in range(30)]
        reference_prices = [50.0 * (1.002**i) for i in range(30)]  # identical relative moves
        state, value, reliability = compute_correlation(_points(subject_prices), _points(reference_prices), config)
        assert state == CorrelationState.HIGH
        assert value is not None and value > 0.99
        assert reliability == 1.0

    def test_no_reference_series_is_unknown(self) -> None:
        config = RegimeConfig()
        state, value, reliability = compute_correlation(_points([100.0] * 30), [], config)
        assert state == CorrelationState.UNKNOWN
        assert value is None
        assert reliability == 0.0

    def test_misaligned_timestamps_reduce_reliability(self) -> None:
        from datetime import timedelta

        config = RegimeConfig(correlation_window=20)
        subject = _points([100.0 * (1.001**i) for i in range(30)])
        # Reference series shifted so only half the timestamps overlap.
        reference = _points(
            [50.0 * (1.001**i) for i in range(30)],
            start=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=15),
        )
        state, _, reliability = compute_correlation(subject, reference, config)
        assert reliability < 1.0
        assert state == CorrelationState.UNKNOWN  # too few overlapping points


class TestStress:
    def test_drawdown_with_high_volatility_is_stressed(self) -> None:
        config = RegimeConfig(stress_drawdown_window=20, stress_elevated_drawdown=-0.05, stress_high_drawdown=-0.15)
        prices = [100.0] * 5 + [95.0, 90.0, 85.0, 80.0, 75.0] + [75.0] * 15
        state, value, reliability = compute_stress(prices_to_points(prices), VolatilityState.HIGH, config)
        assert state == StressState.HIGH
        assert value is not None and value <= -0.15
        assert reliability == 1.0

    def test_no_drawdown_low_volatility_is_normal(self) -> None:
        config = RegimeConfig(stress_drawdown_window=20)
        prices = [100.0 + i * 0.1 for i in range(25)]  # monotonically rising, no drawdown
        state, value, _ = compute_stress(prices_to_points(prices), VolatilityState.LOW, config)
        assert state == StressState.NORMAL

    def test_insufficient_history_is_unknown(self) -> None:
        config = RegimeConfig(stress_drawdown_window=20)
        state, value, _ = compute_stress(prices_to_points([100.0]), VolatilityState.NORMAL, config)
        assert state == StressState.UNKNOWN
        assert value is None


def prices_to_points(prices) -> list[PricePoint]:
    return _points(prices)


def _alternating_decline_series(num_points: int) -> tuple[list[float], list[float]]:
    """Every odd index is a -1% decline on double the prior day's
    volume (a "distribution day" by `compute_distribution_days`'s own
    definition); every even index recovers on a quarter of the prior
    day's volume (never itself a distribution day, whether or not it
    happens to be a decline). For `num_points` points, exactly
    `(num_points - 1) // 2` distribution days occur -- easy to
    hand-verify without a formula: odd indices 1, 3, 5, ... up to
    `num_points - 1`."""
    prices = [100.0]
    volumes = [1_000.0]
    for i in range(1, num_points):
        if i % 2 == 1:
            prices.append(prices[-1] * 0.99)
            volumes.append(volumes[-1] * 2)
        else:
            prices.append(prices[-1] / 0.99)
            volumes.append(volumes[-1] / 4)
    return prices, volumes


class TestDistributionDays:
    def test_no_declines_classified_normal(self) -> None:
        config = RegimeConfig(distribution_window=10)
        prices = [100.0 + i * 0.1 for i in range(11)]  # monotonically rising, no decline days at all
        state, value, reliability = compute_distribution_days(_points(prices), config)
        assert state == DistributionState.NORMAL
        assert value == 0.0
        assert reliability == 1.0

    def test_five_distribution_days_classified_elevated(self) -> None:
        config = RegimeConfig(distribution_window=10, distribution_warning_count=5, distribution_high_count=7)
        prices, volumes = _alternating_decline_series(11)  # odd indices 1,3,5,7,9 -> 5 distribution days
        state, value, _ = compute_distribution_days(_points(prices, volumes=volumes), config)
        assert value == 5.0
        assert state == DistributionState.ELEVATED

    def test_seven_distribution_days_classified_high(self) -> None:
        config = RegimeConfig(distribution_window=14, distribution_warning_count=5, distribution_high_count=7)
        prices, volumes = _alternating_decline_series(15)  # odd indices 1,3,...,13 -> 7 distribution days
        state, value, _ = compute_distribution_days(_points(prices, volumes=volumes), config)
        assert value == 7.0
        assert state == DistributionState.HIGH

    def test_decline_without_higher_volume_does_not_count(self) -> None:
        """A decline on LOWER or EQUAL volume than the prior day is not
        institutional distribution by this definition -- must not be
        counted, however sharp the price move."""
        config = RegimeConfig(distribution_window=10)
        prices = [100.0] + [95.0] * 10  # one sharp decline, then flat -- only 1 decline transition at all
        volumes = [2_000.0] + [1_000.0] * 10  # every day's volume is <= the prior day's
        state, value, _ = compute_distribution_days(_points(prices, volumes=volumes), config)
        assert value == 0.0
        assert state == DistributionState.NORMAL

    def test_no_volume_data_is_unknown_not_guessed(self) -> None:
        """A benchmark-derived series has no volume at all (Phase 1's
        BenchmarkPoint has no volume field) -- must be honestly UNKNOWN,
        mirroring `compute_liquidity`'s own handling of the same gap."""
        config = RegimeConfig(distribution_window=10)
        prices = [100.0] * 11
        points = [PricePoint(p.timestamp, p.price, None, p.data_version) for p in _points(prices)]
        state, value, reliability = compute_distribution_days(points, config)
        assert state == DistributionState.UNKNOWN
        assert value is None
        assert reliability == 0.0

    def test_insufficient_history_is_unknown(self) -> None:
        config = RegimeConfig(distribution_window=25)
        prices = [100.0] * 5
        state, value, reliability = compute_distribution_days(_points(prices), config)
        assert state == DistributionState.UNKNOWN
        assert value is None
        assert reliability < 1.0
