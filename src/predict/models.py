"""Prediction data model.

See docs/specifications/PHASE-6-prediction.md sections 5, 7.

`@dataclass(frozen=True)` -- the same immutability discipline every
domain type in this project already uses (Phase 1 `data_infra.models`,
Phase 2 `backtest.orders.Order`, Phase 3 `trade_journal.models`, Phase 5
`regime.models`).

**Structural boundary enforcement**: this type has no `side`, `action`,
`quantity`, or any other order-shaped field, and no method anywhere in
`predict.*` returns an `Order`/`OrderIntent`. This is not just documented
-- `tests/predict/test_boundary.py` verifies it by reflection, mirroring
how Phase 5 structurally verified `AsOfDataView.get_bars` has no
`as_of_time` parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from predict.enums import PredictionMethodType

from trade_journal.enums import TradeProvenance


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be timezone-aware: {value!r}")


@dataclass(frozen=True)
class PredictionOutput:
    prediction_id: str  # "PRED-000001"
    security_id: str
    as_of_time: datetime
    horizon_days: int

    # -- the five concepts PROJECT_MASTER_PLAN.md section 8.1 lists --
    expected_return: Optional[float]
    probability: Optional[float]  # P(return > 0) over the horizon, empirically estimated
    expected_volatility: Optional[float]  # annualized, persistence-of-volatility estimate
    uncertainty: Optional[float]  # dispersion of the expected_return estimate itself
    confidence: Optional[float]  # data-completeness reliability, never a fabricated ML score

    method: str  # e.g. "random_walk_v1", "drift_v1", "regime_aware_drift_v1"
    method_type: PredictionMethodType

    feature_version: str
    data_version: tuple[str, ...]
    method_version: str
    configuration_version: str
    model_version: Optional[str] = None  # reserved -- None for every Phase 6 predictor (no trained model)
    regime_context: Optional[dict] = None  # composite regime label/axis states used as an input, if any

    provenance: TradeProvenance = TradeProvenance.HISTORICAL_SIMULATION
    experiment_id: Optional[str] = None
    recorded_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not self.prediction_id:
            raise ValueError("PredictionOutput.prediction_id must not be empty")
        if not self.security_id:
            raise ValueError("PredictionOutput.security_id must not be empty")
        _require_aware("PredictionOutput.as_of_time", self.as_of_time)
        if self.horizon_days <= 0:
            raise ValueError("PredictionOutput.horizon_days must be positive")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"PredictionOutput.confidence must be in [0, 1]: {self.confidence!r}")
        if self.probability is not None and not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"PredictionOutput.probability must be in [0, 1]: {self.probability!r}")
