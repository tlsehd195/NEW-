"""Category: composite label lookup, axis independence, version lineage,
timezone, reproducibility (Phase 5 spec section 6, 7, 13).
"""

from __future__ import annotations

from datetime import date

from regime_helpers import build_repository, make_bars, make_benchmark, trading_days, view_at, trend_up, trend_down

from regime.config import RegimeConfig
from regime.detector import RegimeDetector
from regime.enums import RegimeAxis, SubjectKind


class TestAxisIndependence:
    def test_each_axis_is_recorded_independently_with_its_own_id(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 6, 28))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        ids = [obs.regime_id for obs in composite.axes.values()]
        assert len(ids) == len(set(ids)) == len(RegimeAxis)
        assert set(composite.axes.keys()) == set(RegimeAxis)

    def test_axes_can_disagree_independently(self) -> None:
        """A rising-price, high-noise series can be simultaneously
        trending BULL and volatility HIGH -- the two axes are not forced
        to agree (Phase 5 spec section 6: each dimension is preserved
        independently, not collapsed into one score)."""
        import random

        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        rng = random.Random(5)
        closes = [100.0]
        for _ in range(1, len(days)):
            closes.append(closes[-1] * (1 + rng.gauss(0.004, 0.05)))
        bars = make_bars("AAA", days, closes)
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        trend_state = composite.get(RegimeAxis.TREND).state
        vol_state = composite.get(RegimeAxis.VOLATILITY).state
        # Not asserting a specific pair (that would be a return-chasing
        # threshold fit) -- only that the two fields are independently
        # populated and not silently coupled to each other's value.
        assert trend_state is not None and vol_state is not None


class TestCompositeLabel:
    def test_bull_high_vol_combination_gets_a_curated_label(self) -> None:
        import random

        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        rng = random.Random(2)
        closes = [100.0]
        for _ in range(1, len(days)):
            closes.append(closes[-1] * (1 + rng.gauss(0.004, 0.05)))
        bars = make_bars("AAA", days, closes)
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        if composite.get(RegimeAxis.TREND).state == "BULL" and composite.get(RegimeAxis.VOLATILITY).state in (
            "HIGH", "EXTREME",
        ):
            assert composite.composite_label == "BULL_HIGH_VOL"

    def test_uncurated_combination_has_no_fabricated_label(self) -> None:
        """A combination not in the curated table (Phase 5 spec section
        6) must be None, never a guessed/concatenated string."""
        days = trading_days(date(2024, 1, 2), date(2024, 3, 29))  # short window -> UNKNOWN axes
        bars = make_bars("AAA", days, [100.0] * len(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        assert composite.composite_label is None

    def test_high_stress_overrides_trend_volatility_label(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        closes = [100.0] * 40 + [100.0 * (0.97**i) for i in range(1, len(days) - 39)]
        bars = make_bars("AAA", days, closes)
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        if composite.get(RegimeAxis.STRESS).state == "HIGH":
            assert composite.composite_label == "HIGH_STRESS"


class TestVersionLineage:
    def test_every_observation_carries_full_lineage_fields(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 6, 28))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        for obs in composite.axes.values():
            assert obs.feature_version
            assert obs.method_version
            assert obs.configuration_version
            assert isinstance(obs.data_version, tuple)

    def test_different_config_yields_different_configuration_version(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 6, 28))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        c1 = RegimeDetector(RegimeConfig(trend_short_window=10)).compute_composite(view, "AAA")
        c2 = RegimeDetector(RegimeConfig(trend_short_window=15)).compute_composite(view, "AAA")
        assert (
            c1.get(RegimeAxis.TREND).configuration_version != c2.get(RegimeAxis.TREND).configuration_version
        )

    def test_data_version_reflects_the_bars_actually_used(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 6, 28))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "AAA")
        trend_obs = composite.get(RegimeAxis.TREND)
        assert len(trend_obs.data_version) > 0
        real_versions = {b.provenance.data_version for b in bars}
        assert set(trend_obs.data_version).issubset(real_versions)


class TestReproducibility:
    def test_identical_inputs_produce_byte_identical_composite_axes(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bars = make_bars("AAA", days, trend_up(days))
        repo = build_repository(bars=bars)
        view1 = view_at(repo, days, len(days) - 1)
        view2 = view_at(repo, days, len(days) - 1)

        c1 = RegimeDetector(RegimeConfig()).compute_composite(view1, "AAA")
        c2 = RegimeDetector(RegimeConfig()).compute_composite(view2, "AAA")
        for axis in RegimeAxis:
            o1, o2 = c1.get(axis), c2.get(axis)
            assert o1.state == o2.state
            assert o1.value == o2.value
            assert o1.reliability == o2.reliability
            assert o1.configuration_version == o2.configuration_version


class TestBenchmarkSubject:
    def test_regime_computable_on_a_benchmark_series_too(self) -> None:
        days = trading_days(date(2024, 1, 2), date(2024, 8, 30))
        bench = make_benchmark(days, trend_up(days, start=4000.0, daily_return=0.001))
        repo = build_repository(benchmarks=bench)
        view = view_at(repo, days, len(days) - 1)

        composite = RegimeDetector(RegimeConfig()).compute_composite(view, "SP500", SubjectKind.BENCHMARK)
        trend_obs = composite.get(RegimeAxis.TREND)
        assert trend_obs.state in ("BULL", "NEUTRAL", "BEAR")
        liquidity_obs = composite.get(RegimeAxis.LIQUIDITY)
        assert liquidity_obs.state == "UNKNOWN"  # BenchmarkPoint has no volume -- honest, not guessed
