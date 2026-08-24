"""RegimeConfig: every threshold/window used by the Phase 5 baseline
detectors, kept out of code (Phase 5 spec section 4: "구체적인 threshold는
코드에 하드코딩하지 말고 configuration으로 분리한다").

`configuration_version()` reuses Phase 1's content-hash helper
(`data_infra.versioning.compute_data_version`) rather than inventing a
second hashing scheme, so a `RegimeConfig`'s version is computed the same
way `BacktestConfig`'s `configuration_version` already is (Phase 2 spec
section 13) -- identical config -> identical version, any real change ->
a different one, verifiable independently of what the config is used for.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class RegimeConfig:
    version: str = "regime_config_v1"

    # -- Trend: short/long moving-average relationship (Phase 5 spec section 4) --
    trend_short_window: int = 20
    trend_long_window: int = 100
    trend_neutral_band: float = 0.005  # +/- 0.5% MA gap treated as NEUTRAL

    # -- Volatility: realized volatility, percentile-classified against its
    # own trailing history (never against the full/future sample) --
    volatility_window: int = 20
    volatility_percentile_window: int = 100
    volatility_low_percentile: float = 0.25
    volatility_high_percentile: float = 0.75
    volatility_extreme_percentile: float = 0.95

    # -- Liquidity: recent vs. baseline average volume ratio --
    liquidity_recent_window: int = 5
    liquidity_baseline_window: int = 60
    liquidity_low_ratio: float = 0.5
    liquidity_high_ratio: float = 1.5

    # -- Correlation: rolling correlation of subject vs. a reference series --
    correlation_window: int = 60
    correlation_high_threshold: float = 0.7
    correlation_low_threshold: float = 0.3

    # -- Stress: composite of Volatility state + trailing drawdown --
    stress_drawdown_window: int = 60
    stress_elevated_drawdown: float = -0.10
    stress_high_drawdown: float = -0.20

    # -- Fail-closed data-sufficiency gate, applied to every axis --
    min_data_completeness: float = 0.75  # below this, state is forced UNKNOWN

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_REGIME_CONFIG = RegimeConfig()
