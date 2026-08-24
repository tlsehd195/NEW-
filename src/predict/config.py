"""PredictionConfig: every window/threshold the Phase 6 baseline
predictors use, kept out of code -- the same discipline
`regime.config.RegimeConfig` already established (Phase 5 spec section
4), applied here to Prediction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from data_infra.versioning import compute_data_version


@dataclass(frozen=True)
class PredictionConfig:
    version: str = "prediction_config_v1"

    # -- shared lookback for return/volatility estimation --
    lookback_days: int = 60

    # -- default forecast horizon, in trading days --
    horizon_days: int = 5

    # -- RegimeAwarePredictor: how much to damp the drift estimate when
    # the Volatility regime is EXTREME (0 = no damping, 1 = fully zeroed) --
    regime_extreme_vol_damping: float = 0.5
    # Confidence multiplier applied under the same EXTREME-volatility
    # condition (never below 0).
    regime_extreme_vol_confidence_multiplier: float = 0.5

    # -- Fail-closed data-sufficiency gate, applied to every predictor --
    min_data_completeness: float = 0.75

    def configuration_version(self) -> str:
        return compute_data_version(asdict(self))


DEFAULT_PREDICTION_CONFIG = PredictionConfig()
