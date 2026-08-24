"""Category: regime transition, regime stability/persistence, synthetic
bull/bear/high-volatility scenarios, sensitivity to parameters (Phase 5
spec section 9, 13).

Validates the *behavior* of the regime layer as a classifier, not its
correlation with future returns -- consistent with Phase 5 spec section 9:
regime stability/transition-frequency/persistence, not alpha.
"""

from __future__ import annotations

from datetime import date

from regime_helpers import (
    build_repository, high_volatility, low_volatility, make_bars, trading_days, trend_down, trend_up, view_at,
)

from regime.config import RegimeConfig
from regime.detector import RegimeDetector
from regime.enums import RegimeAxis, TrendState, VolatilityState


def _replay(repo, days, config, security_id="AAA"):
    """Replays the detector at every checkpoint, mirroring how a real
    backtest would query it once per decision step."""
    detector = RegimeDetector(config)
    observations = []
    for i in range(len(days)):
        view = view_at(repo, days, i)
        observations.append(detector.compute_composite(view, security_id))
    return observations


class TestSyntheticScenarios:
    def test_synthetic_bull_scenario_eventually_classified_bull(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days, daily_return=0.004))
        repo = build_repository(bars=bars)
        config = RegimeConfig(trend_long_window=30)

        observations = _replay(repo, days, config)
        late_states = [o.get(RegimeAxis.TREND).state for o in observations[-20:]]
        assert late_states.count("BULL") / len(late_states) > 0.8

    def test_synthetic_bear_scenario_eventually_classified_bear(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_down(days, daily_return=-0.004))
        repo = build_repository(bars=bars)
        config = RegimeConfig(trend_long_window=30)

        observations = _replay(repo, days, config)
        late_states = [o.get(RegimeAxis.TREND).state for o in observations[-20:]]
        assert late_states.count("BEAR") / len(late_states) > 0.8

    def test_synthetic_high_volatility_scenario_classified_high_or_extreme(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        calm_days = trading_days(date(2023, 1, 2), date(2023, 12, 29))
        prices = low_volatility(calm_days) + high_volatility(days)
        all_days = calm_days + days
        bars = make_bars("AAA", all_days, prices)
        repo = build_repository(bars=bars)
        config = RegimeConfig(volatility_window=15, volatility_percentile_window=100)

        detector = RegimeDetector(config)
        view = view_at(repo, all_days, len(all_days) - 1)
        composite = detector.compute_composite(view, "AAA")
        assert composite.get(RegimeAxis.VOLATILITY).state in ("HIGH", "EXTREME")

    def test_calm_then_volatile_shows_a_volatility_regime_transition(self) -> None:
        calm_days = trading_days(date(2023, 1, 2), date(2023, 12, 29))
        volatile_days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        all_days = calm_days + volatile_days
        prices = low_volatility(calm_days) + high_volatility(volatile_days)
        bars = make_bars("AAA", all_days, prices)
        repo = build_repository(bars=bars)
        config = RegimeConfig(volatility_window=15, volatility_percentile_window=100)

        observations = _replay(repo, all_days, config)
        states = [o.get(RegimeAxis.VOLATILITY).state for o in observations]
        # At least one LOW/NORMAL -> HIGH/EXTREME transition actually occurs.
        transitioned = any(
            states[i] in ("LOW", "NORMAL") and states[i + 1] in ("HIGH", "EXTREME")
            for i in range(len(states) - 1)
        )
        assert transitioned


class TestPersistenceAndTransitionFrequency:
    def test_regime_does_not_flicker_every_single_day_in_a_stable_trend(self) -> None:
        """A stable, one-directional trend should not produce more than a
        handful of TREND-axis transitions across the whole window --
        excessive flicker would indicate the classifier is unstable, not
        that the market genuinely regime-switched every day."""
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days, daily_return=0.003))
        repo = build_repository(bars=bars)
        config = RegimeConfig(trend_long_window=30)

        observations = _replay(repo, days, config)
        states = [o.get(RegimeAxis.TREND).state for o in observations]
        transitions = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1])
        # UNKNOWN -> BULL counts as one transition; a healthy classifier
        # over a one-directional trend should settle and stay settled.
        assert transitions <= 3

    def test_regime_persistence_average_run_length_is_multi_day(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days, daily_return=0.003))
        repo = build_repository(bars=bars)
        config = RegimeConfig(trend_long_window=30)

        observations = _replay(repo, days, config)
        states = [o.get(RegimeAxis.TREND).state for o in observations]
        run_lengths = []
        current_run = 1
        for i in range(1, len(states)):
            if states[i] == states[i - 1]:
                current_run += 1
            else:
                run_lengths.append(current_run)
                current_run = 1
        run_lengths.append(current_run)
        assert max(run_lengths) > 10  # at least one long, persistent run


class TestClassificationConsistency:
    def test_same_series_replayed_twice_gives_identical_state_sequence(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        config = RegimeConfig(trend_long_window=30)

        states1 = [o.get(RegimeAxis.TREND).state for o in _replay(repo, days, config)]
        states2 = [o.get(RegimeAxis.TREND).state for o in _replay(repo, days, config)]
        assert states1 == states2


class TestParameterSensitivity:
    def test_wider_neutral_band_produces_fewer_or_equal_non_neutral_calls(self) -> None:
        """Sensitivity to a parameter is expected and healthy -- this
        test only verifies the *direction* of the effect (a wider
        neutral band should never classify strictly more days as
        BULL/BEAR than a narrower one), not that any specific band value
        is "correct" (Phase 5 spec section 15 -- no threshold is fit to
        maximize a return here)."""
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days, daily_return=0.0015))
        repo = build_repository(bars=bars)

        narrow = RegimeConfig(trend_long_window=30, trend_neutral_band=0.001)
        wide = RegimeConfig(trend_long_window=30, trend_neutral_band=0.05)

        narrow_states = [o.get(RegimeAxis.TREND).state for o in _replay(repo, days, narrow)]
        wide_states = [o.get(RegimeAxis.TREND).state for o in _replay(repo, days, wide)]

        narrow_non_neutral = sum(1 for s in narrow_states if s in ("BULL", "BEAR"))
        wide_non_neutral = sum(1 for s in wide_states if s in ("BULL", "BEAR"))
        assert wide_non_neutral <= narrow_non_neutral

    def test_experiment_count_and_configs_are_individually_recorded_not_selected(self) -> None:
        """Running multiple configs (as the previous test does) must not
        collapse into "pick the best-looking one" -- each configuration's
        own configuration_version is independently retrievable, so a
        record of how many configurations were tried is always
        reconstructable (Phase 5 spec section 15, overfitting avoidance)."""
        days = trading_days(date(2024, 1, 2), date(2024, 6, 28))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        configs = [RegimeConfig(trend_neutral_band=b) for b in (0.001, 0.01, 0.05)]
        versions = {
            RegimeDetector(c).compute_composite(view, "AAA").get(RegimeAxis.TREND).configuration_version
            for c in configs
        }
        assert len(versions) == 3  # every distinct config is distinguishable, none silently discarded
